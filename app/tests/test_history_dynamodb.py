"""Queries reales del SDK contra los tres indices simulados por moto."""
import importlib.util
import os
import unittest
from unittest.mock import Mock, patch

from history_support import HistoryMemoryRepository, add_invoice
from invoice_support import initial_items
from catalogo.model import ApiError
from facturacion.history import HistoryService, history_parameters
from facturacion.repository import InvoiceRepository

AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("boto3", "moto"))
RANGE = {"desde": "2026-01-15", "hasta": "2026-01-16"}


@unittest.skipUnless(AVAILABLE, "Requiere boto3 y moto en cdk-dev")
class HistoryDynamoTests(unittest.TestCase):
    def setUp(self):
        import boto3
        from moto import mock_aws
        from infra.schema import INDEX_PROJECTIONS
        environment = {key: value for key, value in os.environ.items() if not key.startswith("AWS_ENDPOINT_URL")}
        environment.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", AWS_DEFAULT_REGION="us-east-1")
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        attributes = ["PK", "SK"] + [f"GSI{n}{suffix}" for n in (1,2,3) for suffix in ("PK", "SK")]
        self.table = boto3.resource("dynamodb").create_table(TableName="TestHistorial", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName":"PK","KeyType":"HASH"},{"AttributeName":"SK","KeyType":"RANGE"}],
            AttributeDefinitions=[{"AttributeName": name,"AttributeType":"S"} for name in attributes],
            GlobalSecondaryIndexes=[{"IndexName":name,
                "KeySchema":[{"AttributeName":name+"PK","KeyType":"HASH"},{"AttributeName":name+"SK","KeyType":"RANGE"}],
                "Projection":{"ProjectionType":"INCLUDE","NonKeyAttributes":projection}}
                for name,projection in INDEX_PROJECTIONS.items()])
        self.client = boto3.client("dynamodb")
        self.repo = InvoiceRepository(self.client, "TestHistorial")
        self.service = HistoryService(self.repo)
        self.memory = HistoryMemoryRepository()
        for item in initial_items():
            self.table.put_item(Item=item)

    def add(self, stamp, **kwargs):
        item = add_invoice(self.memory, stamp, **kwargs)
        self.table.put_item(Item=item)
        return item

    def listing(self, kind="cliente", identifier="CC#00001", query=None):
        return self.service.listing(*history_parameters(kind, identifier, query or RANGE))

    def test_three_gsi_queries_return_only_matching_invoice_summaries(self):
        expected = self.add("2026-01-15T12:00:00.000Z")
        general = self.add("2026-01-15T13:00:00.000Z", client="GENERAL", box="c02")
        customer = self.listing()
        box = self.listing("caja", "c01")
        day = self.listing("dia", "", {"fecha":"2026-01-15"})
        self.assertEqual([i["factura_id"] for i in customer["items"]], [expected["factura_id"]])
        self.assertEqual([i["factura_id"] for i in box["items"]], [expected["factura_id"]])
        self.assertEqual({i["factura_id"] for i in day["items"]}, {expected["factura_id"],general["factura_id"]})
        self.assertNotIn("lineas", day["items"][0])
        self.assertIs(type(day["items"][0]["total_centavos"]), int)

    def test_between_bounds_include_start_and_exclude_all_ids_at_end(self):
        outside = [self.add("2026-01-15T04:59:59.999Z"), self.add("2026-01-16T05:00:00.000Z"),
                   self.add("2026-01-16T05:00:00.000Z")]
        inside = [self.add("2026-01-15T05:00:00.000Z"), self.add("2026-01-16T04:59:59.999Z")]
        ids = {item["factura_id"] for item in self.listing()["items"]}
        self.assertEqual(ids, {item["factura_id"] for item in inside})

    def test_sdk_cursor_paginates_over_25_same_timestamp_items(self):
        documents = [self.add("2026-01-15T12:00:00.000Z") for _ in range(29)]
        found, cursor = [], None
        for _ in range(10):
            query = {**RANGE,"limit":"7"}
            if cursor:
                query["cursor"] = cursor
            response = self.listing(query=query)
            found.extend(item["factura_id"] for item in response["items"])
            cursor = response["next_cursor"]
            if not cursor:
                break
        self.assertIsNone(cursor)
        self.assertEqual(found, sorted([item["factura_id"] for item in documents], reverse=True))

    def test_query_contract_uses_projection_key_conditions_and_eventual_read(self):
        self.add("2026-01-15T12:00:00.000Z")
        with patch.object(self.client,"query",wraps=self.client.query) as query:
            self.listing()
        args = query.call_args.kwargs
        self.assertEqual(args["IndexName"],"GSI1")
        self.assertFalse(args["ScanIndexForward"])
        self.assertNotIn("FilterExpression",args)
        self.assertNotIn("ConsistentRead",args)
        self.assertNotIn("lineas",args["ExpressionAttributeNames"].values())
        self.assertEqual(args["ExpressionAttributeValues"][":hi"],{"S":"FACTURA#2026-01-16T05:00:00.000Z"})

    def test_empty_result_and_no_master_gets(self):
        with patch.object(self.client,"get_item",side_effect=AssertionError("Sin joins")):
            self.assertEqual(self.listing(),{"items":[],"next_cursor":None})

    def test_query_failure_is_503_without_internal_details(self):
        with patch.object(self.client,"query",side_effect=TimeoutError("clave privada")), \
             self.assertLogs("facturacion.repository",level="ERROR"), self.assertRaises(ApiError) as failure:
            self.listing()
        self.assertEqual(failure.exception.status,503)
        self.assertNotIn("privada",failure.exception.message)
