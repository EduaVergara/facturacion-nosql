"""Verifica las rutas desplegadas sin modificar datos del comercio."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from local_outputs import load_outputs
from local_http import request_json


def verify():
    outputs = load_outputs()
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://emulador:4566").rstrip("/")
    base = f"{endpoint}/restapis/{outputs['ApiId']}/prod/_user_request_"

    def request(path):
        return request_json(base + path)[1]

    product = request("/productos/00000000-0000-4000-8000-000000000001")
    client = request("/clientes/" + urllib.parse.quote("CC#90000001", safe=""))
    boxes = request("/cajas")
    if product.get("version", 0) < 1 or client.get("cliente_id") != "CC#90000001":
        raise RuntimeError("Los detalles no devuelven los registros de demostracion")
    if not {"c01", "c02"}.issubset({item["caja_id"] for item in boxes["items"]}):
        raise RuntimeError("No aparecen ambas cajas")

    def read_pages(path, id_field):
        cursor = None
        identifiers = set()
        visited = set()
        for _ in range(100):
            route = path + "?limit=2"
            if cursor:
                route += "&cursor=" + urllib.parse.quote(cursor, safe="")
            page = request(route)
            for item in page["items"]:
                identifier = item[id_field]
                if identifier in identifiers:
                    raise RuntimeError("La paginacion repite registros en un catalogo estable")
                identifiers.add(identifier)
            cursor = page.get("next_cursor")
            if not cursor:
                return identifiers
            if cursor in visited:
                raise RuntimeError("El cursor de paginacion se repite")
            visited.add(cursor)
        raise RuntimeError("El conjunto supera el limite de esta comprobacion de demostracion")

    expected_products = {f"00000000-0000-4000-8000-{number:012d}" for number in (1, 2, 3)}
    expected_clients = {"CC#90000001", "CC#90000002", "GENERAL"}
    # Los listados del GSI pueden tardar en reflejar toda la carga inicial.
    for attempt in range(10):
        product_ids = read_pages("/productos", "producto_id")
        client_ids = read_pages("/clientes", "cliente_id")
        if expected_products.issubset(product_ids) and expected_clients.issubset(client_ids):
            break
        if attempt == 9:
            raise RuntimeError("El indice aun no refleja todos los datos iniciales")
        time.sleep(1)
    return {"estado": "ok", "detalle_producto": "ok", "cliente_con_identificacion": "ok",
            "cajas": [item["caja_id"] for item in boxes["items"]],
            "listados_y_paginacion": "ok"}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Comprobacion del catalogo incompleta: {exc}", file=sys.stderr)
        sys.exit(1)
