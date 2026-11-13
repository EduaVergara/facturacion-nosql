"""Ensayo del comprobador, fixtures idempotentes y contratos de las rutas."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from history_support import HistoryMemoryRepository
from catalogo.service import CatalogService
from facturacion.handler import main

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import check_history


class HistoryCheckFlowTests(unittest.TestCase):
    def checker(self):
        repo = HistoryMemoryRepository()
        checker = object.__new__(check_history.HistoryCheck)
        checker.table_name = "Facturacion"
        checker.repo = repo
        checker.catalog = CatalogService(repo)
        def request(path, query=None, expected=(200,), **unused):
            pieces = path.strip("/").split("/")
            if pieces[0] in {"clientes","cajas"}:
                route, identifier = f"/{pieces[0]}/{{id}}/facturas", pieces[1]
            else:
                route, identifier = ("/facturas/{id}",pieces[1]) if len(pieces)==2 else ("/facturas", "")
            response = main({"resource":route, "httpMethod":"GET", "pathParameters":{"id":identifier},
                             "queryStringParameters":query or {}}, None, repo)
            self.assertIn(response["statusCode"],expected, response["body"])
            return response["statusCode"], json.loads(response["body"]), response["headers"]
        checker.request = request
        return checker

    def test_fixture_and_http_check_cover_all_32_documents(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as directory, patch.object(check_history,"CONTEXT_PATH",Path(directory)/"context.json"):
            data = checker.prepare()
            result = checker.verify(data)
            self.assertEqual(result["estado"],"ok")
            self.assertEqual(result["facturas_cliente_en_dia"],29)
            self.assertEqual(result["paginas_cliente_limite_25"],2)
            self.assertEqual(len(checker.repo.invoices()),32)
            self.assertEqual(len(checker.repo.receipts()),32)

    def test_reusing_context_does_not_add_invoices_after_master_updates(self):
        checker = self.checker()
        with tempfile.TemporaryDirectory() as directory, patch.object(check_history,"CONTEXT_PATH",Path(directory)/"context.json"):
            first = checker.prepare()
            checker.repo.items[("CLIENTE#"+first["customer_id"],"PERFIL")].update(nombre="Nombre editado", version=2)
            for item in checker.repo.items.values():
                if item.get("tipo_entidad") == "PRODUCTO":
                    item["version"] = 2
            second = checker.prepare()
            self.assertEqual(first,second)
            self.assertEqual(len(checker.repo.invoices()),32)
            self.assertEqual(checker.verify(second)["estado"],"ok")
