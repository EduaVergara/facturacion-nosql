import base64
import copy
import json
import unittest
from decimal import Decimal

from catalog_support import MemoryRepository
from catalogo.handler import main
from catalogo.model import ApiError, client_id, json_numbers, new_product
from catalogo.pagination import decode_cursor, encode_cursor, page_limit
from catalogo.service import CatalogService
from scripts.seed_demo import seed


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.repository = MemoryRepository()
        self.service = CatalogService(self.repository)
        self.product_data = {"nombre": "Cuaderno", "precio_unitario_centavos": 10000, "impuesto_bps": 1000}
        self.client_data = {"nombre": "Cliente ficticio", "tipo_documento": "CC", "numero_documento": "000123"}

    def request(self, route, method="GET", data=None, identifier=None, query=None, **extra):
        event = {"resource": route, "httpMethod": method,
                 "headers": {"Content-Type": "application/json"},
                 "pathParameters": {"id": identifier} if identifier else {},
                 "queryStringParameters": query}
        if data is not None:
            event["body"] = json.dumps(data)
        event.update(extra)
        response = main(event, None, repository=self.repository)
        return response["statusCode"], json.loads(response["body"])

    def test_create_product_hides_database_keys(self):
        status, product = self.request("/productos", "POST", self.product_data)
        self.assertEqual(status, 201)
        self.assertEqual(product["version"], 1)
        self.assertEqual(product["precio_unitario_centavos"], 10000)
        self.assertNotIn("PK", product)
        self.assertNotIn("GSI1SK", product)
        self.assertTrue(product["activo"])

    def test_detail_returns_the_saved_product(self):
        product = self.service.create_product(self.product_data)
        status, fetched = self.request("/productos/{id}", identifier=product["producto_id"])
        self.assertEqual(status, 200)
        self.assertEqual(product, fetched)

    def test_product_update_requires_current_version(self):
        product = self.service.create_product(self.product_data)
        updated = self.service.update_product(product["producto_id"], {"version_esperada": 1, "precio_unitario_centavos": 12000})
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["creado_en"], product["creado_en"])
        with self.assertRaises(ApiError) as error:
            self.service.update_product(product["producto_id"], {"version_esperada": 1, "nombre": "Viejo"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.service.product(product["producto_id"])["precio_unitario_centavos"], 12000)

    def test_concurrent_change_is_not_overwritten(self):
        product = self.service.create_product(self.product_data)
        key = f"PRODUCTO#{product['producto_id']}", "DATOS"
        def competing_write():
            self.repository.items[key]["version"] = 2
            self.repository.items[key]["precio_unitario_centavos"] = 777
        self.repository.before_put = competing_write
        with self.assertRaises(ApiError) as error:
            self.service.update_product(product["producto_id"], {"version_esperada": 1, "nombre": "Mi cambio"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.repository.items[key]["precio_unitario_centavos"], 777)

    def test_product_deactivation_is_preserved(self):
        product = self.service.create_product(self.product_data)
        updated = self.service.update_product(product["producto_id"], {"version_esperada": 1, "activo": False})
        self.assertFalse(updated["activo"])

    def test_invalid_money_inputs_are_rejected(self):
        for value in (-1, True, 1.5, "10000", 1_000_000_001):
            with self.subTest(value=value):
                status, _ = self.request("/productos", "POST", {**self.product_data, "precio_unitario_centavos": value})
                self.assertEqual(status, 400)
        self.assertFalse(self.repository.items)

    def test_invalid_tax_inputs_are_rejected(self):
        for value in (-1, 10001, False, "1000"):
            with self.subTest(value=value):
                self.assertEqual(self.request("/productos", "POST", {**self.product_data, "impuesto_bps": value})[0], 400)

    def test_bad_names_and_unknown_fields_are_rejected(self):
        for value in (" ", "x" * 121, "nombre\ninvalido", 123):
            with self.subTest(value=value):
                self.assertEqual(self.request("/productos", "POST", {**self.product_data, "nombre": value})[0], 400)
        self.assertEqual(self.request("/productos", "POST", {**self.product_data, "version": 9})[0], 400)

    def test_invalid_boolean_is_rejected(self):
        self.assertEqual(self.request("/productos", "POST", {**self.product_data, "activo": "false"})[0], 400)

    def test_empty_update_is_rejected(self):
        product = self.service.create_product(self.product_data)
        self.assertEqual(self.request("/productos/{id}", "PUT", {"version_esperada": 1}, product["producto_id"])[0], 400)

    def test_missing_product_is_404(self):
        self.assertEqual(self.request("/productos/{id}", identifier="00000000-0000-4000-8000-000000000099")[0], 404)

    def test_invalid_product_id_is_400(self):
        self.assertEqual(self.request("/productos/{id}", identifier="no-es-uuid")[0], 400)

    def test_client_preserves_leading_zeroes(self):
        status, client = self.request("/clientes", "POST", self.client_data)
        self.assertEqual(status, 201)
        self.assertEqual(client["cliente_id"], "CC#000123")
        self.assertEqual(client["numero_documento"], "000123")

    def test_duplicate_client_is_conflict(self):
        self.service.create_client(self.client_data)
        status, _ = self.request("/clientes", "POST", {**self.client_data, "nombre": "Otro"})
        self.assertEqual(status, 409)
        self.assertEqual(self.service.client("CC#000123")["nombre"], "Cliente ficticio")

    def test_encoded_client_identifier_is_accepted(self):
        self.service.create_client(self.client_data)
        status, client = self.request("/clientes/{id}", identifier="CC%23000123")
        self.assertEqual(status, 200)
        self.assertEqual(client["cliente_id"], "CC#000123")

    def test_client_update_cannot_change_identification(self):
        self.service.create_client(self.client_data)
        status, _ = self.request("/clientes/{id}", "PUT", {"nombre": "Nuevo", "numero_documento": "9", "version_esperada": 1}, "CC#000123")
        self.assertEqual(status, 400)

    def test_client_update_advances_version(self):
        self.service.create_client(self.client_data)
        client = self.service.update_client("CC#000123", {"nombre": "Nombre nuevo", "version_esperada": 1})
        self.assertEqual(client["version"], 2)
        self.assertEqual(client["cliente_id"], "CC#000123")

    def test_invalid_identification_is_400(self):
        for value in ("CC#12#34", "INEXISTENTE#1", "CC#", "CC#1/2"):
            with self.subTest(value=value), self.assertRaises(ApiError):
                client_id(value)

    def test_catalog_pagination_has_no_duplicates(self):
        for name in ("Cebra", "Arbol", "Borrador"):
            self.service.create_product({**self.product_data, "nombre": name})
        first = self.service.listing("PRODUCTOS", {"limit": "2"})
        self.assertEqual([p["nombre"] for p in first["items"]], ["Arbol", "Borrador"])
        self.assertTrue(all(p.get("producto_id") for p in first["items"]))
        second = self.service.listing("PRODUCTOS", {"limit": "2", "cursor": first["next_cursor"]})
        self.assertEqual([p["nombre"] for p in second["items"]], ["Cebra"])
        self.assertIsNone(second["next_cursor"])

    def test_customer_cursor_cannot_be_used_for_products(self):
        key = {"PK": "CLIENTE#CC#1", "SK": "PERFIL", "GSI1PK": "DIRECTORIO#CLIENTES", "GSI1SK": "CLIENTE#a#CC#1"}
        cursor = encode_cursor(key, "CLIENTES")
        with self.assertRaises(ApiError):
            self.service.listing("PRODUCTOS", {"cursor": cursor})

    def test_corrupt_cursor_is_rejected(self):
        for token in ("!", "e30", "" , "x" * 4097):
            with self.subTest(token=token[:10]), self.assertRaises(ApiError):
                decode_cursor(token, "PRODUCTOS")

    def test_bad_page_limits_are_rejected(self):
        for value in ("0", "26", "1.0", "-1", "abc", True):
            with self.subTest(value=value), self.assertRaises(ApiError):
                page_limit(value)

    def test_unknown_query_filter_is_rejected(self):
        self.assertEqual(self.request("/productos", query={"buscar": "algo"})[0], 400)

    def test_client_directory_uses_projected_identity(self):
        self.service.create_client(self.client_data)
        result = self.service.listing("CLIENTES", {})["items"][0]
        self.assertEqual(result["tipo_documento"], "CC")
        self.assertEqual(result["numero_documento"], "000123")

    def test_renamed_product_has_new_sort_position(self):
        first = self.service.create_product({**self.product_data, "nombre": "Zeta"})
        self.service.create_product({**self.product_data, "nombre": "Beta"})
        self.service.update_product(first["producto_id"], {"version_esperada": 1, "nombre": "Alfa"})
        self.assertEqual([p["nombre"] for p in self.service.listing("PRODUCTOS", {})["items"]], ["Alfa", "Beta"])

    def test_seed_can_be_repeated_without_resetting_changes(self):
        self.assertEqual(seed(self.repository)["creados"], 8)
        identifier = "00000000-0000-4000-8000-000000000001"
        self.service.update_product(identifier, {"version_esperada": 1, "precio_unitario_centavos": 999})
        report = seed(self.repository)
        self.assertEqual(report["creados"], 0)
        self.assertEqual(report["existentes_conservados"], 8)
        self.assertEqual(self.service.product(identifier)["precio_unitario_centavos"], 999)

    def test_seed_exposes_two_boxes_and_general_client(self):
        seed(self.repository)
        status, boxes = self.request("/cajas")
        self.assertEqual(status, 200)
        self.assertEqual([b["caja_id"] for b in boxes["items"]], ["c01", "c02"])
        self.assertEqual(self.service.client("GENERAL")["cliente_id"], "GENERAL")

    def test_master_update_does_not_modify_existing_invoice(self):
        product = self.service.create_product(self.product_data)
        invoice = {"PK": "FACTURA#demo", "SK": "DOCUMENTO", "total_centavos": 11000,
                   "lineas": [{"producto_id": product["producto_id"], "precio_unitario_centavos": 10000}]}
        self.repository.put(invoice)
        self.service.update_product(product["producto_id"], {"version_esperada": 1, "precio_unitario_centavos": 20000})
        self.assertEqual(self.repository.get("FACTURA#demo", "DOCUMENTO"), invoice)

    def test_json_content_type_is_required(self):
        self.assertEqual(self.request("/productos", "POST", self.product_data, headers={})[0], 400)

    def test_invalid_json_and_non_object_are_rejected(self):
        for raw in ("{invalido", "[]", "null"):
            with self.subTest(raw=raw):
                self.assertEqual(self.request("/productos", "POST", body=raw)[0], 400)

    def test_oversize_body_is_rejected(self):
        self.assertEqual(self.request("/productos", "POST", body='"' + 'a' * 66000 + '"')[0], 413)

    def test_base64_body_and_charset_are_supported(self):
        raw = base64.b64encode(json.dumps(self.product_data).encode()).decode()
        status, _ = self.request("/productos", "POST", body=raw, isBase64Encoded=True,
                                 headers={"content-type": "application/json; charset=utf-8"})
        self.assertEqual(status, 201)

    def test_unsupported_method_and_route_have_clear_status(self):
        self.assertEqual(self.request("/productos", "DELETE")[0], 405)
        self.assertEqual(self.request("/no-existe")[0], 404)

    def test_dynamodb_integer_conversion_never_uses_float(self):
        self.assertEqual(json_numbers({"a": Decimal("123")}), {"a": 123})
        with self.assertRaises(ValueError):
            json_numbers(Decimal("1.23"))

    def test_backend_outage_is_a_503(self):
        class Offline:
            def get(self, *args):
                raise ApiError(503, "Base no disponible")
        result = main({"resource": "/productos/{id}", "httpMethod": "GET",
                       "pathParameters": {"id": "00000000-0000-4000-8000-000000000001"}}, None, Offline())
        self.assertEqual(result["statusCode"], 503)
