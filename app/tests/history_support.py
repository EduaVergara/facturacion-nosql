"""Fixtures de fechas y proyecciones, sin servicios externos."""
import copy
from datetime import datetime, timezone
import uuid

from invoice_support import InvoiceMemoryRepository, sale
from facturacion.history import SUMMARY_FIELDS
from facturacion.model import intention, invoice_document
from facturacion.service import InvoiceService


class HistoryMemoryRepository(InvoiceMemoryRepository):
    def __init__(self):
        super().__init__()
        self.history_queries = []

    def history_query(self, spec, limit, cursor):
        self.history_queries.append((spec, limit, copy.deepcopy(cursor)))
        pk, sk = f"{spec.index}PK", f"{spec.index}SK"
        values = [item for item in self.items.values() if item.get(pk) == spec.partition
                  and spec.lower <= item[sk] <= spec.upper]
        if cursor:
            values = [item for item in values if item[sk] < cursor[sk]]
        values.sort(key=lambda item: item[sk], reverse=True)
        selected = values[:limit]
        next_key = ({key: selected[-1][key] for key in ("PK", "SK", pk, sk)} if len(values) > limit else None)
        return [{key: copy.deepcopy(item[key]) for key in SUMMARY_FIELDS} for item in selected], next_key


def add_invoice(repo, stamp, *, identifier=None, box="c01", client="CC#00001"):
    data = intention(sale(caja_id=box, cliente_id=client))
    products, customer, _ = InvoiceService(repo).snapshot(data)
    document = invoice_document(data, products, customer, identifier=identifier or str(uuid.uuid4()),
        instant=datetime.fromisoformat(stamp.replace("Z", "+00:00")))
    repo.put(document)
    return document
