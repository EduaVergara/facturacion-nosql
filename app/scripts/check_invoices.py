"""Prueba HTTP de ventas ficticias y persistencia real, sin borrar registros."""
import copy
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP

from local_http import request_json
from local_outputs import load_outputs


def verify():
    import boto3
    outputs = load_outputs()
    endpoint = os.environ["AWS_ENDPOINT_URL"].rstrip("/")
    base = f"{endpoint}/restapis/{outputs['ApiId']}/prod/_user_request_"
    def request(path, **kwargs):
        return request_json(base + path, **kwargs)
    products = [request(f"/productos/00000000-0000-4000-8000-{i:012d}")[1] for i in (1, 2)]
    if any(not product["activo"] for product in products):
        raise RuntimeError("Los productos de demostracion deben estar activos")
    def intention(box="c01"):
        return {"solicitud_id": str(uuid.uuid4()), "caja_id": box, "operador_declarado": "Prueba automatica etapa 3",
                "cliente_id": "CC#90000001", "lineas": [
                    {"producto_id": p["producto_id"], "cantidad": 2, "version_esperada": p["version"]} for p in products]}
    table = boto3.resource("dynamodb").Table(outputs["TableName"])
    def persisted(data, result):
        doc = table.get_item(Key={"PK": f"FACTURA#{result['factura']['factura_id']}", "SK": "DOCUMENTO"}, ConsistentRead=True)["Item"]
        receipt = table.get_item(Key={"PK": f"SOLICITUD#{data['caja_id']}#{data['solicitud_id']}", "SK": "RESULTADO"}, ConsistentRead=True)["Item"]
        assert receipt["factura_id"] == doc["factura_id"] == result["factura"]["factura_id"]
        assert len(doc["lineas"]) == 2 and doc["cliente"]["numero_documento"] == "90000001"
        return doc

    data = intention()
    # POST se puede repetir tras un timeout usando exactamente el mismo cuerpo.
    _, first, _ = request("/facturas", method="POST", data=data, expected=(200, 201))
    _, repeated, _ = request("/facturas", method="POST", data=data)
    assert repeated["replayed"] is True and repeated["factura"] == first["factura"]
    _, detail, _ = request("/facturas/" + first["factura"]["factura_id"])
    assert detail == first["factura"]
    subtotal = sum(p["precio_unitario_centavos"] * 2 for p in products)
    taxes = sum(int((Decimal(p["precio_unitario_centavos"] * 2) * p["impuesto_bps"] / Decimal(10000))
                    .quantize(Decimal(1), rounding=ROUND_HALF_UP)) for p in products)
    assert detail["subtotal_centavos"] == subtotal and detail["total_centavos"] == subtotal + taxes
    persisted(data, first)
    changed = copy.deepcopy(data)
    changed["lineas"][0]["cantidad"] = 3
    request("/facturas", method="POST", data=changed, expected=(409,))

    concurrent = intention()
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: request("/facturas", method="POST", data=concurrent, expected=(200, 201))[1], range(2)))
    assert len({r["factura"]["factura_id"] for r in replies}) == 1
    persisted(concurrent, replies[0])

    two_boxes = [intention("c01"), intention("c02")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        separate = list(pool.map(lambda body: request("/facturas", method="POST", data=body, expected=(200, 201))[1], two_boxes))
    assert len({r["factura"]["factura_id"] for r in separate}) == 2
    for body, result in zip(two_boxes, separate):
        persisted(body, result)
    stale = intention()
    stale["lineas"][0]["version_esperada"] = products[0]["version"] + 1
    _, conflict, _ = request("/facturas", method="POST", data=stale, expected=(409,))
    assert conflict["codigo"] == "CATALOGO_CAMBIO"
    absent = table.get_item(Key={"PK": f"SOLICITUD#c01#{stale['solicitud_id']}", "SK": "RESULTADO"}, ConsistentRead=True)
    assert "Item" not in absent
    return {"estado": "ok", "calculo_en_servidor": "ok", "documento_y_solicitud_persistidos": "ok",
            "reenvio_sin_duplicados": "ok", "envios_simultaneos": "ok", "dos_cajas": "ok",
            "version_desactualizada_rechazada": "ok", "ventas_ficticias_creadas": 4,
            "factura_ejemplo": detail["factura_id"], "total_ejemplo_centavos": detail["total_centavos"]}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Comprobacion de facturas incompleta ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
