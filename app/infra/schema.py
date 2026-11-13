"""Contrato de claves e índices correspondiente al documento de diseño."""

TABLE_NAME = "Facturacion"
INDEX_PROJECTIONS = {
    "GSI1": [
        "tipo_entidad", "nombre", "activo", "version",
        "precio_unitario_centavos", "impuesto_bps", "factura_id",
        "fecha_utc", "caja_id", "cliente_id", "total_centavos",
    ],
    "GSI2": ["factura_id", "fecha_utc", "caja_id", "cliente_id", "total_centavos"],
    "GSI3": ["factura_id", "fecha_utc", "caja_id", "cliente_id", "total_centavos"],
}
