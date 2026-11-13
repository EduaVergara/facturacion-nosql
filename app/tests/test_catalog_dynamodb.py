"""Pruebas del adaptador real con DynamoDB simulado por moto."""
import importlib.util
import os
import unittest
from unittest.mock import patch

from catalog_support import MemoryRepository
from catalogo.model import ApiError, new_product
from catalogo.repository import DynamoRepository
from catalogo.service import CatalogService

AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("boto3", "moto"))


@unittest.skipUnless(AVAILABLE, "Requiere boto3 y moto dentro de cdk-dev")
class DynamoCatalogTests(unittest.TestCase):
    def setUp(self):
        import boto3
        from moto import mock_aws
        from infra.schema import INDEX_PROJECTIONS
        self.env = patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
                                          "AWS_DEFAULT_REGION": "us-east-1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("AWS_ENDPOINT_URL", None)
        os.environ.pop("AWS_ENDPOINT_URL_DYNAMODB", None)
        mock = mock_aws()
        mock.start()
        self.addCleanup(mock.stop)
        attributes = ["PK", "SK"] + [f"GSI{n}{suffix}" for n in (1, 2, 3) for suffix in ("PK", "SK")]
        self.table = boto3.resource("dynamodb").create_table(
            TableName="TestCatalogo", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": name, "AttributeType": "S"} for name in attributes],
            GlobalSecondaryIndexes=[{
                "IndexName": name,
                "KeySchema": [{"AttributeName": f"{name}PK", "KeyType": "HASH"}, {"AttributeName": f"{name}SK", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": projection},
            } for name, projection in INDEX_PROJECTIONS.items()],
        )
        self.repo = DynamoRepository(table=self.table)
        self.service = CatalogService(self.repo)
        self.data = {"nombre": "Producto moto", "precio_unitario_centavos": 12345, "impuesto_bps": 1000}

    def test_conditional_create_rejects_duplicates(self):
        item = new_product(self.data)
        self.repo.put(item)
        with self.assertRaises(ApiError) as error:
            self.repo.put({**item, "nombre": "No sobrescribir"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.repo.get(item["PK"], item["SK"])["nombre"], "Producto moto")

    def test_conditional_write_rejects_stale_version(self):
        product = self.service.create_product(self.data)
        original = self.repo.get(f"PRODUCTO#{product['producto_id']}", "DATOS")
        self.service.update_product(product["producto_id"], {"version_esperada": 1, "activo": False})
        with self.assertRaises(ApiError) as error:
            self.repo.put({**original, "nombre": "Viejo"}, expected_version=1)
        self.assertEqual(error.exception.status, 409)

    def test_real_query_paginates_projected_products(self):
        for name in ("Alfa", "Beta", "Gamma"):
            self.service.create_product({**self.data, "nombre": name})
        first = self.service.listing("PRODUCTOS", {"limit": "2"})
        second = self.service.listing("PRODUCTOS", {"limit": "2", "cursor": first["next_cursor"]})
        self.assertEqual([p["nombre"] for p in first["items"] + second["items"]], ["Alfa", "Beta", "Gamma"])
        self.assertTrue(all(p.get("producto_id") for p in first["items"]))

    def test_client_directory_uses_same_index_with_other_partition(self):
        self.service.create_product(self.data)
        self.service.create_client({"nombre": "Persona demo", "tipo_documento": "CC", "numero_documento": "000001"})
        clients = self.service.listing("CLIENTES", {})["items"]
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["cliente_id"], "CC#000001")
        self.assertEqual(clients[0]["numero_documento"], "000001")

    def test_box_query_ignores_other_configuration_items(self):
        self.repo.put({"PK": "CONFIG#CAJAS", "SK": "OTRO", "nombre": "No es caja"})
        self.repo.put({"PK": "CONFIG#CAJAS", "SK": "CAJA#c01", "caja_id": "c01"})
        boxes = self.service.listing("CAJAS", {})["items"]
        self.assertEqual([b["caja_id"] for b in boxes], ["c01"])
