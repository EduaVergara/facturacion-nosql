"""Ventas atomicas, snapshots e idempotencia persistente por caja."""
import time
import uuid

from catalogo.model import ApiError, public_item
from .model import SaleError, intention, intention_hash, invoice_document, request_record, uuid_value
from .repository import CommitConflict


class InvoiceService:
    def __init__(self, repository, *, sleep=time.sleep, document_factory=invoice_document):
        self.repository = repository
        self.sleep = sleep
        self.document_factory = document_factory

    def invoice(self, identifier):
        identifier = uuid_value(identifier, "factura_id")
        document = self.repository.get(f"FACTURA#{identifier}", "DOCUMENTO")
        if document is None:
            raise ApiError(404, "Factura no encontrada")
        return public_item(document)

    def replay(self, data, digest):
        result = self.repository.get(f"SOLICITUD#{data['caja_id']}#{data['solicitud_id']}", "RESULTADO")
        if result is None:
            return None
        if result["intencion_sha256"] != digest:
            raise SaleError(409, "Esta solicitud_id ya se uso para otra venta; usa otra clave para una nueva intencion",
                            codigo="SOLICITUD_REUTILIZADA")
        document = self.invoice(result["factura_id"])
        return {"factura": document, "replayed": True}

    def snapshot(self, data):
        box = self.repository.get("CONFIG#CAJAS", f"CAJA#{data['caja_id']}")
        if box is None:
            raise ApiError(404, "Caja no encontrada")
        if box.get("activo") is not True:
            raise SaleError(409, "La caja no esta activa", codigo="CAJA_INACTIVA")
        customer = self.repository.get(f"CLIENTE#{data['cliente_id']}", "PERFIL")
        if customer is None:
            raise ApiError(404, "Cliente no encontrado")
        products, changed = {}, []
        for line in data["lineas"]:
            product = self.repository.get(f"PRODUCTO#{line['producto_id']}", "DATOS")
            if product is None:
                raise ApiError(404, "Producto no encontrado: " + line["producto_id"])
            products[line["producto_id"]] = product
            if product.get("activo") is not True or product["version"] != line["version_esperada"]:
                changed.append({"producto_id": line["producto_id"], "nombre": product["nombre"],
                    "cantidad": line["cantidad"], "activo": product.get("activo", False),
                    "version": product["version"], "precio_unitario_centavos": product["precio_unitario_centavos"],
                    "impuesto_bps": product["impuesto_bps"]})
        if changed:
            raise SaleError(409, "El catalogo cambio; revisa el carrito y confirma con otra solicitud_id",
                            codigo="CATALOGO_CAMBIO", carrito_actualizado=changed)
        return products, customer, box

    def create(self, raw):
        data = intention(raw)
        digest = intention_hash(data)
        existing = self.replay(data, digest)
        if existing is not None:
            return existing
        try:
            products, customer, box = self.snapshot(data)
        except ApiError:
            # Otro envio pudo confirmar esta solicitud mientras se leian los maestros.
            existing = self.replay(data, digest)
            if existing is not None:
                return existing
            raise
        document = self.document_factory(data, products, customer)
        receipt = request_record(data, digest, document)
        # Token de transporte unico por invocacion, estable en sus reintentos.
        # La garantia duradera de negocio es el registro SOLICITUD sin TTL.
        token = str(uuid.uuid4())
        for attempt in range(3):
            try:
                self.repository.commit(document, receipt, products, customer, box, token)
                return {"factura": public_item(document), "replayed": False}
            except CommitConflict as exc:
                existing = self.replay(data, digest)
                if existing is not None:
                    return existing
                if exc.kind == "conditional":
                    self.snapshot(data)  # Devuelve el carrito actualizado si cambio el catalogo.
                    raise SaleError(409, "Los datos de la venta cambiaron durante el registro; vuelve a confirmar",
                                    codigo="DATOS_CAMBIARON") from exc
                if attempt < 2:
                    self.sleep(0.05 * (2**attempt))
            except ApiError as exc:
                if exc.status != 503:
                    raise
                # Una respuesta perdida puede ocurrir despues de confirmar el commit.
                try:
                    existing = self.replay(data, digest)
                except ApiError as read_error:
                    if read_error.status != 503:
                        raise
                    existing = None
                if existing is not None:
                    return existing
                raise
        raise ApiError(503, "La venta sigue sin confirmarse; reintenta con la misma solicitud_id y cuerpo")
