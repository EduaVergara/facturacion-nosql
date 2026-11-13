"""Validacion de intenciones, calculos exactos y documentos historicos."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from catalogo.model import ApiError, client_id, fields, integer, product_id, text

MAX_SAFE_INTEGER = 2**53 - 1
MAX_DOCUMENT_BYTES = 350 * 1024  # Margen bajo el limite DynamoDB de 400 KiB.
# Esta version admite ventas actuales en Colombia (UTC-5, sin horario de verano).
BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")


class SaleError(ApiError):
    def __init__(self, status, message, **details):
        super().__init__(status, message)
        self.details = details


def uuid_value(value, label):
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ApiError(400, f"{label} debe ser UUID") from None


def box_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
        raise ApiError(400, "caja_id no valido")
    return value


def intention(data):
    required = {"solicitud_id", "caja_id", "operador_declarado", "cliente_id", "lineas"}
    fields(data, required, required)
    raw_lines = data["lineas"]
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 50:
        raise ApiError(400, "Incluye entre 1 y 50 productos distintos")
    lines = []
    seen = set()
    for line in raw_lines:
        allowed = {"producto_id", "cantidad", "version_esperada"}
        fields(line, allowed, allowed)
        identifier = product_id(line["producto_id"])
        if identifier in seen:
            raise ApiError(400, "Un producto no puede aparecer en varias lineas")
        seen.add(identifier)
        lines.append({"producto_id": identifier,
                      "cantidad": integer(line["cantidad"], "cantidad", 1, 9999),
                      "version_esperada": integer(line["version_esperada"], "version_esperada", 1, 2**31 - 1)})
    return {"solicitud_id": uuid_value(data["solicitud_id"], "solicitud_id"),
            "caja_id": box_id(data["caja_id"]),
            "operador_declarado": text(data["operador_declarado"], "operador_declarado"),
            "cliente_id": client_id(data["cliente_id"]),
            "lineas": sorted(lines, key=lambda line: line["producto_id"])}


def intention_hash(data):
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def invoice_document(data, products, customer, *, identifier=None, instant=None):
    identifier = uuid_value(identifier or str(uuid.uuid4()), "factura_id")
    instant = instant or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("La fecha del servidor debe tener zona horaria")
    stamp = instant.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    day = instant.astimezone(BOGOTA).date().isoformat()
    lines = []
    for requested in data["lineas"]:
        product = products[requested["producto_id"]]
        base = product["precio_unitario_centavos"] * requested["cantidad"]
        tax = int((Decimal(base) * Decimal(product["impuesto_bps"]) / Decimal(10000))
                  .quantize(Decimal(1), rounding=ROUND_HALF_UP))
        lines.append({"producto_id": requested["producto_id"], "nombre": product["nombre"],
                      "version": product["version"], "cantidad": requested["cantidad"],
                      "precio_unitario_centavos": product["precio_unitario_centavos"],
                      "impuesto_bps": product["impuesto_bps"], "base_centavos": base,
                      "impuesto_centavos": tax, "total_centavos": base + tax})
    subtotal = sum(line["base_centavos"] for line in lines)
    taxes = sum(line["impuesto_centavos"] for line in lines)
    if subtotal + taxes > MAX_SAFE_INTEGER:
        raise ApiError(400, "El total excede el rango monetario de la aplicacion")
    item = {"PK": f"FACTURA#{identifier}", "SK": "DOCUMENTO", "tipo_entidad": "FACTURA",
            "schema_version": 1, "factura_id": identifier, "referencia": f"DEMO-{identifier}",
            "fecha_utc": stamp, "fecha_local": day, "creado_en": stamp,
            "caja_id": data["caja_id"], "operador_declarado": data["operador_declarado"],
            "cliente_id": data["cliente_id"],
            "cliente": {field: customer[field] for field in ("nombre", "tipo_documento", "numero_documento", "version")},
            "moneda": "COP", "lineas": lines, "subtotal_centavos": subtotal,
            "impuestos_centavos": taxes, "total_centavos": subtotal + taxes,
            "solicitud_id": data["solicitud_id"], "alcance": "PROTOTIPO_ACADEMICO",
            "GSI1PK": f"CLIENTE#{data['cliente_id']}", "GSI1SK": f"FACTURA#{stamp}#{identifier}",
            "GSI2PK": f"CAJA#{data['caja_id']}", "GSI2SK": f"FACTURA#{stamp}#{identifier}",
            "GSI3PK": f"VENTAS#DIA#{day}", "GSI3SK": f"FACTURA#{stamp}#{identifier}"}
    if len(json.dumps(item, ensure_ascii=False).encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ApiError(413, "La factura supera el tamano admitido por la aplicacion")
    return item


def request_record(data, digest, document):
    return {"PK": f"SOLICITUD#{data['caja_id']}#{data['solicitud_id']}", "SK": "RESULTADO",
            "tipo_entidad": "SOLICITUD", "schema_version": 1, "caja_id": data["caja_id"],
            "solicitud_id": data["solicitud_id"], "intencion_sha256": digest,
            "factura_id": document["factura_id"], "creado_en": document["creado_en"]}
