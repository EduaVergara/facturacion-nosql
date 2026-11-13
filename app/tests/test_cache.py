"""Aceptacion de cache: hit/miss, TTL, invalidacion y continuidad del negocio."""
import copy
import importlib.util
import json
import unittest
from unittest.mock import Mock, patch

from invoice_support import InvoiceMemoryRepository, P1, P2, sale
from cache_support import MemoryRedis
from cache_layer import CachedReads, INVOICE_TTL, PRODUCT_TTL, JsonCache, cache_key
from catalogo.handler import main as catalog_main
from catalogo.model import ApiError, public_item
from catalogo.service import CatalogService
from facturacion.handler import main as invoice_main
from facturacion.service import InvoiceService


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.repo = InvoiceMemoryRepository()
        self.redis = MemoryRedis()
        self.cache = JsonCache(self.redis)
        self.product = public_item(self.repo.get(f"PRODUCTO#{P1}", "DATOS"))
        self.key = cache_key("producto", P1)
        self.repo.get = Mock(wraps=self.repo.get)
        self.service = CatalogService(self.repo, self.cache)
        self.log = patch("cache_layer.logger.warning")
        self.log.start()
        self.addCleanup(self.log.stop)

    def fresh_service(self):
        return CatalogService(self.repo, JsonCache(self.redis))

    def test_first_product_read_uses_dynamo_second_redis(self):
        first = self.service.product(P1)
        self.assertEqual(self.service.reads.source, "dynamodb")
        self.assertEqual(self.service.reads.status, "miss")
        self.assertEqual(self.redis.ttl(self.key), 60)
        second = self.service.product(P1)
        self.assertEqual(first, second)
        self.assertEqual(self.service.reads.source, "redis")
        self.assertEqual(self.service.reads.status, "hit")
        self.assertEqual(self.repo.get.call_count, 1)

    def test_hits_do_not_extend_ttl(self):
        self.service.product(P1)
        self.redis.now = 20
        self.service.product(P1)
        self.assertEqual(self.redis.ttl(self.key), 40)

    def test_expired_entry_reloads_latest_dynamo_version(self):
        self.service.product(P1)
        self.repo.items[(f"PRODUCTO#{P1}", "DATOS")].update(version=2, precio_unitario_centavos=888)
        self.redis.now = 61
        value = self.service.product(P1)
        self.assertEqual(value["precio_unitario_centavos"], 888)
        self.assertEqual(self.service.reads.source, "dynamodb")
        self.assertEqual(self.redis.ttl(self.key), PRODUCT_TTL)

    def test_update_commits_dynamo_before_invalidating(self):
        self.service.product(P1)
        def before_write():
            self.assertIsNotNone(self.redis.get(self.key))
        self.repo.before_put = before_write
        result = self.service.update_product(P1, {"version_esperada": 1, "precio_unitario_centavos": 777})
        self.assertEqual(result["version"], 2)
        self.assertIsNone(self.redis.get(self.key))
        self.assertEqual(self.service.product(P1)["precio_unitario_centavos"], 777)
        self.assertEqual(self.service.reads.source, "dynamodb")
        self.service.product(P1)
        self.assertEqual(self.service.reads.source, "redis")

    def test_rejected_update_keeps_cache_entry(self):
        self.service.product(P1)
        cached = self.redis.get(self.key)
        with self.assertRaises(ApiError) as error:
            self.service.update_product(P1, {"version_esperada": 2, "precio_unitario_centavos": 777})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.redis.get(self.key), cached)

    def test_get_failure_falls_back_once_without_attempting_cache_set(self):
        self.redis.fail = {"get"}
        self.assertEqual(self.service.product(P1), self.product)
        self.assertEqual(self.service.reads.source, "dynamodb")
        self.assertEqual(self.service.reads.status, "error")
        self.assertEqual([operation for operation, _ in self.redis.calls], ["get"])

    def test_set_failure_does_not_fail_product_read(self):
        self.redis.fail = {"set"}
        self.assertEqual(self.service.product(P1), self.product)
        self.assertEqual(self.service.reads.status, "error")

    def test_ttl_failure_does_not_trust_cached_value(self):
        self.cache.write("producto", P1, self.product)
        self.redis.fail = {"ttl"}
        self.assertEqual(self.service.product(P1), self.product)
        self.assertEqual(self.service.reads.source, "dynamodb")
        self.assertEqual(self.service.reads.status, "error")

    def test_invalidation_failure_does_not_undo_dynamo_update(self):
        self.service.product(P1)
        self.redis.fail = {"delete"}
        updated = self.service.update_product(P1, {"version_esperada": 1, "precio_unitario_centavos": 999})
        self.assertEqual(updated["version"], 2)
        self.assertEqual(self.repo.items[(f"PRODUCTO#{P1}", "DATOS")]["precio_unitario_centavos"], 999)
        # Otra peticion puede ver el valor previo hasta su TTL; facturar verifica DynamoDB.
        self.assertEqual(self.fresh_service().product(P1)["version"], 1)
        with self.assertRaises(ApiError) as error:
            InvoiceService(self.repo).create(sale())
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.repo.invoices(), [])
        self.redis.now = 61
        self.assertEqual(self.fresh_service().product(P1)["version"], 2)

    def test_invalid_json_is_ignored_and_replaced(self):
        self.redis.set(self.key, "{", ex=60)
        self.assertEqual(self.service.product(P1), self.product)
        self.assertEqual(self.service.reads.source, "dynamodb")
        self.assertEqual(self.service.reads.status, "invalid")
        self.assertEqual(json.loads(self.redis.get(self.key)), self.product)

    def test_wrong_id_schema_type_and_numeric_fields_are_ignored(self):
        invalid = [{**self.product, "producto_id": P2}, {**self.product, "schema_version": True},
                   {**self.product, "version": "1"}, {**self.product, "activo": 1},
                   {**self.product, "precio_unitario_centavos": -1}, {**self.product, "PK": "private"},
                   {**self.product, "tipo_entidad": "CLIENTE"}, []]
        for data in invalid:
            with self.subTest(data=data):
                self.redis.set(self.key, json.dumps(data), ex=60)
                self.assertEqual(self.service.product(P1), self.product)
                self.assertEqual(self.service.reads.source, "dynamodb")

    def test_persistent_or_excessive_ttl_is_rejected(self):
        for ttl in [None, 9999, 0]:
            with self.subTest(ttl=ttl):
                self.redis.set(self.key, json.dumps(self.product), ex=ttl)
                self.service.product(P1)
                self.assertEqual(self.service.reads.source, "dynamodb")
                self.assertEqual(self.redis.ttl(self.key), PRODUCT_TTL)

    def test_nan_and_oversized_payloads_are_ignored(self):
        bad_constant = json.dumps(self.product)[:-1] + ',"extra":NaN}'
        for raw in [bad_constant, 'x' * (400 * 1024 + 1)]:
            with self.subTest(size=len(raw)):
                self.redis.set(self.key, raw, ex=60)
                self.assertEqual(self.service.product(P1), self.product)
                self.assertEqual(self.service.reads.source, "dynamodb")

    def test_not_found_is_not_negatively_cached(self):
        del self.repo.items[(f"PRODUCTO#{P1}", "DATOS")]
        with self.assertRaises(ApiError) as error:
            self.service.product(P1)
        self.assertEqual(error.exception.status, 404)
        self.assertIsNone(self.redis.get(self.key))
        self.assertFalse(any(op == "set" for op, _ in self.redis.calls))

    def test_dynamo_failure_on_miss_is_not_reported_as_success(self):
        self.repo.get.side_effect = ApiError(503, "Base no disponible")
        with self.assertRaises(ApiError) as error:
            self.service.product(P1)
        self.assertEqual(error.exception.status, 503)
        self.assertIsNone(self.redis.get(self.key))

    def test_valid_cache_hit_can_serve_during_dynamo_read_failure(self):
        self.service.product(P1)
        self.repo.get.side_effect = ApiError(503, "Base no disponible")
        self.assertEqual(self.service.product(P1), self.product)
        self.assertEqual(self.service.reads.source, "redis")

    def test_clients_and_listings_do_not_use_cache(self):
        self.service.client("GENERAL")
        self.service.listing("PRODUCTOS", {})
        self.service.listing("CLIENTES", {})
        self.service.listing("CAJAS", {})
        self.assertEqual(self.redis.calls, [])

    def test_failed_initialization_and_close_are_nonfatal(self):
        with patch("cache_layer.redis_client", side_effect=ValueError("config privada")):
            cache = JsonCache.from_environment()
        service = CatalogService(self.repo, cache)
        self.assertEqual(service.product(P1), self.product)
        self.assertEqual(service.reads.status, "error")
        self.redis.fail = {"close"}
        self.cache.close()

    def test_invoice_ttl_300_and_cache_does_not_modify_document(self):
        document = InvoiceService(self.repo).create(sale())["factura"]
        reads = CachedReads(self.cache)
        loader = Mock(return_value=document)
        self.assertEqual(reads.load("factura", document["factura_id"], loader), document)
        key = cache_key("factura", document["factura_id"])
        self.assertEqual(self.redis.ttl(key), INVOICE_TTL)
        self.assertEqual(reads.load("factura", document["factura_id"], loader), document)
        self.assertEqual(reads.source, "redis")
        self.assertEqual(loader.call_count, 1)
        self.redis.now = 301
        reads.load("factura", document["factura_id"], loader)
        self.assertEqual(reads.source, "dynamodb")
        self.assertEqual(loader.call_count, 2)

    def test_incoherent_invoice_cache_is_discarded(self):
        document = InvoiceService(self.repo).create(sale())["factura"]
        for changes in [{"total_centavos": 1}, {"cliente": {}}, {"lineas": []}, {"moneda": "USD"},
                        {"creado_en": None}, {"cliente_id": "GENERAL"}, {"fecha_utc": "hoy"}]:
            with self.subTest(changes=changes):
                key = cache_key("factura", document["factura_id"])
                self.redis.set(key, json.dumps({**document, **changes}), ex=300)
                reads = CachedReads(self.cache)
                self.assertEqual(reads.load("factura", document["factura_id"], lambda: document), document)
                self.assertEqual(reads.source, "dynamodb")


