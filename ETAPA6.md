# Etapa 6 · Interfaz web Folio

Folio permite vender, gestionar el catálogo y los clientes, consultar historiales
por cliente/caja/día, abrir comprobantes e imprimirlos. Es un prototipo académico.
Las tasas se configuran para la demostración; los comprobantes no son facturas
fiscales autorizadas. Esta etapa utiliza los servicios de las etapas 1–5.

## Instalar y verificar

1. Extrae TODO el ZIP en otra carpeta. Conserva juntos `Aplicar-Etapa6.ps1` y
   `facturacion-nosql`. No ejecutes archivos dentro de la vista del ZIP.
2. Abre PowerShell en la carpeta extraída y ejecuta ` .\Aplicar-Etapa6.ps1 `.
   El destino predeterminado es el proyecto `facturacion-nosql` del escritorio.
   Otro destino: ` .\Aplicar-Etapa6.ps1 -ProjectPath 'C:\ruta\facturacion-nosql' `.
3. Desde el proyecto del escritorio ejecuta:

```powershell
cd "$env:USERPROFILE\Desktop\facturacion-nosql"
.\scripts\Verificar-Etapa6.ps1
```

El instalador respalda archivos reemplazados en `.actualizaciones/etapa6-*` y
conserva `.env`, configuración, salidas CDK, contextos de demostración y respaldos.
La verificación ejecuta las pruebas Python y Node antes de desplegar. Reutiliza
la imagen `facturacion-nosql-cdk-dev` existente, sin reconstruir ni descargar otra.
Actualiza las funciones, conserva el esquema/tabla/índices y publica prod con el
mecanismo ya usado en las etapas anteriores. Agrega un servicio `frontend`.

Al final comprueba archivos web, proxy, dos ventas ficticias y su reenvío sin
duplicación, comprobantes e historial. También repite las comprobaciones previas:
crea cuatro ventas de regresión y reutiliza las 32 solicitudes de historial si su
contexto existe. No borra registros. El mensaje final automático no reemplaza la
revisión visual indicada abajo.

## Abrir las dos cajas

- Caja 1: http://localhost:8080/?caja=c01
- Caja 2: http://localhost:8080/?caja=c02

Cada caja conserva operador, cliente, carrito y solicitud pendiente en el
almacenamiento del navegador. Usa una pestaña por caja. Si otra pestaña modifica
esa misma caja, la interfaz solicita recargar antes de continuar; los historiales
permiten ver el trabajo conjunto. La caja del selector solo cambia con carrito
vacío y sin confirmación pendiente. No hay autenticación: el operador es declarado.

## Revisión visual después de verificar

1. En caja 1 escribe tu nombre, selecciona un cliente y agrega dos productos.
   Cambia cantidades y confirma. Debe abrirse el comprobante con los totales
   devueltos por el servidor; el carrito queda vacío después de guardar el estado.
2. Abre caja 2, usa otro operador y registra una venta. Su carrito debe ser
   independiente. Consulta Historial → Día del comercio para ver ambas ventas.
3. Prueba Historial → Cliente y Caja. Desde incluye el inicio y Hasta excluye
   el día elegido. Para consultar un día completo usa como Hasta el día siguiente.
   El rango máximo es 31 días. Abre un comprobante desde el historial.
4. Para probar paginación, consulta el día de demostración 2026-01-15 y pulsa
   Cargar más facturas: la etapa 5 preparó 29 facturas de ese día. El cursor
   se descarta cuando cambias filtros.
5. Crea un producto ficticio y un cliente de prueba. Edita el nombre/precio del
   producto. Al abrir una factura anterior debe conservar los datos de la venta.
   El precio se escribe sin separadores de miles: 5000.00 o 5000,00.
6. Pulsa Imprimir comprobante y revisa la vista previa. Puedes guardar como PDF
   mediante el diálogo del navegador. Cierra la vista previa si no vas a imprimir.
   Comprueba también la distribución en una ventana estrecha.
