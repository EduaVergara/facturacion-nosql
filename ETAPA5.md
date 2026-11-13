# Etapa 5: historiales por cliente, caja y dia

Los documentos existentes ya tenian las claves de los tres indices. Esta etapa
agrega sus consultas HTTP; no requiere modificar la tabla ni reconstruir facturas.

| Ruta GET | Consulta | Parametros obligatorios |
|---|---|---|
| /clientes/{id}/facturas | GSI1, CLIENTE#identificacion | desde y hasta |
| /cajas/{id}/facturas | GSI2, CAJA#identificador | desde y hasta |
| /facturas | GSI3, VENTAS#DIA#fecha | fecha |

Todas admiten limit (1..25, predeterminado 25) y cursor. El orden es descendente
por fecha UTC y UUID de factura. La respuesta tiene items y next_cursor; este
ultimo es null al terminar. Un sujeto valido sin ventas devuelve una lista vacia,
aunque no exista ya su registro maestro.

## Fechas y rangos

desde y hasta admiten AAAA-MM-DD o instantes ISO con zona horaria explicita,
por ejemplo 2026-01-15T00:00:00-05:00. Una fecha simple representa medianoche
de Colombia (UTC-5, para las ventas contemporaneas de este prototipo). Los instantes
admiten hasta tres decimales y se normalizan a UTC con milisegundos.

El inicio se incluye; el fin se excluye. Para todo el dia 15 de enero:

```text
desde=2026-01-15&hasta=2026-01-16
```

El rango debe durar mas de cero y hasta 31 dias. El historial diario usa fecha
local y una sola particion de GSI3. No admite combinaciones arbitrarias de filtros.

La condicion Query usa igualdad de particion y BETWEEN sobre la clave de orden.
El limite superior es el prefijo FACTURA#instante_final sin #UUID; todas las claves
de facturas exactamente en ese instante son mayores que el prefijo y quedan fuera.
Asi se conserva el fin exclusivo sin FilterExpression ni Scan.

## Resumen y documento

Cada item devuelve factura_id, referencia, fecha_utc, fecha_local, caja_id,
cliente_id, total_centavos y moneda. Los cinco atributos de origen se proyectan
desde el GSI; referencia, fecha_local y moneda se derivan del contrato. No se
consulta el catalogo ni el cliente para reconstruir el historial.

Para abrir cliente, lineas, impuestos y demas datos historicos de una factura,
usar GET /facturas/{id}. Esa consulta conserva la cache de la etapa 4.

Los historiales no se cachean: X-Data-Source=dynamodb y X-Cache=bypass. GSI1/2/3
tienen consistencia eventual; una venta reciente puede tardar en aparecer.
La respuesta de POST /facturas y su detalle siguen permitiendo ver la venta
confirmada sin esperar al listado. Los listados no solicitan lectura fuerte al GSI.

## Cursores

next_cursor transporta la LastEvaluatedKey y el alcance de la consulta. Se valida
su version, estructura, indice, particion, fechas y correspondencia entre UUID
de factura y claves. Cambiar cliente, caja, dia o intervalo exige iniciar otra
consulta sin cursor. Dos representaciones equivalentes de un mismo instante
tienen el mismo alcance. Se puede cambiar limit entre paginas.

El cliente debe reenviar el cursor opaco sin editarlo. Se codifica en Base64 URL;
no constituye una firma ni un mecanismo de autorizacion. En un conjunto estable,
el desempate por UUID permite paginar facturas de igual hora sin duplicados.
La paginacion no crea un snapshot de la base: ventas concurrentes y propagacion
del indice pueden requerir refrescar el historial desde su primera pagina.

## Ejemplos desde PowerShell

```powershell
$salidas = Get-Content .\app\cdk-outputs.json -Raw | ConvertFrom-Json
$api = @($salidas.PSObject.Properties.Value | Where-Object { $_.ApiId })[0]
$base = $api.ApiUrl.TrimEnd('/')
$cliente = [uri]::EscapeDataString('CC#90000001')
$pagina = Invoke-RestMethod "$base/clientes/$cliente/facturas?desde=2026-11-12&hasta=2026-11-13&limit=2"
$pagina | ConvertTo-Json -Depth 8
if ($pagina.next_cursor) {
    $cursor = [uri]::EscapeDataString($pagina.next_cursor)
    Invoke-RestMethod "$base/clientes/$cliente/facturas?desde=2026-11-12&hasta=2026-11-13&limit=2&cursor=$cursor"
}
Invoke-RestMethod "$base/cajas/c01/facturas?desde=2026-11-12&hasta=2026-11-13"
Invoke-RestMethod "$base/facturas?fecha=2026-11-12"
```

Los identificadores con # y los cursores deben codificarse para usarlos en URLs.
El ejemplo no presupone que existan ventas en esa fecha: una lista vacia es valida.

## Aplicar y verificar

Extraer todo el paquete; conservar juntos Aplicar-Etapa5.ps1 y su carpeta:

```powershell
.\Aplicar-Etapa5.ps1
cd "$env:USERPROFILE\Desktop\facturacion-nosql"
.\scripts\Verificar-Etapa5.ps1
```

El instalador conserva .env, configuracion, salidas, contextos de demostracion y
datos; respalda los archivos reemplazados. No requiere reconstruir contenedores.
La verificacion ejecuta pytest antes del despliegue, respalda tabla y plantilla,
actualiza el stack recuperado y publica prod mediante el procedimiento ya probado.

check_history.py crea inicialmente un cliente OTRO#H5-* y 32 facturas ficticias en
torno al 15 de enero de 2026. Hay 27 facturas a la misma hora, una al inicio del dia,
otra al ultimo milisegundo y tres fuera del intervalo. Comprueba que el dia central
tenga 29 facturas y necesite mas de una pagina con limit=25. Verifica las cajas,
el dia, el siguiente dia, los cursores y el detalle documental.

Las fechas controladas se insertan mediante el SDK en este script administrativo
de demostracion. POST /facturas sigue asignando la fecha del servidor y rechaza
fechas enviadas por las cajas. Las fixtures conservan el calculo, transaccion,
snapshot e idempotencia del servicio. No se borra ni se sobrescribe una venta.

app/historial-demo-etapa5.json conserva cuerpos, solicitudes e IDs para reanudar
la carga y reutilizar esas 32 facturas. La primera verificacion completa crea
36 ventas ficticias: 32 de historial y cuatro de regresion. Al repetir se agregan
las cuatro de regresion y se reutilizan las 32 de historial.

Para repetir solo el historial:

```powershell
docker compose exec -T cdk-dev python scripts/check_history.py
```

Si recreaste la tabla y necesitas otro conjunto de demostracion:

```powershell
docker compose exec -T cdk-dev python scripts/check_history.py --new-demo
```

Esto crea otro cliente y otras 32 facturas; no elimina los anteriores y respalda
el contexto anterior. El contexto y respaldos quedan fuera de Git y del paquete.

RESULTADO_LOCAL.json documenta las pruebas ejecutadas al preparar la entrega.
Las comprobaciones reales y las pruebas de CDK/moto se completan en Docker.
La etapa 6 construira las pantallas de las cajas, historiales y comprobantes.

Referencias:

- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.KeyConditionExpressions.html
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html
