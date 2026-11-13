"""Carga datos ficticios sin sobrescribir registros existentes."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))
from catalogo.model import ApiError, general_client, new_client, new_product, now_utc
from catalogo.repository import DynamoRepository


def seed(repository=None):
    repository = repository if repository is not None else DynamoRepository()
    items = [
        new_product({"nombre": "Cuaderno de demostracion", "precio_unitario_centavos": 500000,
                     "impuesto_bps": 1000}, "00000000-0000-4000-8000-000000000001"),
        new_product({"nombre": "Lapicero de demostracion", "precio_unitario_centavos": 150000,
                     "impuesto_bps": 1000}, "00000000-0000-4000-8000-000000000002"),
        new_product({"nombre": "Carpeta de demostracion", "precio_unitario_centavos": 300000,
                     "impuesto_bps": 0}, "00000000-0000-4000-8000-000000000003"),
        new_client({"nombre": "Cliente Demo Uno", "tipo_documento": "CC", "numero_documento": "90000001"}),
        new_client({"nombre": "Cliente Demo Dos", "tipo_documento": "CC", "numero_documento": "90000002"}),
        general_client(),
    ]
    for number in (1, 2):
        identifier = f"c{number:02d}"
        items.append({"PK": "CONFIG#CAJAS", "SK": f"CAJA#{identifier}", "tipo_entidad": "CAJA",
                      "schema_version": 1, "caja_id": identifier, "nombre": f"Caja {number}",
                      "activo": True, "version": 1, "creado_en": now_utc()})
    created = existing = 0
    for item in items:
        try:
            repository.put(item)
            created += 1
        except ApiError as exc:
            if exc.status != 409:
                raise
            existing += 1
    return {"creados": created, "existentes_conservados": existing,
            "nota": "Datos ficticios; las tasas de demostracion no son reglas fiscales reales"}


if __name__ == "__main__":
    try:
        print(json.dumps(seed(), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"No fue posible cargar la demostracion: {exc}", file=sys.stderr)
        sys.exit(1)
