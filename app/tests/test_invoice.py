"""Criterios de negocio: dinero, historico, atomicidad y solicitudes repetidas."""
import copy
import json
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from invoice_support import InvoiceMemoryRepository, P1, P2, sale
from catalogo.model import ApiError
from facturacion.handler import main
from facturacion.model import MAX_DOCUMENT_BYTES, intention, intention_hash, invoice_document
from facturacion.repository import CommitConflict, transaction_actions
from facturacion.service import InvoiceService


class InvoiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = InvoiceMemoryRepository()
        self.sleep = Mock()
        self.service = InvoiceService(self.repo, sleep=self.sleep)
        self.data = sale()

    def assert_error(self, code, callable_, *args):
        with self.assertRaises(ApiError) as error:
            callable_(*args)
        self.assertEqual(error.exception.status, code)
        return error.exception

    def test_full_invoice_and_receipt_are_saved_together(self):
        result = self.service.create(self.data)
        invoice = result["factura"]
        self.assertFalse(result["replayed"])
        self.assertEqual(invoice["subtotal_centavos"], 21252)
        self.assertEqual(invoice["impuestos_centavos"], 10001)
        self.assertEqual(invoice["total_centavos"], 31253)
        self.assertEqual(invoice["cliente"]["numero_documento"], "00001")
        self.assertEqual(len(self.repo.invoices()), 1)
        self.assertEqual(len(self.repo.receipts()), 1)
        self.assertNotIn("PK", invoice)
        self.assertNotIn("GSI1PK", invoice)
        self.assertEqual(self.repo.receipts()[0]["factura_id"], invoice["factura_id"])
        self.assertNotIn("ttl", self.repo.receipts()[0])

    def test_half_cent_rounds_up_per_line(self):
        self.data["lineas"] = [{"producto_id": P1, "cantidad": 1, "version_esperada": 1}]
        invoice = self.service.create(self.data)["factura"]
        self.assertEqual(invoice["impuestos_centavos"], 5001)
        self.assertEqual(invoice["total_centavos"], 15002)

    def test_general_customer_and_free_zero_tax_product(self):
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")].update(precio_unitario_centavos=0, impuesto_bps=0)
        invoice = self.service.create(sale(cliente_id="GENERAL", lineas=[self.data["lineas"][0]]))["factura"]
        self.assertEqual(invoice["total_centavos"], 0)
        self.assertEqual(invoice["cliente"]["tipo_documento"], "GENERAL")

    def test_same_request_returns_original_invoice(self):
        first = self.service.create(self.data)
        second = self.service.create(self.data)
        self.assertTrue(second["replayed"])
        self.assertEqual(second["factura"], first["factura"])
        self.assertEqual(self.repo.commit_calls, 1)

    def test_line_order_does_not_change_intention(self):
        first = self.service.create(self.data)
        changed_order = {**self.data, "lineas": list(reversed(self.data["lineas"]))}
        self.assertEqual(self.service.create(changed_order)["factura"], first["factura"])
        self.assertEqual(intention_hash(intention(self.data)), intention_hash(intention(changed_order)))

    def test_reused_key_with_different_quantity_rejected(self):
        self.service.create(self.data)
        other = copy.deepcopy(self.data)
        other["lineas"][0]["cantidad"] = 9
        error = self.assert_error(409, self.service.create, other)
        self.assertEqual(error.details["codigo"], "SOLICITUD_REUTILIZADA")
        self.assertEqual(len(self.repo.invoices()), 1)

    def test_replay_precedes_catalog_customer_and_box_checks(self):
        original = self.service.create(self.data)["factura"]
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")].update(version=2, activo=False, nombre="Nuevo", precio_unitario_centavos=1)
        del self.repo.items[("CLIENTE#CC#00001", "PERFIL")]
        self.repo.items[("CONFIG#CAJAS", "CAJA#c01")]["activo"] = False
        self.repo.read_calls.clear()
        self.assertEqual(self.service.create(self.data)["factura"], original)
        self.assertEqual(len(self.repo.read_calls), 2)

    def test_history_survives_updates_to_master_records(self):
        original = self.service.create(self.data)["factura"]
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")].update(nombre="Otra descripcion", version=2)
        self.repo.items[("CLIENTE#CC#00001", "PERFIL")].update(nombre="Otro nombre", version=2)
        self.assertEqual(self.service.invoice(original["factura_id"]), original)

    def test_concurrent_commit_before_failed_snapshot_returns_original(self):
        original_snapshot = self.service.snapshot
        def race(data):
            InvoiceService(self.repo).create(self.data)
            del self.repo.items[(f"PRODUCTO#{P1}", "DATOS")]
            return original_snapshot(data)
        self.service.snapshot = race
        result = self.service.create(self.data)
        self.assertTrue(result["replayed"])
        self.assertEqual(len(self.repo.invoices()), 1)

    def test_stale_product_returns_updated_cart_without_writes(self):
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")].update(version=2, precio_unitario_centavos=500)
        error = self.assert_error(409, self.service.create, self.data)
        self.assertEqual(error.details["carrito_actualizado"][0]["precio_unitario_centavos"], 500)
        self.assertEqual(self.repo.invoices(), [])
        self.assertEqual(self.repo.receipts(), [])

    def test_inactive_product_is_rejected(self):
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")]["activo"] = False
        self.assert_error(409, self.service.create, self.data)
        self.assertEqual(self.repo.commit_calls, 0)

    def test_inactive_box_is_rejected(self):
        self.repo.items[("CONFIG#CAJAS", "CAJA#c01")]["activo"] = False
        self.assert_error(409, self.service.create, self.data)
        self.assertEqual(self.repo.commit_calls, 0)

    def test_missing_references_are_404_without_partial_sale(self):
        for key in [(f"PRODUCTO#{P1}", "DATOS"), ("CLIENTE#CC#00001", "PERFIL"), ("CONFIG#CAJAS", "CAJA#c01")]:
            with self.subTest(key=key):
                repo = InvoiceMemoryRepository()
                del repo.items[key]
                self.assert_error(404, InvoiceService(repo).create, self.data)
                self.assertEqual(repo.invoices(), [])
                self.assertEqual(repo.receipts(), [])

    def test_catalog_change_between_read_and_commit_is_atomic(self):
        def concurrent_update():
            self.repo.items[(f"PRODUCTO#{P1}", "DATOS")].update(version=2, precio_unitario_centavos=7)
        self.repo.before_commit = concurrent_update
        self.assert_error(409, self.service.create, self.data)
        self.assertEqual(self.repo.invoices(), [])
        self.assertEqual(self.repo.receipts(), [])

    def test_client_change_between_read_and_commit_is_atomic(self):
        def concurrent_update():
            self.repo.items[("CLIENTE#CC#00001", "PERFIL")]["version"] = 2
        self.repo.before_commit = concurrent_update
        self.assert_error(409, self.service.create, self.data)
        self.assertEqual(self.repo.invoices(), [])

    def test_box_deactivated_between_read_and_commit_is_atomic(self):
        def concurrent_update():
            self.repo.items[("CONFIG#CAJAS", "CAJA#c01")]["activo"] = False
        self.repo.before_commit = concurrent_update
        self.assert_error(409, self.service.create, self.data)
        self.assertEqual(self.repo.receipts(), [])

    def test_two_simultaneous_identical_requests_have_one_invoice(self):
        barrier = threading.Barrier(2)
        def factory(*args):
            document = invoice_document(*args)
            barrier.wait(timeout=5)
            return document
        service = InvoiceService(self.repo, document_factory=factory)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: service.create(self.data), range(2)))
        self.assertEqual({r["factura"]["factura_id"] for r in responses}, {self.repo.invoices()[0]["factura_id"]})
        self.assertEqual(sorted(r["replayed"] for r in responses), [False, True])
        self.assertEqual(len(self.repo.invoices()), 1)
        self.assertEqual(len(self.repo.receipts()), 1)

    def test_two_boxes_can_record_different_sales(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(self.service.create, [sale(caja_id="c01"), sale(caja_id="c02")]))
        self.assertEqual(len({r["factura"]["factura_id"] for r in responses}), 2)
        self.assertEqual(len(self.repo.invoices()), 2)

    def test_same_request_id_is_scoped_to_each_box(self):
        self.service.create(self.data)
        second = self.service.create({**self.data, "caja_id": "c02"})
        self.assertFalse(second["replayed"])
        self.assertEqual(len(self.repo.invoices()), 2)

    def test_simultaneous_different_intentions_cannot_share_one_key(self):
        other = copy.deepcopy(self.data)
        other["lineas"][0]["cantidad"] = 4
        barrier = threading.Barrier(2)
        def factory(*args):
            document = invoice_document(*args)
            barrier.wait(timeout=5)
            return document
        service = InvoiceService(self.repo, document_factory=factory)
        def attempt(body):
            try:
                return service.create(body)
            except ApiError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [self.data, other]))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn(409, results)
        self.assertEqual(len(self.repo.invoices()), 1)
        self.assertEqual(len(self.repo.receipts()), 1)

    def test_maximum_cart_uses_54_actions_and_exact_safe_integer_totals(self):
        lines = []
        prototype = self.repo.items[(f"PRODUCTO#{P1}", "DATOS")]
        for _ in range(50):
            identifier = str(uuid.uuid4())
            product = {**prototype, "PK": f"PRODUCTO#{identifier}", "producto_id": identifier,
                       "precio_unitario_centavos": 1_000_000_000, "impuesto_bps": 10000}
            self.repo.items[(product["PK"], "DATOS")] = product
            lines.append({"producto_id": identifier, "cantidad": 9999, "version_esperada": 1})
        data = intention(sale(lineas=lines))
        products, customer, box = self.service.snapshot(data)
        result = self.service.create(data)
        self.assertEqual(result["factura"]["total_centavos"], 999_900_000_000_000)
        actions = transaction_actions("Facturacion", self.repo.invoices()[0], self.repo.receipts()[0],
                                      products, customer, box, lambda item: item)
        self.assertEqual(len(actions), 54)

    def test_transient_conflict_retries_same_transport_token(self):
        self.repo.failures = [CommitConflict("retryable"), CommitConflict("retryable")]
        self.assertFalse(self.service.create(self.data)["replayed"])
        self.assertEqual(len(set(self.repo.tokens)), 1)
        self.assertEqual(self.sleep.call_count, 2)

    def test_exhausted_conflicts_return_503_and_keep_key_reusable(self):
        self.repo.failures = [CommitConflict("retryable")] * 3
        self.assert_error(503, self.service.create, self.data)
        self.assertEqual(self.repo.invoices(), [])
        self.assertFalse(self.service.create(self.data)["replayed"])

    def test_uncertain_response_after_commit_is_resolved_by_receipt(self):
        real_commit = self.repo.commit
        def commit_then_lose_response(*args):
            real_commit(*args)
            raise ApiError(503, "Respuesta perdida")
        self.repo.commit = commit_then_lose_response
        result = self.service.create(self.data)
        self.assertTrue(result["replayed"])
        self.assertEqual(len(self.repo.invoices()), 1)

    def test_database_failure_does_not_report_success(self):
        self.repo.failures = [ApiError(503, "No disponible")]
        self.assert_error(503, self.service.create, self.data)
        self.assertEqual(self.repo.invoices(), [])

    def test_bogota_day_and_utc_timestamp_are_distinct(self):
        data = intention(self.data)
        products, customer, _ = self.service.snapshot(data)
        invoice = invoice_document(data, products, customer, instant=datetime(2026, 11, 12, 3, 0, tzinfo=timezone.utc))
        self.assertEqual(invoice["fecha_utc"], "2026-11-12T03:00:00.000Z")
        self.assertEqual(invoice["fecha_local"], "2026-11-11")
        self.assertEqual(invoice["GSI3PK"], "VENTAS#DIA#2026-11-11")
        midnight = invoice_document(data, products, customer, instant=datetime(2026, 11, 12, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(midnight["fecha_local"], "2026-11-12")

    def test_invalid_quantities_and_versions_are_rejected(self):
        for field, values in [("cantidad", [True, False, 0, -1, 1.5, "2", 10000]),
                              ("version_esperada", [True, 0, "1", 2**31])]:
            for value in values:
                with self.subTest(field=field, value=value):
                    data = copy.deepcopy(self.data)
                    data["lineas"][0][field] = value
                    self.assert_error(400, self.service.create, data)
        self.assertEqual(self.repo.commit_calls, 0)

    def test_duplicate_products_are_rejected(self):
        self.assert_error(400, self.service.create, sale(lineas=[self.data["lineas"][0]] * 2))

    def test_empty_or_excessive_cart_is_rejected(self):
        for lines in [[], None, {}, self.data["lineas"] * 26]:
            with self.subTest(lines_type=type(lines).__name__):
                self.assert_error(400, self.service.create, sale(lineas=lines))

    def test_cannot_supply_prices_or_totals(self):
        for extra in [{"total_centavos": 1}, {"fecha_utc": "ayer"}, {"cliente": {}}]:
            with self.subTest(extra=extra):
                self.assert_error(400, self.service.create, {**self.data, **extra})
        line = {**self.data["lineas"][0], "precio_unitario_centavos": 1}
        self.assert_error(400, self.service.create, sale(lineas=[line]))

    def test_invalid_identifiers_and_operators(self):
        for changes in [{"solicitud_id": "x"}, {"caja_id": "c#01"}, {"cliente_id": "CC#"},
                        {"operador_declarado": ""}, {"operador_declarado": "a\nb"}]:
            with self.subTest(changes=changes):
                self.assert_error(400, self.service.create, sale(**changes))

    def test_size_limit_checked_before_commit(self):
        with patch("facturacion.model.MAX_DOCUMENT_BYTES", 20):
            self.assert_error(413, self.service.create, self.data)
        self.assertEqual(self.repo.commit_calls, 0)

    def test_not_found_and_invalid_invoice_id(self):
        self.assert_error(404, self.service.invoice, str(uuid.uuid4()))
        self.assert_error(400, self.service.invoice, "not-uuid")

    def test_transaction_has_two_conditional_puts_and_distinct_checks(self):
        data = intention(self.data)
        products, customer, box = self.service.snapshot(data)
        document = invoice_document(data, products, customer)
        receipt = {"PK": "SOLICITUD#demo", "SK": "RESULTADO"}
        actions = transaction_actions("Facturacion", document, receipt, products, customer, box, lambda x: x)
        self.assertEqual(len(actions), 6)
        self.assertEqual([set(action).pop() for action in actions[:2]], ["Put", "Put"])
        self.assertTrue(all(a["Put"]["ConditionExpression"] == "attribute_not_exists(PK)" for a in actions[:2]))
        targets = []
        for action in actions:
            body = next(iter(action.values()))
            item = body.get("Item", body.get("Key"))
            targets.append((item["PK"], item["SK"]))
        self.assertEqual(len(targets), len(set(targets)))


class InvoiceHttpTests(unittest.TestCase):
    def setUp(self):
        self.repo = InvoiceMemoryRepository()

    def event(self, data=None, **changes):
        return {"resource": "/facturas", "httpMethod": "POST", "headers": {"Content-Type": "application/json"},
                "body": json.dumps(data if data is not None else sale()), **changes}

    def test_post_replay_and_get_status_codes(self):
        event = self.event()
        first = main(event, None, self.repo)
        self.assertEqual(first["statusCode"], 201)
        self.assertEqual(main(event, None, self.repo)["statusCode"], 200)
        invoice = json.loads(first["body"])["factura"]
        found = main(self.event(resource="/facturas/{id}", httpMethod="GET",
            pathParameters={"id": invoice["factura_id"]}), None, self.repo)
        self.assertEqual(json.loads(found["body"]), invoice)

    def test_bad_json_media_size_route_and_method(self):
        cases = [(self.event(body="{"), 400), (self.event(headers={}), 400),
                 (self.event(body=" " * 65537), 413), (self.event(resource="/otra"), 404),
                 (self.event(httpMethod="DELETE"), 405), (self.event(queryStringParameters={"x": "1"}), 400)]
        for event, expected in cases:
            with self.subTest(expected=expected, event=event.get("httpMethod")):
                self.assertEqual(main(event, None, self.repo)["statusCode"], expected)

    def test_conflict_contains_current_cart(self):
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")]["version"] = 2
        response = main(self.event(), None, self.repo)
        self.assertEqual(response["statusCode"], 409)
        self.assertEqual(json.loads(response["body"])["carrito_actualizado"][0]["version"], 2)

    def test_cors_and_unexpected_error_do_not_leak_internal_details(self):
        with patch.dict("os.environ", {"FRONTEND_ORIGIN": "http://localhost:8080"}):
            self.repo.get = Mock(side_effect=RuntimeError("password secreto"))
            with self.assertLogs("facturacion.handler", level="ERROR"):
                result = main(self.event(), None, self.repo)
        self.assertEqual(result["statusCode"], 503)
        self.assertNotIn("secreto", result["body"])
        self.assertEqual(result["headers"]["Access-Control-Allow-Origin"], "http://localhost:8080")