7. En Diagnóstico comprueba servicios y consulta Origen/Caché de las peticiones.
   Repite la lectura de un mismo producto/comprobante para observar miss y hit.

Si una confirmación pierde conexión o devuelve un error incierto, conserva la
pestaña y su almacenamiento. El carrito queda bloqueado y Reintentar confirmación
reenvía exactamente la misma solicitud. Recargar conserva ese estado. No borres
el almacenamiento ni cambies de navegador para reintentar esa venta. Si el
servidor rechaza definitivamente una versión, Revisar carrito y precios permite
corregirla antes de crear una intención nueva. No hay cola de ventas sin conexión.

## Volver a iniciar o compartir en la LAN

Con los contenedores base funcionando, iniciar únicamente la web:

```powershell
.\scripts\Iniciar-Web.ps1
```

Para probar clientes ligeros en otros computadores de la misma red:

```powershell
.\scripts\Iniciar-Web.ps1 -CompartirEnRed
```

En cada cliente abre `http://IP-DEL-COMPUTADOR-CENTRAL:8080/?caja=c02`.
El cliente solo necesita un navegador moderno. El script publica únicamente la
web en las interfaces de red; no modifica firewall ni expone Redis. Si Windows
solicita acceso para Docker, utiliza la red privada del laboratorio. Para volver
al acceso exclusivo del equipo central ejecuta Iniciar-Web sin ese parámetro.

Si 8080 está ocupado usa `-Puerto 8081` (también en Verificar-Etapa6). Usa el
mismo origen y puerto al volver a una venta pendiente, pues el almacenamiento
local está asociado al origen. Cierra la aplicación desde la interfaz habitual
de Docker al terminar; no uses `down -v`, que eliminaría volúmenes.

## Organización y decisiones

| Archivo | Responsabilidad |
| --- | --- |
| frontend/index.html y styles.css | Navegación, formularios, distribución adaptable e impresión |
| frontend/app.mjs | Vistas, catálogos, eventos y llamadas a la API |
| frontend/domain.mjs | Importes exactos, borradores por caja e intención persistente |
| frontend/api.mjs | HTTP con timeout y sin reintento automático de POST |
| app/scripts/serve_frontend.py | Archivos estáticos y proxy a rutas permitidas de la API |
| docker-compose.web.yml | Servicio web que reutiliza la imagen ya construida |
| scripts/Iniciar-Web.ps1 | Inicio local o LAN con puerto configurable |
| scripts/Verificar-Etapa6.ps1 | Pruebas, respaldo, despliegue y comprobaciones HTTP |

El navegador usa `/api` en el mismo origen. El proxy resuelve el ApiId desde las
salidas actuales, evitando que cada terminal necesite conocer LocalStack o su
DNS interno. No necesita dependencias npm ni conexión a CDN. El servidor expone
solo archivos permitidos y rutas del negocio, con límite de cuerpo de 64 KiB.
El contenedor web no requiere credenciales AWS.

Los totales del carrito son estimados con enteros BigInt y HALF_UP por línea.
POST envía IDs, cantidades y versiones; el servidor determina los valores
persistidos. Los comprobantes leen la copia histórica de la factura. Los nombres
se escriben con textContent para que texto comercial no se interprete como HTML.
Las búsquedas de catálogo/directorio filtran los registros cargados; Cargar más
amplía ese conjunto. No se presenta como búsqueda global.

## Estado de la entrega y siguiente etapa

Las pruebas locales cubren reglas monetarias, solicitudes persistentes, fallos,
contratos con los handlers y proxy. La ejecución Docker y la revisión visual en
el navegador del estudiante quedan por confirmar con Verificar-Etapa6 y la lista
anterior. La vista en navegador no pudo abrirse desde el entorno de preparación;
no se afirma una validación visual completada.

Después de confirmar esta etapa sigue la **7: cierre integral, documentación,
evidencias, demostración y preparación de la sustentación**.
