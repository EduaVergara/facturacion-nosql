# Etapa 4: cache con Redis

Se incorpora Cache-Aside en GET /productos/{id} y GET /facturas/{id}. La factura
persistida y la tabla unica conservan el modelo de la etapa 3.

| Dato | Clave Redis | TTL |
|---|---|---|
| Producto | facturacion:v1:producto:UUID | 60 segundos |
| Factura inmutable | facturacion:v1:factura:UUID | 300 segundos |

## Lecturas y diagnostico

1. Buscar JSON en Redis, comprobar tipo, identidad, esquema y expiracion.
2. Ante un hit valido, devolverlo sin consultar DynamoDB ni extender su TTL.
3. Ante miss o entrada invalida, consultar DynamoDB y guardar el documento con SET EX.
4. Ante fallo de Redis, devolver la lectura de DynamoDB. No se cachean los 404.

La respuesta conserva el mismo cuerpo documental. La procedencia va en cabeceras:

| Cabecera | Valores |
|---|---|
| X-Data-Source | dynamodb o redis |
| X-Cache | hit, miss, invalid, error o bypass |

bypass identifica rutas que no usan cache. CORS expone ambas cabeceras para la
futura pantalla de diagnostico. Clientes, cajas, listados e historiales no se
cachean en esta version. JSON mal formado, ID incorrecto, esquema desconocido,
valores incoherentes o una clave sin TTL se descartan y se consultan de nuevo.

## Escrituras y consistencia

PUT /productos/{id} lee y escribe DynamoDB con control de version. Solo despues
de guardar correctamente intenta borrar la clave Redis. Si falla la invalidacion,
la actualizacion sigue confirmada en DynamoDB. Otra lectura puede mostrar el
valor anterior hasta que expire su TTL. Una lectura concurrente tambien puede
repoblar una version anterior; esta version acepta esa ventana de desactualizacion.

El precio cobrado siempre se verifica leyendo DynamoDB y mediante ConditionCheck
en la transaccion. Un carrito con version anterior recibe 409 y debe reconfirmarse.
POST /facturas, incluyendo sus reenvios, no abre Redis ni obtiene precios de cache.
La resolucion de solicitudes repetidas sigue usando lecturas fuertes de tabla.

Las facturas son inmutables: su cache expira naturalmente y no cambia al editar
un producto o cliente. El comprobante historico conserva sus datos originales.

## Fallos de Redis

El cliente usa tiempos de conexion y lectura de 200 ms como maximo y cero
reintentos automaticos. Tras un fallo de cache, esa peticion evita mas intentos
con Redis y continua con DynamoDB. Los clientes Redis se cierran al finalizar
la peticion. Los fallos se registran sin incluir detalles internos en la API.

Con Redis detenido, /health devuelve 503 y estado degradado, con DynamoDB ok y
Redis error. Las consultas de detalle y las ventas siguen disponibles si DynamoDB
esta operativo. Tras restaurarlo, nuevas peticiones vuelven a poblar la cache.

## Ejecutar la verificacion

Desde la carpeta extraida, conservar juntos el instalador y su carpeta de archivos:

```powershell
.\Aplicar-Etapa4.ps1
cd "$env:USERPROFILE\Desktop\facturacion-nosql"
.\scripts\Verificar-Etapa4.ps1
```

No requiere reconstruir contenedores; redis-py y fakeredis ya estaban instalados.
El instalador conserva configuracion y datos, y respalda archivos reemplazados.
La verificacion ejecuta pytest, respalda tabla/plantilla y actualiza el stack
recuperado. Reutiliza la preparacion y publicacion de API validadas en la etapa 3.

La prueba de cache tiene tres fases:

- online: crea un producto ficticio, comprueba miss/hit, TTL, JSON invalido,
  actualizacion e invalidacion, expiracion y una factura historica.
- offline: detiene Redis, comprueba /health degradado, lecturas desde DynamoDB,
  otra venta y un reenvio sin duplicados.
- recovered: restaura Redis, comprueba /health y vuelve a demostrar miss/hit.

El script PowerShell restaura Redis en finally incluso si falla la fase offline.
Para repetir solo esa prueba, sin volver a desplegar:

```powershell
.\scripts\Probar-Cache.ps1
```

Cada ejecucion completa de Verificar-Etapa4 crea un producto y seis facturas
ficticias. No modifica los productos o clientes que ya tenias. Solo edita el
producto nuevo de prueba y sus claves de cache; no usa FLUSHALL ni borra ventas.
Para comprobar expiracion sin esperar cinco minutos, acorta con PEXPIRE solo
las claves del producto y factura ficticios y comprueba que vuelvan a DynamoDB.
Tambien verifica que los TTL originalmente asignados sean 60 y 300 segundos.

app/cache-demo-etapa4.json guarda los IDs y el cuerpo del reenvio de demostracion.
El instalador lo conserva; el archivo se excluye de Git y del paquete. Para
restaurar Redis manualmente si se cierra la terminal durante una demostracion:

```powershell
docker compose up -d --wait redis
```

## Evidencia y alcance

RESULTADO_LOCAL.json recoge las pruebas que se pudieron ejecutar al preparar el
paquete. Las pruebas con fakeredis y CDK y las comprobaciones de Docker deben
ejecutarse en cdk-dev. El ensayo con objetos en memoria no confirma el despliegue.
La etapa 5 agregara los historiales por cliente, caja y dia con paginacion.

Referencias:

- https://redis.io/docs/latest/develop/clients/redis-py/produsage/
- https://redis.io/docs/latest/commands/set/
- https://redis.io/docs/latest/commands/ttl/
- https://redis.io/docs/latest/commands/pexpire/
- https://redis.readthedocs.io/en/stable/_modules/redis/retry.html
