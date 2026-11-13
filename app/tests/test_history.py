"""Rangos, GSI, empates, paginacion y validacion antes de consultar."""
import base64
import copy
import json
import unittest
from unittest.mock import Mock, patch

from history_support import HistoryMemoryRepository, add_invoice
from catalogo.model import ApiError
from facturacion.handler import main
from facturacion.history import (HistoryService, boundary, decode_history_cursor, encode_history_cursor,
                                 history_parameters, query_spec)

RANGE = {"desde": "2026-01-15", "hasta": "2026-01-16"}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = HistoryMemoryRepository()
        self.service = HistoryService(self.repo)

    def listing(self, kind="cliente", identifier="CC#00001", query=None):
        return self.service.listing(*history_parameters(kind, identifier, query or RANGE))

    def assert_error(self, code, callback, *args):
        with self.assertRaises(ApiError) as error:
            callback(*args)
        self.assertEqual(error.exception.status, code)

    def test_dates_are_local_midnights_normalized_to_utc(self):
        spec = query_spec("cliente", "CC#00001", RANGE)
        self.assertEqual(spec.start, "2026-01-15T05:00:00.000Z")
        self.assertEqual(spec.end, "2026-01-16T05:00:00.000Z")
        self.assertEqual(spec.index, "GSI1")
        self.assertEqual(spec.partition, "CLIENTE#CC#00001")

    def test_equivalent_instants_have_the_same_cursor_scope(self):
        a = query_spec("caja", "c01", RANGE)
        b = query_spec("caja", "c01", {"desde": "2026-01-15T00:00:00-05:00", "hasta": "2026-01-16T05:00:00Z"})
        self.assertEqual(a, b)
        self.assertEqual(a.scope, b.scope)

    def test_start_included_end_excluded_at_millisecond_boundaries(self):
        documents = [add_invoice(self.repo, stamp) for stamp in [
            "2026-01-15T04:59:59.999Z", "2026-01-15T05:00:00.000Z",
            "2026-01-16T04:59:59.999Z", "2026-01-16T05:00:00.000Z"]]
        result = self.listing()
        self.assertEqual([item["factura_id"] for item in result["items"]],
                         [documents[2]["factura_id"], documents[1]["factura_id"]])

    def test_daily_partition_uses_bogota_date_and_gsi3(self):
        before = add_invoice(self.repo, "2026-01-15T04:59:59.999Z")
        included = add_invoice(self.repo, "2026-01-15T05:00:00.000Z")
        result = self.listing("dia", "", {"fecha": "2026-01-15"})
        self.assertEqual([item["factura_id"] for item in result["items"]], [included["factura_id"]])
        self.assertEqual(result["items"][0]["fecha_local"], "2026-01-15")
        spec = self.repo.history_queries[0][0]
        self.assertEqual((spec.index, spec.partition), ("GSI3", "VENTAS#DIA#2026-01-15"))

    def test_client_and_box_histories_do_not_mix_entities(self):
        a = add_invoice(self.repo, "2026-01-15T12:00:00.000Z", box="c01")
        b = add_invoice(self.repo, "2026-01-15T13:00:00.000Z", box="c02")
        c = add_invoice(self.repo, "2026-01-15T14:00:00.000Z", client="GENERAL")
        self.assertEqual({item["factura_id"] for item in self.listing()["items"]}, {a["factura_id"], b["factura_id"]})
        boxes = self.listing("caja", "c01")
        self.assertEqual({item["factura_id"] for item in boxes["items"]}, {a["factura_id"], c["factura_id"]})
        self.assertEqual(self.repo.history_queries[-1][0].index, "GSI2")

    def test_more_than_25_tied_instants_paginate_without_duplicates(self):
        documents = [add_invoice(self.repo, "2026-01-15T12:00:00.000Z") for _ in range(53)]
        expected = sorted((item["factura_id"] for item in documents), reverse=True)
        actual, cursor, pages = [], None, 0
        while True:
            query = {**RANGE, "limit": "25"}
            if cursor:
                query["cursor"] = cursor
            result = self.listing(query=query)
            actual.extend(item["factura_id"] for item in result["items"])
            pages += 1
            cursor = result["next_cursor"]
            if not cursor:
                break
        self.assertEqual(actual, expected)
        self.assertEqual(len(set(actual)), 53)
        self.assertEqual(pages, 3)

    def test_limit_can_change_while_filters_remain_identical(self):
        for _ in range(5):
            add_invoice(self.repo, "2026-01-15T12:00:00.000Z")
        first = self.listing(query={**RANGE, "limit": "1"})
        second = self.listing(query={**RANGE, "limit": "4", "cursor": first["next_cursor"]})
        self.assertEqual(len(second["items"]), 4)
        self.assertNotIn(first["items"][0]["factura_id"], {item["factura_id"] for item in second["items"]})

    def test_summary_has_no_document_or_technical_keys(self):
        add_invoice(self.repo, "2026-01-15T12:00:00.000Z")
        item = self.listing()["items"][0]
        self.assertEqual(set(item), {"factura_id", "fecha_utc", "fecha_local", "referencia",
                                    "moneda", "total_centavos", "caja_id", "cliente_id"})
        self.assertEqual(item["cliente_id"], "CC#00001")

    def test_deleted_master_does_not_prevent_historical_query(self):
        add_invoice(self.repo, "2026-01-15T12:00:00.000Z")
        del self.repo.items[("CLIENTE#CC#00001", "PERFIL")]
        self.repo.read_calls.clear()
        self.assertEqual(len(self.listing()["items"]), 1)
        self.assertEqual(self.repo.read_calls, [])

    def test_valid_unknown_customer_returns_empty_result(self):
        self.assertEqual(self.listing(identifier="CC#99999"), {"items": [], "next_cursor": None})

    def test_exact_31_day_interval_is_allowed(self):
        spec = query_spec("caja", "c01", {"desde": "2026-01-01", "hasta": "2026-02-01"})
        self.assertEqual(spec.end, "2026-02-01T05:00:00.000Z")

    def test_reversed_empty_and_excessive_ranges_rejected(self):
        for query in [{"desde": "2026-01-16", "hasta": "2026-01-15"},
                      {"desde": "2026-01-15", "hasta": "2026-01-15"},
                      {"desde": "2026-01-01", "hasta": "2026-02-02"}]:
            with self.subTest(query=query):
                self.assert_error(400, query_spec, "cliente", "GENERAL", query)

    def test_invalid_calendar_and_imprecise_instants_rejected(self):
        for value in [None, "", "2026-02-29", "2026-13-01", "2026-01-15T00:00:00",
                      "2026-01-15T00:00:00.0001Z", "2026-01-15T24:00:00Z", "2026-01-15T00:00:00+25:00"]:
            with self.subTest(value=value):
                self.assert_error(400, boundary, value)

    def test_leap_day_and_fractional_seconds_are_supported(self):
        self.assertEqual(boundary("2024-02-29").hour, 5)
        self.assertEqual(boundary("2026-01-15T12:00:00.1Z").microsecond, 100000)

    def test_missing_and_foreign_query_parameters_are_rejected(self):
        for kind, identifier, query in [
            ("cliente", "GENERAL", {"desde": "2026-01-15"}), ("caja", "c01", {**RANGE, "fecha": "2026-01-15"}),
            ("dia", "", {}), ("dia", "", {"fecha": "2026-01-15", "desde": "2026-01-15"}),
            ("dia", "", {"fecha": "9999-12-31"})]:
            with self.subTest(kind=kind, query=query):
                self.assert_error(400, query_spec, kind, identifier, query)

    def test_limits_and_identifiers_rejected_before_query(self):
        for limit in ["0", "26", "1.5", "", True, 2]:
            with self.subTest(limit=limit):
                self.assert_error(400, history_parameters, "caja", "c01", {**RANGE, "limit": limit})
        self.assert_error(400, history_parameters, "cliente", "CC#", RANGE)
        self.assert_error(400, history_parameters, "caja", "c#01", RANGE)
        self.assertEqual(self.repo.history_queries, [])

    def cursor(self):
        for _ in range(3):
            add_invoice(self.repo, "2026-01-15T12:00:00.000Z")
        return self.listing(query={**RANGE, "limit": "1"})["next_cursor"]

    def test_cursor_is_bound_to_subject_range_and_index(self):
        token = self.cursor()
        for kind, identifier, query in [("cliente", "GENERAL", RANGE), ("caja", "c01", RANGE),
                ("dia", "", {"fecha": "2026-01-15"}),
                ("cliente", "CC#00001", {"desde": "2026-01-14", "hasta": "2026-01-16"})]:
            with self.subTest(kind=kind, identifier=identifier):
                self.assert_error(400, history_parameters, kind, identifier, {**query, "cursor": token})

    def test_cursor_accepts_equivalent_utc_filters(self):
        token = self.cursor()
        result = self.listing(query={"desde": "2026-01-15T05:00:00Z", "hasta": "2026-01-16T00:00:00-05:00", "cursor": token})
        self.assertEqual(len(result["items"]), 2)

    def test_malformed_or_catalog_cursor_is_rejected(self):
        from catalogo.pagination import encode_cursor
        spec = query_spec("cliente", "CC#00001", RANGE)
        for token in ["", "%", "a", "x" * 4097, True, encode_cursor({"PK": "PRODUCTO#x"}, "PRODUCTOS")]:
            with self.subTest(token_type=type(token).__name__):
                self.assert_error(400, decode_history_cursor, token, spec)

    def test_modified_cursor_key_is_checked_not_just_scope(self):
        token = self.cursor()
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        for changes in [{"GSI1PK": "CLIENTE#GENERAL"}, {"SK": "PERFIL"}, {"PK": "PRODUCTO#x"},
                        {"GSI1SK": "FACTURA#2026-01-16T05:00:00.000Z#" + payload["key"]["PK"].split("#")[1]}]:
            with self.subTest(changes=changes):
                other = {**payload, "key": {**payload["key"], **changes}}
                encoded = base64.urlsafe_b64encode(json.dumps(other).encode()).decode().rstrip("=")
                self.assert_error(400, decode_history_cursor, encoded, query_spec("cliente", "CC#00001", RANGE))

    def test_boolean_cursor_version_is_rejected(self):
        token = self.cursor()
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        payload["v"] = True
        token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        self.assert_error(400, decode_history_cursor, token, query_spec("cliente", "CC#00001", RANGE))

    def test_excessively_nested_json_cursor_is_a_400(self):
        token = base64.urlsafe_b64encode(("["*1100 + "0" + "]"*1100).encode()).decode().rstrip("=")
        self.assert_error(400, decode_history_cursor, token, query_spec("cliente", "CC#00001", RANGE))

    def test_empty_page_with_continuation_is_not_silently_finished(self):
        token = self.cursor()
        spec, limit, key = history_parameters("cliente", "CC#00001", {**RANGE, "cursor": token})
        self.repo.history_query = Mock(return_value=([], key))
        response = self.service.listing(spec, limit, None)
        self.assertEqual(response["items"], [])
        self.assertIsNotNone(response["next_cursor"])

    def test_invalid_index_summary_or_continuation_becomes_503(self):
        for response in [([{"factura_id": "x"}], None), ([], {"PK": "x"})]:
            with self.subTest(response=response):
                self.repo.history_query = Mock(return_value=response)
                self.assert_error(503, self.listing)


