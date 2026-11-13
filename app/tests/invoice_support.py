"""Datos ficticios y almacen atomico para probar concurrencia sin AWS."""
import copy
import threading
import uuid

from catalog_support import MemoryRepository
from catalogo.model import general_client, new_client, new_product
from facturacion.repository import CommitConflict

P1 = "00000000-0000-4000-8000-000000000001"
P2 = "00000000-0000-4000-8000-000000000002"


def sale(**changes):
    return {"solicitud_id": str(uuid.uuid4()), "caja_id": "c01",
            "operador_declarado": "Cajero demo", "cliente_id": "CC#00001",
            "lineas": [{"producto_id": P1, "cantidad": 2, "version_esperada": 1},
                       {"producto_id": P2, "cantidad": 1, "version_esperada": 1}], **changes}


def initial_items():
    return [new_product({"nombre": "Cafe demo", "precio_unitario_centavos": 10001, "impuesto_bps": 5000}, P1),
            new_product({"nombre": "Pan demo", "precio_unitario_centavos": 1250, "impuesto_bps": 0}, P2),
            new_client({"nombre": "Cliente demo", "tipo_documento": "CC", "numero_documento": "00001"}),
            general_client(),
            *[{"PK": "CONFIG#CAJAS", "SK": f"CAJA#{box}", "caja_id": box,
               "tipo_entidad": "CAJA", "activo": True, "version": 1} for box in ("c01", "c02")]]


class InvoiceMemoryRepository(MemoryRepository):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.before_commit = None
        self.commit_calls = 0
        self.tokens = []
        self.failures = []
        self.read_calls = []
        for item in initial_items():
            self.items[(item["PK"], item["SK"])] = copy.deepcopy(item)

    def get(self, pk, sk):
        with self.lock:
            self.read_calls.append((pk, sk))
            return super().get(pk, sk)

    def commit(self, document, receipt, products, customer, box, token):
        with self.lock:
            self.commit_calls += 1
            self.tokens.append(token)
            if self.before_commit:
                callback, self.before_commit = self.before_commit, None
                callback()
            if self.failures:
                raise self.failures.pop(0)
            for item in (document, receipt):
                if (item["PK"], item["SK"]) in self.items:
                    raise CommitConflict("conditional")
            references = list(products.values()) + [customer, box]
            for item in references:
                current = self.items.get((item["PK"], item["SK"]))
                if current is None or current.get("version") != item.get("version"):
                    raise CommitConflict("conditional")
                if item in list(products.values()) + [box] and current.get("activo") is not True:
                    raise CommitConflict("conditional")
            for item in (document, receipt):
                self.items[(item["PK"], item["SK"])] = copy.deepcopy(item)

    def invoices(self):
        with self.lock:
            return [copy.deepcopy(item) for item in self.items.values() if item.get("tipo_entidad") == "FACTURA"]

    def receipts(self):
        with self.lock:
            return [copy.deepcopy(item) for item in self.items.values() if item.get("tipo_entidad") == "SOLICITUD"]
