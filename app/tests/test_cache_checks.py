"""Ensayo del comprobador completo con handlers y almacenamiento en memoria."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cache_support import MemoryRedis
from invoice_support import InvoiceMemoryRepository
from cache_layer import JsonCache
from catalogo.handler import main as catalog_main
from facturacion.handler import main as invoice_main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_cache


class CheckFlowTests(unittest.TestCase):
    def test_online_offline_and_recovery_exercise_same_api_contract(self):
        repo, cache = InvoiceMemoryRepository(), MemoryRedis()
        cache.ping = lambda: True
        cache.exists = lambda key: int(cache.get(key) is not None)
        def expire(key, milliseconds):
            present = key in cache.entries
            cache.entries.pop(key, None)
            return present
        cache.pexpire = expire
        checker = object.__new__(check_cache.Check)
        checker.api_id = "fake-api"
        checker.table_name = "Facturacion"
        checker.redis = lambda: cache
        def request(path, method="GET", data=None, expected=(200,), **unused):
            if path == "/health":
                result = (503, {"estado": "degradado", "dynamodb": {"estado": "ok"}, "redis": {"estado": "error"}}, {})
            else:
                pieces = path.strip("/").split("/")
                event = {"resource": "/" + pieces[0] + ("/{id}" if len(pieces) == 2 else ""),
                         "httpMethod": method, "pathParameters": {"id": pieces[-1]} if len(pieces) == 2 else {},
                         "headers": {"Content-Type": "application/json"}, "body": json.dumps(data)}
                handler = invoice_main if pieces[0] == "facturas" else catalog_main
                response = handler(event, None, repo, JsonCache(cache))
                result = response["statusCode"], json.loads(response["body"]), response["headers"]
            self.assertIn(result[0], expected)
            return result
        checker.request = request
        fake_boto = Mock()
        table = fake_boto.resource.return_value.Table.return_value
        def get_item(**kwargs):
            self.assertTrue(kwargs["ConsistentRead"])
            key = kwargs["Key"]
            return {"Item": repo.get(key["PK"], key["SK"])}
        table.get_item.side_effect = get_item
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(check_cache, "CONTEXT_PATH", Path(directory)/"demo.json"), \
             patch.dict(sys.modules, {"boto3": fake_boto}):
            self.assertEqual(checker.online()["estado"], "ok")
            cache.fail = {"get"}
            with self.assertLogs("cache_layer", level="WARNING"):
                self.assertEqual(checker.offline()["estado"], "ok")
                self.assertEqual(checker.offline()["estado"], "ok")
            self.assertEqual(len(repo.invoices()), 2)
            self.assertEqual(len(repo.receipts()), 2)
            cache.fail = set()
            self.assertEqual(checker.recovered()["estado"], "ok")