class HistoryHttpTests(unittest.TestCase):
    def setUp(self):
        self.repo = HistoryMemoryRepository()
        add_invoice(self.repo, "2026-01-15T12:00:00.000Z")

    def event(self, route="/clientes/{id}/facturas", identifier="CC%2300001", query=None, method="GET"):
        return {"resource": route, "httpMethod": method, "pathParameters": {"id": identifier},
                "queryStringParameters": query if query is not None else RANGE}

    def test_three_routes_use_queries_and_bypass_redis(self):
        with patch("facturacion.handler.JsonCache.from_environment", side_effect=AssertionError("No usar Redis")):
            for event in [self.event(), self.event("/cajas/{id}/facturas", "c01"),
                          self.event("/facturas", "", {"fecha": "2026-01-15"})]:
                with self.subTest(route=event["resource"]):
                    result = main(event, None, self.repo)
                    self.assertEqual(result["statusCode"], 200)
                    self.assertEqual(result["headers"]["X-Data-Source"], "dynamodb")
                    self.assertEqual(result["headers"]["X-Cache"], "bypass")
                    self.assertEqual(len(json.loads(result["body"])["items"]), 1)

    def test_bad_query_does_not_initialize_sdk(self):
        with patch("facturacion.handler.InvoiceRepository", side_effect=AssertionError("No consultar")) as factory:
            result = main(self.event(query={"desde": "bad", "hasta": "bad"}), None)
        self.assertEqual(result["statusCode"], 400)
        factory.assert_not_called()

    def test_history_does_not_accept_writes(self):
        self.assertEqual(main(self.event(method="POST"), None, self.repo)["statusCode"], 405)

    def test_database_error_is_sanitized(self):
        self.repo.history_query = Mock(side_effect=RuntimeError("password privado"))
        with self.assertLogs("facturacion.handler", level="ERROR"):
            response = main(self.event(), None, self.repo)
        self.assertEqual(response["statusCode"], 503)
        self.assertNotIn("privado", response["body"])
