"""Cursores de Query ligados al recurso y a su particion."""
import base64
import binascii
import json

from .model import ApiError


def page_limit(raw):
    if raw is None:
        return 25
    if not isinstance(raw, str) or not raw.isdecimal() or not 1 <= int(raw) <= 25:
        raise ApiError(400, "limit debe estar entre 1 y 25")
    return int(raw)


def encode_cursor(key, scope):
    if not key:
        return None
    value = json.dumps({"v": 1, "scope": scope, "key": key}, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode_cursor(token, scope):
    if token is None:
        return None
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise ValueError()
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if set(value) != {"v", "scope", "key"} or value["v"] != 1 or value["scope"] != scope:
            raise ValueError()
        key = value["key"]
        names = {"PK", "SK"} | ({"GSI1PK", "GSI1SK"} if scope != "CAJAS" else set())
        if not isinstance(key, dict) or set(key) != names:
            raise ValueError()
        if not all(isinstance(v, str) and 1 <= len(v.encode()) <= 2048 for v in key.values()):
            raise ValueError()
        partitions = {"PRODUCTOS": "CATALOGO#PRODUCTOS", "CLIENTES": "DIRECTORIO#CLIENTES"}
        if scope == "CAJAS":
            if key["PK"] != "CONFIG#CAJAS" or not key["SK"].startswith("CAJA#"):
                raise ValueError()
        elif key["GSI1PK"] != partitions[scope]:
            raise ValueError()
        return key
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, AttributeError):
        raise ApiError(400, "Cursor no valido para esta consulta") from None
