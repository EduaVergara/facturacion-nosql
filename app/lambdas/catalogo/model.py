"""Validacion y representacion de entidades, independiente de AWS."""
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import Decimal


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fields(data, allowed, required=()):
    if not isinstance(data, dict):
        raise ApiError(400, "El cuerpo debe ser un objeto JSON")
    if set(data) - set(allowed):
        raise ApiError(400, "Campos no admitidos: " + ", ".join(sorted(set(data) - set(allowed))))
    missing = set(required) - set(data)
    if missing:
        raise ApiError(400, "Faltan campos: " + ", ".join(sorted(missing)))


def text(value, label="nombre", maximum=120):
    if not isinstance(value, str):
        raise ApiError(400, f"{label} debe ser texto")
    value = value.strip()
    if not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        raise ApiError(400, f"{label} debe tener de 1 a {maximum} caracteres sin controles")
    return value


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ApiError(400, f"{label} debe ser un entero entre {low} y {high}")
    return value


def normalized_name(value):
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", plain).split()) or "sin nombre"


def product_id(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ApiError(400, "El identificador de producto debe ser UUID") from None


def client_id(value):
    if value == "GENERAL":
        return value
    if not isinstance(value, str) or not re.fullmatch(r"(CC|CE|NIT|PASAPORTE|OTRO)#[A-Z0-9-]{1,32}", value):
        raise ApiError(400, "Identificacion de cliente no valida")
    return value


def product_values(data):
    values = {}
    for name, value in data.items():
        if name == "nombre":
            values[name] = text(value)
        elif name == "precio_unitario_centavos":
            values[name] = integer(value, name, 0, 1_000_000_000)
        elif name == "impuesto_bps":
            values[name] = integer(value, name, 0, 10_000)
        elif name == "activo":
            if type(value) is not bool:
                raise ApiError(400, "activo debe ser true o false")
            values[name] = value
    return values


def new_product(data, identifier=None):
    allowed = {"nombre", "precio_unitario_centavos", "impuesto_bps", "activo"}
    fields(data, allowed, {"nombre", "precio_unitario_centavos", "impuesto_bps"})
    values = product_values(data)
    identifier = product_id(identifier or str(uuid.uuid4()))
    stamp = now_utc()
    return {
        "PK": f"PRODUCTO#{identifier}", "SK": "DATOS",
        "tipo_entidad": "PRODUCTO", "schema_version": 1,
        "producto_id": identifier, "activo": True, **values,
        "version": 1, "creado_en": stamp, "actualizado_en": stamp,
        "GSI1PK": "CATALOGO#PRODUCTOS",
        "GSI1SK": f"PRODUCTO#{normalized_name(values['nombre'])}#{identifier}",
    }


def updated_product(current, data):
    allowed = {"nombre", "precio_unitario_centavos", "impuesto_bps", "activo", "version_esperada"}
    fields(data, allowed, {"version_esperada"})
    version = integer(data["version_esperada"], "version_esperada", 1, 2**31 - 1)
    if len(data) == 1:
        raise ApiError(400, "Incluye al menos un campo para actualizar")
    if current["version"] != version:
        raise ApiError(409, "El producto cambio; consulta su version actual")
    updated = {**current, **product_values(data), "version": version + 1, "actualizado_en": now_utc()}
    updated["GSI1SK"] = f"PRODUCTO#{normalized_name(updated['nombre'])}#{current['producto_id']}"
    return updated, version


def new_client(data):
    fields(data, {"nombre", "tipo_documento", "numero_documento"},
           {"nombre", "tipo_documento", "numero_documento"})
    name = text(data["nombre"])
    kind = text(data["tipo_documento"], "tipo_documento", 12).upper()
    number = text(data["numero_documento"], "numero_documento", 32).upper()
    identifier = client_id(f"{kind}#{number}")
    stamp = now_utc()
    return {
        "PK": f"CLIENTE#{identifier}", "SK": "PERFIL",
        "tipo_entidad": "CLIENTE", "schema_version": 1,
        "cliente_id": identifier, "tipo_documento": kind, "numero_documento": number,
        "nombre": name, "version": 1, "creado_en": stamp, "actualizado_en": stamp,
        "GSI1PK": "DIRECTORIO#CLIENTES",
        "GSI1SK": f"CLIENTE#{normalized_name(name)}#{identifier}",
    }


def general_client():
    stamp = now_utc()
    return {
        "PK": "CLIENTE#GENERAL", "SK": "PERFIL", "tipo_entidad": "CLIENTE",
        "schema_version": 1, "cliente_id": "GENERAL", "nombre": "Cliente general de demostracion",
        "tipo_documento": "GENERAL", "numero_documento": "", "version": 1,
        "creado_en": stamp, "actualizado_en": stamp,
        "GSI1PK": "DIRECTORIO#CLIENTES",
        "GSI1SK": "CLIENTE#cliente general de demostracion#GENERAL",
    }


def updated_client(current, data):
    fields(data, {"nombre", "version_esperada"}, {"nombre", "version_esperada"})
    version = integer(data["version_esperada"], "version_esperada", 1, 2**31 - 1)
    if current["version"] != version:
        raise ApiError(409, "El cliente cambio; consulta su version actual")
    name = text(data["nombre"])
    return {**current, "nombre": name, "version": version + 1,
            "actualizado_en": now_utc(),
            "GSI1SK": f"CLIENTE#{normalized_name(name)}#{current['cliente_id']}"}, version


def public_item(item):
    data = {key: value for key, value in item.items() if key not in {"PK", "SK"} and not key.startswith("GSI")}
    if item.get("tipo_entidad") == "PRODUCTO":
        data.setdefault("producto_id", item["PK"].removeprefix("PRODUCTO#"))
    if item.get("tipo_entidad") == "CLIENTE":
        identifier = data.setdefault("cliente_id", item["PK"].removeprefix("CLIENTE#"))
        if identifier != "GENERAL":
            kind, number = identifier.split("#", 1)
            data.setdefault("tipo_documento", kind)
            data.setdefault("numero_documento", number)
    return data


def json_numbers(value):
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError("Se esperaba un numero entero en el modelo")
        return int(value)
    if isinstance(value, dict):
        return {k: json_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_numbers(v) for v in value]
    return value
