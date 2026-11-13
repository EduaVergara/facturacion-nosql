"""Operaciones de catalogo sin acoplar reglas de negocio a HTTP."""
from .model import ApiError, client_id, new_client, new_product, product_id, public_item
from .model import updated_client, updated_product
from .pagination import decode_cursor, encode_cursor, page_limit
from cache_layer import CachedReads


class CatalogService:
    def __init__(self, repository, cache=None):
        self.repository = repository
        self.reads = CachedReads(cache)

    def product(self, identifier):
        identifier = product_id(identifier)
        def load():
            item = self.repository.get(f"PRODUCTO#{identifier}", "DATOS")
            if item is None:
                raise ApiError(404, "Producto no encontrado")
            return public_item(item)
        return self.reads.load("producto", identifier, load)

    def create_product(self, data):
        item = new_product(data)
        self.repository.put(item)
        return public_item(item)

    def update_product(self, identifier, data):
        identifier = product_id(identifier)
        current = self.repository.get(f"PRODUCTO#{identifier}", "DATOS")
        if current is None:
            raise ApiError(404, "Producto no encontrado")
        updated, expected = updated_product(current, data)
        self.repository.put(updated, expected_version=expected)
        self.reads.cache.invalidate("producto", identifier)
        return public_item(updated)

    def client(self, identifier):
        item = self.repository.get(f"CLIENTE#{client_id(identifier)}", "PERFIL")
        if item is None:
            raise ApiError(404, "Cliente no encontrado")
        return public_item(item)

    def create_client(self, data):
        item = new_client(data)
        self.repository.put(item)
        return public_item(item)

    def update_client(self, identifier, data):
        current = self.repository.get(f"CLIENTE#{client_id(identifier)}", "PERFIL")
        if current is None:
            raise ApiError(404, "Cliente no encontrado")
        updated, expected = updated_client(current, data)
        self.repository.put(updated, expected_version=expected)
        return public_item(updated)

    def listing(self, scope, query):
        if set(query) - {"limit", "cursor"}:
            raise ApiError(400, "Este listado solo admite limit y cursor")
        limit = page_limit(query.get("limit"))
        cursor = decode_cursor(query.get("cursor"), scope)
        items, next_key = self.repository.query(scope, limit, cursor)
        return {"items": [public_item(item) for item in items],
                "next_cursor": encode_cursor(next_key, scope)}