class CacheHttpTests(unittest.TestCase):
    def setUp(self):
        self.repo = InvoiceMemoryRepository()
        self.redis = MemoryRedis()
        self.cache = JsonCache(self.redis)

    def product_event(self, **changes):
        return {"resource": "/productos/{id}", "httpMethod": "GET", "pathParameters": {"id": P1}, **changes}

    def invoice_event(self, identifier):
        return {"resource": "/facturas/{id}", "httpMethod": "GET", "pathParameters": {"id": identifier}}

    def test_product_headers_report_origin_without_changing_body(self):
        first = catalog_main(self.product_event(), None, self.repo, self.cache)
        second = catalog_main(self.product_event(), None, self.repo, self.cache)
        self.assertEqual(first["body"], second["body"])
        self.assertEqual(first["headers"]["X-Data-Source"], "dynamodb")
        self.assertEqual(first["headers"]["X-Cache"], "miss")
        self.assertEqual(second["headers"]["X-Data-Source"], "redis")
        self.assertEqual(second["headers"]["X-Cache"], "hit")

    def test_invoice_headers_report_hit_and_immutable_body(self):
        doc = InvoiceService(self.repo).create(sale())["factura"]
        event = self.invoice_event(doc["factura_id"])
        first = invoice_main(event, None, self.repo, self.cache)
        second = invoice_main(event, None, self.repo, self.cache)
        self.assertEqual(json.loads(first["body"]), doc)
        self.assertEqual(first["body"], second["body"])
        self.assertEqual(second["headers"]["X-Data-Source"], "redis")

    def test_post_invoice_and_replay_never_contact_cache(self):
        event = {"resource": "/facturas", "httpMethod": "POST", "headers": {"Content-Type": "application/json"}, "body": json.dumps(sale())}
        with patch("facturacion.handler.JsonCache.from_environment", side_effect=AssertionError("No abrir Redis")):
            first = invoice_main(event, None, self.repo, self.cache)
            replay = invoice_main(event, None, self.repo, self.cache)
        self.assertEqual(first["statusCode"], 201)
        self.assertEqual(replay["statusCode"], 200)
        self.assertEqual(replay["headers"]["X-Cache"], "bypass")
        self.assertEqual(self.redis.calls, [])

    def test_poisoned_cached_price_cannot_determine_charge(self):
        old_product = public_item(self.repo.get(f"PRODUCTO#{P1}", "DATOS"))
        old_product["precio_unitario_centavos"] = 1
        self.cache.write("producto", P1, old_product)
        event = {"resource": "/facturas", "httpMethod": "POST", "headers": {"Content-Type": "application/json"}, "body": json.dumps(sale())}
        created = invoice_main(event, None, self.repo, self.cache)
        self.assertEqual(json.loads(created["body"])["factura"]["total_centavos"], 31253)
        self.assertEqual(self.redis.calls[-1][0], "set")

    def test_redis_failure_preserves_get_status_and_diagnostics(self):
        self.redis.fail = {"get"}
        with self.assertLogs("cache_layer", level="WARNING"):
            result = catalog_main(self.product_event(), None, self.repo, self.cache)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["headers"]["X-Cache"], "error")
        self.assertNotIn("privado", result["body"])

    def test_cors_exposes_both_diagnostic_headers(self):
        with patch.dict("os.environ", {"FRONTEND_ORIGIN": "http://localhost:8080"}):
            result = catalog_main(self.product_event(), None, self.repo, self.cache)
        self.assertEqual(result["headers"]["Access-Control-Expose-Headers"], "X-Data-Source, X-Cache")

    def test_owned_runtime_cache_is_closed_even_when_dynamo_fails(self):
        cache = Mock(wraps=self.cache)
        with patch("catalogo.handler.JsonCache.from_environment", return_value=cache), \
             patch("catalogo.handler.DynamoRepository", side_effect=RuntimeError("privado")), \
             self.assertLogs("catalogo.handler", level="ERROR"):
            result = catalog_main(self.product_event(), None)
        self.assertEqual(result["statusCode"], 503)
        cache.close.assert_called_once()


