"""API Gateway proxy para productos, clientes y cajas."""
import base64
import binascii
import json
import logging
import os
from urllib.parse import unquote

from .model import ApiError, json_numbers
from .repository import DynamoRepository
from .service import CatalogService
from cache_layer import JsonCache

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ROUTES = {
    "/productos": {"GET", "POST"}, "/productos/{id}": {"GET", "PUT"},
    "/clientes": {"GET", "POST"}, "/clientes/{id}": {"GET", "PUT"},
    "/cajas": {"GET"},
}


def response(status, body, source="dynamodb", cache_status="bypass"):
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store",
               "X-Data-Source": source, "X-Cache": cache_status}
    origin = os.environ.get("FRONTEND_ORIGIN")
    if origin:
        headers.update({"Access-Control-Allow-Origin": origin,
                        "Access-Control-Expose-Headers": "X-Data-Source, X-Cache", "Vary": "Origin"})
    return {"statusCode": status, "headers": headers,
            "body": json.dumps(json_numbers(body), ensure_ascii=False)}


def body_json(event):
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    content_type = headers.get("content-type", "")
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise ApiError(400, "Usa Content-Type: application/json")
    raw = event.get("body")
    if not isinstance(raw, str):
        raise ApiError(400, "El cuerpo debe contener JSON")
    if len(raw.encode("utf-8")) > 90_000:
        raise ApiError(413, "El cuerpo supera el limite de 64 KiB")
    try:
        encoded = base64.b64decode(raw, validate=True) if event.get("isBase64Encoded") else raw.encode("utf-8")
        if len(encoded) > 65_536:
            raise ApiError(413, "El cuerpo supera el limite de 64 KiB")
        data = json.loads(encoded.decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error):
        raise ApiError(400, "El cuerpo no es JSON valido") from None
    if not isinstance(data, dict):
        raise ApiError(400, "El cuerpo debe ser un objeto JSON")
    return data


def main(event, context, repository=None, cache=None):
    owned_cache = None
    try:
        route = event.get("resource", "")
        method = event.get("httpMethod", "GET")
        if route not in ROUTES:
            raise ApiError(404, "Ruta no encontrada")
        if method not in ROUTES[route]:
            raise ApiError(405, "Metodo no admitido en esta ruta")
        data = body_json(event) if method in {"POST", "PUT"} else None
        if cache is None and repository is None and route == "/productos/{id}" and method in {"GET", "PUT"}:
            owned_cache = JsonCache.from_environment()
            cache = owned_cache
        service = CatalogService(repository if repository is not None else DynamoRepository(), cache=cache)
        params = event.get("pathParameters") or {}
        identifier = unquote(params.get("id", ""))
        query = event.get("queryStringParameters") or {}
        if method == "POST":
            created = service.create_product(data) if route == "/productos" else service.create_client(data)
            return response(201, created)
        if method == "PUT":
            result = service.update_product(identifier, data) if route == "/productos/{id}" else service.update_client(identifier, data)
            return response(200, result)
        if route == "/productos/{id}":
            product = service.product(identifier)
            return response(200, product, service.reads.source, service.reads.status)
        if route == "/clientes/{id}":
            return response(200, service.client(identifier))
        scope = {"/productos": "PRODUCTOS", "/clientes": "CLIENTES", "/cajas": "CAJAS"}[route]
        return response(200, service.listing(scope, query))
    except ApiError as exc:
        return response(exc.status, {"error": exc.message})
    except Exception:
        logger.exception("No fue posible atender la solicitud del catalogo")
        return response(503, {"error": "El servicio no pudo completar la solicitud"})
    finally:
        if owned_cache is not None:
            owned_cache.close()
