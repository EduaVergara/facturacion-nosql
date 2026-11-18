# API

La interfaz utiliza `http://localhost:8080/api`. También puedes consultar el API
Gateway en la URL que emite CDK. Hay 15 combinaciones de método y ruta, sin contar
OPTIONS ni el `/ready` del servidor web.

| Ruta | Métodos | Operación |
| --- | --- | --- |
| /health | GET | Estado de servicios |
| /productos | GET, POST | Listar y crear |
| /productos/{id} | GET, PUT | Consultar y actualizar |
| /clientes | GET, POST | Listar y crear |
| /clientes/{id} | GET, PUT | Consultar y actualizar nombre |
| /cajas | GET | Listar cajas |
| /facturas | GET, POST | Historial diario y confirmación |
| /facturas/{id} | GET | Documento histórico |
| /clientes/{id}/facturas | GET | Historial por cliente |
| /cajas/{id}/facturas | GET | Historial por caja |

## Confirmar una venta

POST /facturas requiere Content-Type: application/json:

```json
{
  "solicitud_id": "00000000-0000-4000-8000-000000000099",
  "caja_id": "c01",
  "operador_declarado": "Operador de prueba",
  "cliente_id": "GENERAL",
  "lineas": [
    {
      "producto_id": "00000000-0000-4000-8000-000000000001",
      "cantidad": 2,
      "version_esperada": 1
    }
  ]
}
```

Consulta la versión actual antes de enviar. Cada intención nueva genera un UUID;
un reintento conserva exactamente cuerpo y UUID. No envíes precios, impuestos
ni totales: el servidor rechaza esos campos y determina los importes.

Una creación devuelve 201, factura completa y replayed=false. Un reenvío válido
devuelve 200, la factura original y replayed=true. Los errores de catálogo
incluyen CATALOGO_CAMBIO y los productos que deben revisarse. Una intención
distinta que reutiliza la misma clave se rechaza.

## Listados e historial

Productos, clientes, cajas e historiales admiten `limit` de 1 a 25 y `cursor`.
Las respuestas contienen `items` y `next_cursor`. Conserva los filtros al usar
un cursor; no es un número de página.

El historial diario exige `fecha=AAAA-MM-DD`. Cliente/caja requieren `desde` y
`hasta`: inicio incluido, fin excluido, intervalo mayor que cero de hasta 31 días.
Las fechas simples se interpretan en Colombia. Los instantes ISO deben incluir
zona. Para un día completo utiliza el día siguiente como `hasta`.

Codifica la identificación al ponerla en una URL: CC#90000001 se convierte en
CC%2390000001. Las actualizaciones PUT requieren version_esperada.

Las lecturas informan X-Data-Source y X-Cache. Los importes JSON están en centavos
COP. Un health 503 puede indicar degradación por Redis aunque DynamoDB siga
disponible para vender.