@unittest.skipUnless(importlib.util.find_spec("fakeredis") is not None, "Requiere fakeredis y redis en cdk-dev")
class FakeRedisTests(unittest.TestCase):
    def setUp(self):
        import fakeredis
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.addCleanup(self.redis.close)
        self.repo = InvoiceMemoryRepository()
        self.service = CatalogService(self.repo, JsonCache(self.redis))

    def test_real_redis_api_get_set_ex_and_invalidation(self):
        self.service.product(P1)
        key = cache_key("producto", P1)
        self.assertTrue(0 < self.redis.ttl(key) <= 60)
        self.service.product(P1)
        self.assertEqual(self.service.reads.source, "redis")
        self.service.update_product(P1, {"version_esperada": 1, "nombre": "Actualizado"})
        self.assertEqual(self.redis.exists(key), 0)
        self.assertEqual(self.service.product(P1)["nombre"], "Actualizado")

    def test_persistent_json_and_wrong_redis_type_fall_back(self):
        key = cache_key("producto", P1)
        self.redis.set(key, "{}")
        self.service.product(P1)
        self.assertTrue(0 < self.redis.ttl(key) <= 60)
        self.redis.delete(key)
        self.redis.hset(key, "field", "wrong type")
        with self.assertLogs("cache_layer", level="WARNING"):
            result = CatalogService(self.repo, JsonCache(self.redis)).product(P1)
        self.assertEqual(result["producto_id"], P1)

    def test_real_client_configuration_has_bounded_timeouts_and_zero_retry(self):
        from cache_layer import redis_client
        with patch.dict("os.environ", {"REDIS_TIMEOUT_SECONDS": "0.2", "REDIS_HOST": "redis", "REDIS_PORT": "6379"}):
            client = redis_client()
        self.addCleanup(client.close)
        options = client.connection_pool.connection_kwargs
        self.assertEqual(options["socket_timeout"], 0.2)
        self.assertEqual(options["socket_connect_timeout"], 0.2)
        self.assertEqual(options["retry"].get_retries(), 0)
