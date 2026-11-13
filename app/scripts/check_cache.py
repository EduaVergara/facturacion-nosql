"""Cache HTTP real, invalidacion, expiracion y prueba de Redis detenido."""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from local_http import request_json
from local_outputs import load_outputs

CONTEXT_PATH = Path(__file__).resolve().parents[1] / "cache-demo-etapa4.json"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def key(kind, identifier):
    return f"facturacion:v1:{kind}:{identifier}"


class Check:
    def __init__(self):
        outputs = load_outputs()
        self.api_id = outputs["ApiId"]
        self.table_name = outputs["TableName"]
        self.base = f"{os.environ['AWS_ENDPOINT_URL'].rstrip('/')}/restapis/{self.api_id}/prod/_user_request_"

    def request(self, path, **kwargs):
        return request_json(self.base + path, **kwargs)

    def detail(self, path, source, status=None):
        _, data, headers = self.request(path)
        headers = {name.lower(): value for name, value in headers.items()}
        require(headers.get("x-data-source") == source, f"{path}: origen inesperado {headers}")
        if status is not None:
            require(headers.get("x-cache") == status, f"{path}: estado de cache inesperado {headers}")
        return data

    def redis(self):
        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry
        return redis.Redis(host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", "6379")), decode_responses=True,
            socket_connect_timeout=1, socket_timeout=1, retry=Retry(NoBackoff(), 0))

    def context(self):
        data = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
        require(data["api_id"] == self.api_id, "El contexto pertenece a otra API; ejecuta primero --mode online")
        return data

    @staticmethod
    def expire_demo(redis, cache_key):
        # Acortar SOLO esta clave ficticia evita esperar 60 o 300 segundos.
        require(redis.pexpire(cache_key, 100), "No existe la clave cuya expiracion se quiere comprobar")
        for _ in range(100):
            if not redis.exists(cache_key):
                return
            time.sleep(0.02)
        raise RuntimeError("La clave de demostracion no expiro")

    def online(self):
        cache = self.redis()
        try:
            require(cache.ping(), "Redis no esta disponible para la prueba inicial")
            _, product, _ = self.request("/productos", method="POST", expected=(201,), attempts=1,
                data={"nombre": "Producto ficticio cache " + str(uuid.uuid4())[:8],
                      "precio_unitario_centavos": 123450, "impuesto_bps": 1000})
            product_id = product["producto_id"]
            path = "/productos/" + product_id
            product_key = key("producto", product_id)
            first = self.detail(path, "dynamodb", "miss")
            require(self.detail(path, "redis", "hit") == first, "El hit cambio el documento de producto")
            product_ttl = cache.ttl(product_key)
            require(0 < product_ttl <= 60, "TTL de producto incorrecto")

            cache.set(product_key, "{", ex=60)
            require(self.detail(path, "dynamodb", "invalid") == first, "No se recupero el JSON invalido")
            _, updated, _ = self.request(path, method="PUT", attempts=1,
                data={"version_esperada": product["version"], "precio_unitario_centavos": 123451})
            require(cache.exists(product_key) == 0, "La actualizacion no invalido la cache del producto")
            require(self.detail(path, "dynamodb", "miss")["version"] == updated["version"], "Se devolvio version anterior")
            self.detail(path, "redis", "hit")
            self.expire_demo(cache, product_key)
            self.detail(path, "dynamodb", "miss")

            def sale_body(version):
                return {"solicitud_id": str(uuid.uuid4()), "caja_id": "c01",
                    "operador_declarado": "Prueba automatica cache", "cliente_id": "GENERAL",
                    "lineas": [{"producto_id": product_id, "cantidad": 2, "version_esperada": version}]}
            online_body = sale_body(updated["version"])
            _, sale, _ = self.request("/facturas", method="POST", data=online_body, expected=(200, 201))
            invoice = sale["factura"]
            invoice_path = "/facturas/" + invoice["factura_id"]
            invoice_key = key("factura", invoice["factura_id"])
            require(self.detail(invoice_path, "dynamodb", "miss") == invoice, "Factura leida diferente a la emitida")
            require(self.detail(invoice_path, "redis", "hit") == invoice, "Hit de factura alterado")
            invoice_ttl = cache.ttl(invoice_key)
            require(0 < invoice_ttl <= 300, "TTL de factura incorrecto")
            self.expire_demo(cache, invoice_key)
            self.detail(invoice_path, "dynamodb", "miss")

            # Cambiar el maestro ficticio no debe alterar el documento historico.
            _, latest, _ = self.request(path, method="PUT", attempts=1,
                data={"version_esperada": updated["version"], "precio_unitario_centavos": 123999})
            self.detail(path, "dynamodb", "miss")
            require(self.detail(invoice_path, "redis", "hit") == invoice, "La factura historica cambio")
            stale = sale_body(updated["version"])
            _, conflict, _ = self.request("/facturas", method="POST", data=stale, expected=(409,))
            require(conflict.get("codigo") == "CATALOGO_CAMBIO", "La venta acepto un precio desactualizado")
            context = {"api_id": self.api_id, "producto": latest, "factura": invoice,
                       "offline_request": sale_body(latest["version"])}
            CONTEXT_PATH.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"estado": "ok", "fase": "redis_disponible", "producto_miss_hit": "ok",
                "factura_miss_hit": "ok", "ttl_producto_segundos": product_ttl,
                "ttl_factura_segundos": invoice_ttl, "expiracion_ambos": "ok",
                "invalidacion_producto": "ok", "json_invalido_recuperado": "ok",
                "factura_historica_conservada": "ok", "precio_actual_verificado_al_vender": "ok",
                "producto_ficticio_creado": product_id, "factura_ficticia_creada": invoice["factura_id"]}
        finally:
            cache.close()

    def offline(self):
        data = self.context()
        _, health, _ = self.request("/health", expected=(503,), attempts=1)
        require(health.get("estado") == "degradado" and health["dynamodb"]["estado"] == "ok"
                and health["redis"]["estado"] == "error", "No se comprobo la caida de Redis con DynamoDB operativo")
        product = self.detail("/productos/" + data["producto"]["producto_id"], "dynamodb", "error")
        require(product == data["producto"], "Fallo la lectura alternativa de producto")
        invoice = self.detail("/facturas/" + data["factura"]["factura_id"], "dynamodb", "error")
        require(invoice == data["factura"], "Fallo la lectura alternativa de factura")
        _, created, headers = self.request("/facturas", method="POST", data=data["offline_request"], expected=(200, 201))
        require({k.lower(): v for k, v in headers.items()}.get("x-cache") == "bypass", "La venta no debe depender de Redis")
        _, replay, _ = self.request("/facturas", method="POST", data=data["offline_request"])
        require(replay["replayed"] is True and replay["factura"] == created["factura"], "El reenvio sin Redis no fue idempotente")
        import boto3
        table = boto3.resource("dynamodb").Table(self.table_name)
        receipt = table.get_item(Key={"PK": f"SOLICITUD#c01#{data['offline_request']['solicitud_id']}", "SK": "RESULTADO"}, ConsistentRead=True)["Item"]
        require(receipt["factura_id"] == created["factura"]["factura_id"], "No se persistio la solicitud sin Redis")
        return {"estado": "ok", "fase": "redis_detenido", "lectura_producto_desde_dynamodb": "ok",
                "lectura_factura_desde_dynamodb": "ok", "venta_guardada_sin_redis": "ok",
                "reenvio_sin_duplicados": "ok", "factura_ficticia_creada": created["factura"]["factura_id"]}

    def recovered(self):
        data = self.context()
        cache = self.redis()
        try:
            require(cache.ping(), "Redis no se recupero")
            for kind, identifier in [("producto", data["producto"]["producto_id"]), ("factura", data["factura"]["factura_id"])]:
                cache.delete(key(kind, identifier))
                path = f"/{'productos' if kind == 'producto' else 'facturas'}/{identifier}"
                self.detail(path, "dynamodb", "miss")
                self.detail(path, "redis", "hit")
            return {"estado": "ok", "fase": "redis_restaurado", "producto_y_factura_en_cache": "ok"}
        finally:
            cache.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("online", "offline", "recovered"), default="online")
    args = parser.parse_args()
    try:
        print(json.dumps(getattr(Check(), args.mode)(), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Comprobacion de cache incompleta ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
