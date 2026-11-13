"""Repositorio en memoria para comprobar las reglas sin depender de AWS."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))
from catalogo.model import ApiError


class MemoryRepository:
    def __init__(self):
        self.items = {}
        self.query_calls = []
        self.before_put = None

    def get(self, pk, sk):
        return copy.deepcopy(self.items.get((pk, sk)))

    def put(self, item, expected_version=None):
        if self.before_put:
            callback, self.before_put = self.before_put, None
            callback()
        key = item["PK"], item["SK"]
        current = self.items.get(key)
        if expected_version is None and current is not None:
            raise ApiError(409, "Ya existe")
        if expected_version is not None and (current is None or current["version"] != expected_version):
            raise ApiError(409, "La version cambio")
        self.items[key] = copy.deepcopy(item)

    def query(self, scope, limit, cursor):
        self.query_calls.append((scope, limit, cursor))
        if scope == "CAJAS":
            values = [v for v in self.items.values() if v["PK"] == "CONFIG#CAJAS" and v["SK"].startswith("CAJA#")]
            key_name = "SK"
        else:
            partition = {"PRODUCTOS": "CATALOGO#PRODUCTOS", "CLIENTES": "DIRECTORIO#CLIENTES"}[scope]
            values = [v for v in self.items.values() if v.get("GSI1PK") == partition]
            key_name = "GSI1SK"
        values = sorted(values, key=lambda value: value[key_name])
        if cursor:
            values = [v for v in values if v[key_name] > cursor[key_name]]
        selected = copy.deepcopy(values[:limit])
        key_fields = {"PK", "SK"} if scope == "CAJAS" else {"PK", "SK", "GSI1PK", "GSI1SK"}
        next_key = {k: selected[-1][k] for k in key_fields} if len(values) > limit else None
        if scope != "CAJAS":
            # Imitar la proyeccion reducida, sin incluir producto_id por defecto.
            attributes = key_fields | {"tipo_entidad", "nombre", "activo", "version", "precio_unitario_centavos",
                                       "impuesto_bps", "factura_id", "fecha_utc", "caja_id", "cliente_id", "total_centavos"}
            selected = [{k: v for k, v in item.items() if k in attributes} for item in selected]
        return selected, next_key
