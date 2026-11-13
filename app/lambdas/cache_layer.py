"""Cache-Aside acotada: Redis es opcional y DynamoDB conserva la autoridad."""
import json
import logging
import os
import re
import uuid
from datetime import date, datetime

from catalogo.model import json_numbers

logger = logging.getLogger(__name__)
PRODUCT_TTL = 60
INVOICE_TTL = 300
TTL = {"producto": PRODUCT_TTL, "factura": INVOICE_TTL}
MAX_CACHE_BYTES = 400 * 1024


def reject_constant(value):
    raise ValueError("Constante JSON no admitida")


def cache_key(kind, identifier):
    if kind not in TTL:
        raise ValueError("Tipo de cache no admitido")
    return f"facturacion:v1:{kind}:{identifier}"


def whole(value, low=0, high=2**53 - 1):
    return type(value) is int and low <= value <= high


def valid_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def named(value):
    return isinstance(value, str) and 1 <= len(value) <= 120 and not any(ord(c) < 32 for c in value)


def valid_timestamp(value):
    if not isinstance(value, str) or len(value) != 24:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
        return True
    except ValueError:
        return False


def valid_document(kind, identifier, value):
    """Rechaza JSON incompleto, de otro ID/esquema o con numeros incoherentes."""
    if not isinstance(value, dict) or any(k in {"PK", "SK"} or k.startswith("GSI") for k in value):
        return False
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        return False
    if kind == "producto":
        return (value.get("tipo_entidad") == "PRODUCTO" and value.get("producto_id") == identifier
                and valid_uuid(identifier) and named(value.get("nombre"))
                and type(value.get("activo")) is bool and whole(value.get("version"), 1, 2**31)
                and whole(value.get("precio_unitario_centavos"), 0, 1_000_000_000)
                and whole(value.get("impuesto_bps"), 0, 10000)
                and valid_timestamp(value.get("creado_en")) and valid_timestamp(value.get("actualizado_en")))
    if kind != "factura" or value.get("tipo_entidad") != "FACTURA" or value.get("factura_id") != identifier:
        return False
    if not valid_uuid(identifier) or value.get("moneda") != "COP" or value.get("alcance") != "PROTOTIPO_ACADEMICO":
        return False
    if value.get("referencia") != f"DEMO-{identifier}" or not valid_uuid(value.get("solicitud_id")):
        return False
    if not named(value.get("operador_declarado")) or not isinstance(value.get("caja_id"), str):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value["caja_id"]):
        return False
    if not valid_timestamp(value.get("fecha_utc")) or value.get("creado_en") != value["fecha_utc"]:
        return False
    try:
        from catalogo.model import client_id
        client_id(value["cliente_id"])
        if len(value["fecha_local"]) != 10:
            return False
        date.fromisoformat(value["fecha_local"])
    except Exception:
        # ApiError de identificacion tambien significa una entrada de cache invalida.
        return False
    customer = value.get("cliente")
    if (not isinstance(customer, dict) or not named(customer.get("nombre"))
            or not whole(customer.get("version"), 1, 2**31)
            or not isinstance(customer.get("tipo_documento"), str)
            or not isinstance(customer.get("numero_documento"), str)):
        return False
    expected_client = ("GENERAL" if customer["tipo_documento"] == "GENERAL" and customer["numero_documento"] == ""
                       else f"{customer['tipo_documento']}#{customer['numero_documento']}")
    if expected_client != value["cliente_id"]:
        return False
    lines = value.get("lineas")
    if not isinstance(lines, list) or not 1 <= len(lines) <= 50:
        return False
    seen = set()
    for line in lines:
        if not isinstance(line, dict) or not valid_uuid(line.get("producto_id")) or not named(line.get("nombre")):
            return False
        if line["producto_id"] in seen:
            return False
        seen.add(line["producto_id"])
        if not (whole(line.get("cantidad"), 1, 9999) and whole(line.get("version"), 1, 2**31)
                and whole(line.get("precio_unitario_centavos"), 0, 1_000_000_000)
                and whole(line.get("impuesto_bps"), 0, 10000)):
            return False
        base = line["precio_unitario_centavos"] * line["cantidad"]
        tax = (base * line["impuesto_bps"] + 5000) // 10000
        if not all(whole(line.get(k)) for k in ("base_centavos", "impuesto_centavos", "total_centavos")):
            return False
        if (line["base_centavos"], line["impuesto_centavos"], line["total_centavos"]) != (base, tax, base + tax):
            return False
    if not all(whole(value.get(k)) for k in ("subtotal_centavos", "impuestos_centavos", "total_centavos")):
        return False
    return (value["subtotal_centavos"] == sum(line["base_centavos"] for line in lines)
            and value["impuestos_centavos"] == sum(line["impuesto_centavos"] for line in lines)
            and value["total_centavos"] == value["subtotal_centavos"] + value["impuestos_centavos"])


