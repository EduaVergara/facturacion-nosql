"""Pruebas del contrato DynamoDB con serializacion y transacciones reales de SDK/moto."""
import importlib.util
import os
import unittest
from unittest.mock import patch

from invoice_support import P1, initial_items, sale
from catalogo.model import ApiError
from facturacion.model import intention, intention_hash, invoice_document, request_record
from facturacion.repository import CommitConflict, InvoiceRepository
from facturacion.service import InvoiceService

AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("boto3", "moto"))


@unittest.skipUnless(AVAILABLE, "Requiere boto3 y moto; ejecutar dentro de cdk-dev")
class InvoiceDynamoTests(unittest.TestCase):
    def setUp(self):
        import boto3
        from moto import mock_aws
        environment = {key: value for key, value in os.environ.items() if not key.startswith("AWS_ENDPOINT_URL")}
        environment.update(AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", AWS_DEFAULT_REGION="us-east-1")
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.table = boto3.resource("dynamodb").create_table(TableName="TestFacturas", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}])
        for item in initial_items():
            self.table.put_item(Item=item)
        self.repo = InvoiceRepository(client=boto3.client("dynamodb"), table_name="TestFacturas")
        self.service = InvoiceService(self.repo, sleep=lambda _: None)
        self.data = sale()

    def prepared(self):
        data = intention(self.data)
        products, customer, box = self.service.snapshot(data)
        doc = invoice_document(data, products, customer)
        receipt = request_record(data, intention_hash(data), doc)
        return doc, receipt, products, customer, box

    def test_sdk_transaction_writes_document_and_receipt(self):
        result = self.service.create(self.data)
        saved = self.repo.get(f"FACTURA#{result['factura']['factura_id']}", "DOCUMENTO")
        self.assertEqual(saved["total_centavos"], 31253)
        self.assertIs(type(saved["lineas"][0]["cantidad"]), int)
        receipt = self.repo.get(f"SOLICITUD#c01#{self.data['solicitud_id']}", "RESULTADO")
        self.assertEqual(receipt["factura_id"], saved["factura_id"])
        self.assertEqual(self.service.invoice(saved["factura_id"]), result["factura"])

    def test_sdk_replay_returns_existing_after_catalog_changes(self):
        first = self.service.create(self.data)
        self.table.delete_item(Key={"PK": f"PRODUCTO#{P1}", "SK": "DATOS"})
        self.assertEqual(self.service.create(self.data)["factura"], first["factura"])

    def test_product_version_conflict_rolls_back_both_puts(self):
        args = self.prepared()
        product = self.repo.get(f"PRODUCTO#{P1}", "DATOS")
        self.table.put_item(Item={**product, "version": 2})
        with self.assertRaises(CommitConflict) as failure:
            self.repo.commit(*args, token=self.data["solicitud_id"])
        self.assertEqual(failure.exception.kind, "conditional")
        self.assertIsNone(self.repo.get(args[0]["PK"], "DOCUMENTO"))
        self.assertIsNone(self.repo.get(args[1]["PK"], "RESULTADO"))

    def test_client_version_conflict_rolls_back_both_puts(self):
        args = self.prepared()
        client = self.repo.get("CLIENTE#CC#00001", "PERFIL")
        self.table.put_item(Item={**client, "version": 2})
        with self.assertRaises(CommitConflict):
            self.repo.commit(*args, token=self.data["solicitud_id"])
        self.assertIsNone(self.repo.get(args[0]["PK"], "DOCUMENTO"))
        self.assertIsNone(self.repo.get(args[1]["PK"], "RESULTADO"))

    def test_inactive_box_conflict_rolls_back_both_puts(self):
        args = self.prepared()
        box = self.repo.get("CONFIG#CAJAS", "CAJA#c01")
        self.table.put_item(Item={**box, "activo": False})
        with self.assertRaises(CommitConflict):
            self.repo.commit(*args, token=self.data["solicitud_id"])
        self.assertIsNone(self.repo.get(args[0]["PK"], "DOCUMENTO"))

    def test_receipt_collision_cannot_create_an_extra_invoice(self):
        args = self.prepared()
        self.table.put_item(Item=args[1])
        with self.assertRaises(CommitConflict):
            self.repo.commit(*args, token=self.data["solicitud_id"])
        self.assertIsNone(self.repo.get(args[0]["PK"], "DOCUMENTO"))

    def test_get_requests_a_strongly_consistent_read(self):
        from unittest.mock import Mock
        client = Mock()
        client.get_item.return_value = {}
        repo = InvoiceRepository(client=client, table_name="TestFacturas")
        self.assertIsNone(repo.get("X", "Y"))
        client.get_item.assert_called_once_with(TableName="TestFacturas", ConsistentRead=True,
            Key={"PK": {"S": "X"}, "SK": {"S": "Y"}})

    def test_sdk_transport_failure_is_sanitized_as_503(self):
        from unittest.mock import Mock
        client = Mock()
        client.get_item.side_effect = TimeoutError("detalle privado")
        repo = InvoiceRepository(client=client, table_name="TestFacturas")
        with self.assertLogs("facturacion.repository", level="ERROR"), self.assertRaises(ApiError) as failure:
            repo.get("X", "Y")
        self.assertEqual(failure.exception.status, 503)
        self.assertNotIn("privado", failure.exception.message)
