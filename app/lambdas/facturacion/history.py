"""Consultas de resumen por indice, rangos UTC y cursores ligados a filtros."""
import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import re

from catalogo.model import ApiError, client_id
from catalogo.pagination import page_limit
from .model import BOGOTA, box_id, uuid_value

SUMMARY_FIELDS = ("factura_id", "fecha_utc", "caja_id", "cliente_id", "total_centavos")


def utc_text(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ApiError(400, "La fecha debe tener formato AAAA-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "Fecha de calendario no valida") from None


def boundary(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return datetime.combine(local_date(value), time.min, tzinfo=BOGOTA).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise ApiError(400, "Fecha fuera del rango admitido") from None
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,3})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value):
        raise ApiError(400, "Usa una fecha AAAA-MM-DD o un instante ISO con zona y hasta tres decimales")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ApiError(400, "Instante o zona horaria no validos") from None


@dataclass(frozen=True)
class HistorySpec:
    kind: str
    index: str
    partition: str
    start: str
    end: str

    @property
    def lower(self):
        return f"FACTURA#{self.start}#"

    @property
    def upper(self):
        # BETWEEN es inclusivo. El prefijo sin #UUID es menor que cualquier
        # factura exactamente en end, por lo que el fin queda excluido.
        return f"FACTURA#{self.end}"

    @property
    def scope(self):
        value = {"kind": self.kind, "index": self.index, "partition": self.partition,
                 "start": self.start, "end": self.end, "order": "desc"}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def query_spec(kind, identifier, query):
    if not isinstance(query, dict):
        raise ApiError(400, "Parametros de consulta no validos")
    if kind == "dia":
        allowed = {"fecha", "limit", "cursor"}
        if set(query) - allowed or "fecha" not in query:
            raise ApiError(400, "El historial diario requiere fecha y solo admite limit y cursor adicionales")
        day = local_date(query["fecha"])
        try:
            start = datetime.combine(day, time.min, tzinfo=BOGOTA).astimezone(timezone.utc)
            end = start + timedelta(days=1)
        except (ValueError, OverflowError):
            raise ApiError(400, "Dia fuera del rango admitido") from None
        return HistorySpec(kind, "GSI3", f"VENTAS#DIA#{day.isoformat()}", utc_text(start), utc_text(end))
    if kind not in {"cliente", "caja"}:
        raise ApiError(400, "Tipo de historial no valido")
    if set(query) - {"desde", "hasta", "limit", "cursor"} or not {"desde", "hasta"}.issubset(query):
        raise ApiError(400, "El historial requiere desde y hasta; solo admite limit y cursor adicionales")
    start, end = boundary(query["desde"]), boundary(query["hasta"])
    if not start < end or end - start > timedelta(days=31):
        raise ApiError(400, "El rango debe ser mayor que cero y de hasta 31 dias; hasta es exclusivo")
    index, partition = (("GSI1", f"CLIENTE#{client_id(identifier)}") if kind == "cliente"
                        else ("GSI2", f"CAJA#{box_id(identifier)}"))
    return HistorySpec(kind, index, partition, utc_text(start), utc_text(end))


def validate_key(key, spec):
    names = {"PK", "SK", f"{spec.index}PK", f"{spec.index}SK"}
    if not isinstance(key, dict) or set(key) != names or not all(isinstance(v, str) for v in key.values()):
        raise ValueError("Estructura de clave no valida")
    if key["SK"] != "DOCUMENTO" or key[f"{spec.index}PK"] != spec.partition:
        raise ValueError("Particion distinta")
    identifier = uuid_value(key["PK"].removeprefix("FACTURA#"), "factura_id")
    if key["PK"] != f"FACTURA#{identifier}":
        raise ValueError("PK no canonica")
    sk = key[f"{spec.index}SK"]
    stamp = sk.removeprefix("FACTURA#").split("#", 1)[0]
    parsed = boundary(stamp)
    if stamp != utc_text(parsed) or sk != f"FACTURA#{stamp}#{identifier}" or not spec.lower <= sk <= spec.upper:
        raise ValueError("Clave fuera del intervalo")
    return key


def encode_history_cursor(key, spec):
    if not key:
        return None
    try:
        validate_key(key, spec)
    except (ValueError, ApiError):
        raise ApiError(503, "El indice devolvio una clave de continuacion inesperada") from None
    raw = json.dumps({"v": 1, "scope": spec.scope, "key": key}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_history_cursor(token, spec):
    if token is None:
        return None
    try:
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,4096}", token):
            raise ValueError()
        payload = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"v", "scope", "key"}:
            raise ValueError()
        if type(payload["v"]) is not int or payload["v"] != 1 or payload["scope"] != spec.scope:
            raise ValueError()
        return validate_key(payload["key"], spec)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, binascii.Error, RecursionError, ApiError):
        raise ApiError(400, "Cursor no valido para este historial y sus filtros") from None


def summary(item):
    try:
        result = {name: item[name] for name in SUMMARY_FIELDS}
        identifier = uuid_value(result["factura_id"], "factura_id")
        if identifier != result["factura_id"]:
            raise ValueError()
        stamp = boundary(result["fecha_utc"])
        if utc_text(stamp) != result["fecha_utc"] or type(result["total_centavos"]) is not int or not 0 <= result["total_centavos"] <= 2**53 - 1:
            raise ValueError()
        client_id(result["cliente_id"])
        box_id(result["caja_id"])
        return {**result, "referencia": f"DEMO-{identifier}", "moneda": "COP",
                "fecha_local": stamp.astimezone(BOGOTA).date().isoformat()}
    except (KeyError, ValueError, TypeError, OverflowError, ApiError):
        raise ApiError(503, "El indice devolvio un resumen de factura no valido") from None


class HistoryService:
    def __init__(self, repository):
        self.repository = repository

    def listing(self, spec, limit, cursor):
        items, next_key = self.repository.history_query(spec, limit, cursor)
        return {"items": [summary(item) for item in items],
                "next_cursor": encode_history_cursor(next_key, spec)}


def history_parameters(kind, identifier, query):
    spec = query_spec(kind, identifier, query)
    return spec, page_limit(query.get("limit")), decode_history_cursor(query.get("cursor"), spec)