def redis_client():
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    # Sin reintentos implicitos de redis-py. Como maximo 200 ms por socket.
    timeout = float(os.environ.get("REDIS_TIMEOUT_SECONDS", "0.2"))
    if not 0 < timeout <= 0.2:
        timeout = 0.2
    return redis.Redis(host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", "6379")), decode_responses=True,
        socket_connect_timeout=timeout, socket_timeout=timeout, retry=Retry(NoBackoff(), 0))


class JsonCache:
    def __init__(self, client=None, *, failed=False):
        self.client = client
        self.failed = failed
        self.last_status = "error" if failed else ("bypass" if client is None else "miss")

    @classmethod
    def from_environment(cls):
        try:
            return cls(redis_client())
        except Exception:
            logger.warning("No se pudo inicializar Redis; se usara DynamoDB")
            return cls(failed=True)

    def ready(self):
        if self.failed:
            self.last_status = "error"
            return False
        return self.client is not None

    def failure(self, operation):
        self.failed = True
        self.last_status = "error"
        logger.warning("Redis no disponible en %s; se continua con DynamoDB", operation)

    def read(self, kind, identifier):
        if not self.ready():
            return None
        key = cache_key(kind, identifier)
        try:
            raw = self.client.get(key)
            if raw is None:
                self.last_status = "miss"
                return None
            ttl = self.client.ttl(key)
        except Exception:
            self.failure("lectura")
            return None
        try:
            if ttl <= 0 or ttl > TTL[kind] or not isinstance(raw, (str, bytes)):
                raise ValueError("Entrada sin expiracion valida")
            if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > MAX_CACHE_BYTES:
                raise ValueError("Entrada demasiado grande")
            value = json.loads(raw, parse_constant=reject_constant)
            if not valid_document(kind, identifier, value):
                raise ValueError("Documento de cache invalido")
        except Exception:
            self.last_status = "invalid"
            logger.warning("Entrada Redis invalida; se consultara DynamoDB")
            self.invalidate(kind, identifier)
            return None
        self.last_status = "hit"
        return value

    def write(self, kind, identifier, value):
        if not self.ready():
            return
        try:
            value = json_numbers(value)
            if not valid_document(kind, identifier, value):
                return
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(raw.encode("utf-8")) > MAX_CACHE_BYTES:
                return
            self.client.set(cache_key(kind, identifier), raw, ex=TTL[kind])
        except Exception:
            self.failure("escritura")

    def invalidate(self, kind, identifier):
        if not self.ready():
            return
        try:
            self.client.delete(cache_key(kind, identifier))
        except Exception:
            self.failure("invalidacion")

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                logger.warning("No se pudo cerrar el cliente de cache")


class CachedReads:
    def __init__(self, cache=None):
        self.cache = cache if cache is not None else JsonCache()
        self.source = "dynamodb"
        self.status = "bypass"

    def load(self, kind, identifier, loader):
        cached = self.cache.read(kind, identifier)
        if cached is not None:
            self.source, self.status = "redis", "hit"
            return cached
        self.source = "dynamodb"
        value = loader()  # Los fallos de DynamoDB y el 404 se propagan sin cachearlos.
        self.cache.write(kind, identifier, value)
        self.status = self.cache.last_status
        return value
