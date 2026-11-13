"""Rutas HTTP de facturacion; el cliente no determina precios ni totales."""
import logging
from urllib.parse import unquote

from catalogo.handler import body_json, response
from catalogo.model import ApiError
from .repository import InvoiceRepository
from .service import InvoiceService
from .model import uuid_value
from cache_layer import CachedReads, JsonCache
from .history import HistoryService, history_parameters

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ROUTES = {"/facturas": {"POST", "GET"}, "/facturas/{id}": {"GET"},
          "/clientes/{id}/facturas": {"GET"}, "/cajas/{id}/facturas": {"GET"}}
HISTORY_ROUTES = {"/facturas": "dia", "/clientes/{id}/facturas": "cliente", "/cajas/{id}/facturas": "caja"}


def main(event, context, repository=None, cache=None):
    owned_cache = None
    try:
        route, method = event.get("resource", ""), event.get("httpMethod", "GET")
        if route not in ROUTES:
            raise ApiError(404, "Ruta no encontrada")
        if method not in ROUTES[route]:
            raise ApiError(405, "Metodo no admitido")
        if method == "GET" and route in HISTORY_ROUTES:
            identifier = unquote((event.get("pathParameters") or {}).get("id", ""))
            parameters = history_parameters(HISTORY_ROUTES[route], identifier, event.get("queryStringParameters") or {})
            history = HistoryService(repository if repository is not None else InvoiceRepository())
            return response(200, history.listing(*parameters))
        if event.get("queryStringParameters"):
            raise ApiError(400, "Esta ruta no admite parametros de consulta")
        data = body_json(event) if method == "POST" else None
        service = InvoiceService(repository if repository is not None else InvoiceRepository())
        if method == "POST":
            result = service.create(data)
            return response(200 if result["replayed"] else 201, result)
        identifier = unquote((event.get("pathParameters") or {}).get("id", ""))
        identifier = uuid_value(identifier, "factura_id")
        if cache is None and repository is None:
            owned_cache = JsonCache.from_environment()
            cache = owned_cache
        reads = CachedReads(cache)
        document = reads.load("factura", identifier, lambda: service.invoice(identifier))
        return response(200, document, reads.source, reads.status)
    except ApiError as exc:
        return response(exc.status, {"error": exc.message, **getattr(exc, "details", {})})
    except Exception:
        logger.exception("No fue posible atender la solicitud de facturacion")
        return response(503, {"error": "No se pudo confirmar la operacion; conserva la solicitud original para reintentar"})
    finally:
        if owned_cache is not None:
            owned_cache.close()
