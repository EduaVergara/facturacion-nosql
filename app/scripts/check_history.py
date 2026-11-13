"""Fixtures academicos con fechas controladas y verificacion HTTP de los GSI."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlencode
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"lambdas"))
from catalogo.model import ApiError
from catalogo.repository import DynamoRepository
from catalogo.service import CatalogService
from facturacion.history import boundary
from facturacion.model import invoice_document
from facturacion.repository import InvoiceRepository
from facturacion.service import InvoiceService
from local_http import request_json
from local_outputs import load_outputs

CONTEXT_PATH = Path(__file__).resolve().parents[1]/"historial-demo-etapa5.json"
DAY = "2026-01-15"
RANGE = {"desde": DAY, "hasta": "2026-01-16"}


class IndexLag(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class HistoryCheck:
    def __init__(self):
        outputs = load_outputs()
        self.table_name = outputs["TableName"]
        self.base = f"{os.environ['AWS_ENDPOINT_URL'].rstrip('/')}/restapis/{outputs['ApiId']}/prod/_user_request_"
        self.repo = InvoiceRepository(table_name=self.table_name)
        self.catalog = CatalogService(DynamoRepository())

    def request(self, path, query=None, **kwargs):
        return request_json(self.base + path + ("?" + urlencode(query) if query else ""), **kwargs)

    def prepare(self, new_demo=False):
        if CONTEXT_PATH.exists() and not new_demo:
            data = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
            require(data.get("v") == 1 and data.get("table") == self.table_name and data.get("day") == DAY
                    and len(data.get("rows", [])) == 32 and data.get("customer_id", "").startswith("OTRO#H5-"),
                    "Contexto de demostracion no valido; revisa el archivo o usa --new-demo")
        else:
            product_id = "00000000-0000-4000-8000-000000000001"
            product = self.repo.get(f"PRODUCTO#{product_id}", "DATOS")
            require(product is not None and product.get("activo") is True, "El producto de demostracion no esta activo")
            code = "H5-" + uuid.uuid4().hex[:24].upper()
            customer_id = "OTRO#" + code
            times = (["2026-01-15T04:59:59.999Z", "2026-01-15T05:00:00.000Z"]
                     + ["2026-01-15T17:30:00.000Z"]*27
                     + ["2026-01-16T04:59:59.999Z", "2026-01-16T05:00:00.000Z", "2026-01-16T05:00:00.001Z"])
            data = {"v":1, "table":self.table_name, "day":DAY, "customer_id":customer_id,
                    "customer_values":{"tipo_documento":"OTRO", "numero_documento":code,
                                       "nombre":"Cliente ficticio historial " + code[-8:]}, "rows":[]}
            for number, stamp in enumerate(times):
                box = "c01" if number % 2 == 0 else "c02"
                data["rows"].append({"factura_id":str(uuid.uuid4()), "stamp":stamp, "caja_id":box,
                    "body":{"solicitud_id":str(uuid.uuid4()), "caja_id":box,
                        "operador_declarado":"Fixture academico historial etapa 5", "cliente_id":customer_id,
                        "lineas":[{"producto_id":product_id, "cantidad":1, "version_esperada":product["version"]}]}})
            if CONTEXT_PATH.exists():
                old = CONTEXT_PATH.parent/"backups"/("historial-contexto-"+datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")+".json")
                old.parent.mkdir(parents=True, exist_ok=True)
                old.write_bytes(CONTEXT_PATH.read_bytes())
            CONTEXT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            self.catalog.create_client(data["customer_values"])
        except ApiError as exc:
            if exc.status != 409:
                raise
            existing = self.catalog.client(data["customer_id"])
            require(all(existing[key] == data["customer_values"][key] for key in ("tipo_documento", "numero_documento")),
                    "La identificacion ficticia ya existe con otros datos; usa --new-demo")
        created = replayed = 0
        for number, row in enumerate(data["rows"], 1):
            def factory(body, products, customer, selected=row):
                return invoice_document(body, products, customer, identifier=selected["factura_id"], instant=boundary(selected["stamp"]))
            result = InvoiceService(self.repo, document_factory=factory).create(row["body"])
            require(result["factura"]["factura_id"] == row["factura_id"], "La solicitud ficticia apunta a otra factura")
            created += int(not result["replayed"])
            replayed += int(result["replayed"])
            if number % 8 == 0:
                print(f"Fixtures de historial preparados: {number}/32", flush=True)
        print(json.dumps({"facturas_ficticias_nuevas":created, "solicitudes_reutilizadas":replayed,
                          "cliente_ficticio":data["customer_id"]}), flush=True)
        return data

    def pages(self, path, query):
        found, cursor, seen, known_ids, page_count = [], None, set(), set(), 0
        for _ in range(500):
            parameters = {**query}
            if cursor:
                parameters["cursor"] = cursor
            _, page, headers = self.request(path, parameters)
            headers = {key.lower():value for key,value in headers.items()}
            require(headers.get("x-data-source") == "dynamodb" and headers.get("x-cache") == "bypass",
                    "El historial debe consultar el indice sin cache")
            require(isinstance(page.get("items"),list), "Formato de pagina no valido")
            for item in page["items"]:
                require(not {"lineas","cliente","PK","SK"}.intersection(item), "El listado debe devolver resumenes")
                require({"factura_id","fecha_utc","caja_id","cliente_id","total_centavos"}.issubset(item), "Resumen incompleto")
                require(item["factura_id"] not in known_ids, "Factura duplicada entre paginas")
                known_ids.add(item["factura_id"])
                found.append(item)
            page_count += 1
            cursor = page.get("next_cursor")
            if cursor is None:
                order = [(item["fecha_utc"],item["factura_id"]) for item in found]
                require(order == sorted(order, reverse=True), "El historial no esta en orden descendente")
                return found, page_count
            require(isinstance(cursor,str) and cursor and cursor not in seen, "Cursor vacio o repetido")
            seen.add(cursor)
        raise RuntimeError("La demostracion supera 500 paginas; reduce el conjunto de prueba")

    @staticmethod
    def covers(actual, expected, exact=False):
        ids = {item["factura_id"] for item in actual}
        if not expected.issubset(ids):
            raise IndexLag("Los indices aun no reflejan todas las facturas ficticias")
        if exact:
            require(ids == expected, "El indice mezclo datos de otro cliente o intervalo")
        return ids

    def verify(self, data):
        customer_path = "/clientes/" + quote(data["customer_id"], safe="") + "/facturas"
        start, end = boundary(RANGE["desde"]), boundary(RANGE["hasta"])
        inside = [row for row in data["rows"] if start <= boundary(row["stamp"]) < end]
        expected = {row["factura_id"] for row in inside}
        customer, customer_pages = self.pages(customer_path, RANGE)
        self.covers(customer, expected, exact=True)
        require(customer_pages >= 2 and len(customer) == 29, "No se comprobo la pagina posterior al limite 25")
        all_rows, _ = self.pages(customer_path, {"desde":"2026-01-14", "hasta":"2026-01-17", "limit":"7"})
        self.covers(all_rows, {row["factura_id"] for row in data["rows"]}, exact=True)
        for box in ("c01","c02"):
            rows, _ = self.pages(f"/cajas/{box}/facturas", {**RANGE,"limit":"3"})
            self.covers(rows, {row["factura_id"] for row in inside if row["caja_id"] == box})
            require(all(row["caja_id"] == box for row in rows), "Se mezclaron cajas")
        daily, daily_pages = self.pages("/facturas", {"fecha":DAY,"limit":"5"})
        day_ids = self.covers(daily, expected)
        require(all(row["fecha_local"] == DAY for row in daily), "Se mezclaron dias locales")
        require(not ({row["factura_id"] for row in data["rows"]}-expected).intersection(day_ids), "El fin exclusivo incluyo otra fecha")
        next_day, _ = self.pages(customer_path, {"desde":"2026-01-16","hasta":"2026-01-17"})
        self.covers(next_day, {row["factura_id"] for row in data["rows"] if boundary(row["stamp"]) >= end}, exact=True)
        _, first_page, _ = self.request(customer_path, {**RANGE,"limit":"2"})
        token = first_page["next_cursor"]
        require(token is not None, "No se obtuvo cursor de demostracion")
        self.request("/cajas/c01/facturas", {**RANGE,"cursor":token}, expected=(400,))
        self.request(customer_path, {**RANGE,"hasta":"2026-01-17","cursor":token}, expected=(400,))
        self.request("/facturas", {"fecha":"2026-02-30"}, expected=(400,))
        self.request(customer_path, {**RANGE,"limit":"0"}, expected=(400,))
        _, detail, _ = self.request("/facturas/" + customer[0]["factura_id"])
        require(detail["cliente_id"] == data["customer_id"] and detail.get("lineas"), "El resumen no abre su documento completo")
        return {"estado":"ok", "historial_cliente_GSI1":"ok", "historial_caja_GSI2":"ok",
                "historial_diario_GSI3":"ok", "orden_y_paginacion":"ok", "cursores_ligados_a_filtros":"ok",
                "inicio_incluido_fin_excluido":"ok", "dia_de_colombia":"ok", "consulta_detalle":"ok",
                "facturas_cliente_en_dia":len(customer), "paginas_cliente_limite_25":customer_pages,
                "paginas_dia_limite_5":daily_pages, "cliente_ficticio":data["customer_id"], "fecha_ficticia":DAY}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-demo", action="store_true")
    args = parser.parse_args()
    try:
        check = HistoryCheck()
        data = check.prepare(args.new_demo)
        for attempt in range(20):
            try:
                report = check.verify(data)
                break
            except IndexLag:
                if attempt == 19:
                    raise
                print("Esperando propagacion de los indices de historial...", flush=True)
                time.sleep(0.5)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Comprobacion de historiales incompleta ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
