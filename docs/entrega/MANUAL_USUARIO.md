# Manual de usuario de Folio

## Abrir el sistema

El computador central debe tener Docker y la API funcionando. Desde la raíz del
proyecto, `scripts/Iniciar-Web.ps1` inicia la web. Los clientes de la LAN solo
necesitan navegador cuando el servidor se inicia con CompartirEnRed.

- Caja 1: http://localhost:8080/?caja=c01
- Caja 2: http://localhost:8080/?caja=c02

En otra máquina, sustituye localhost por la IP del computador central. Usa una
pestaña por caja. No cambies origen o puerto para recuperar una venta pendiente:
el almacenamiento del navegador está asociado a esa dirección.

## Cliente, operador y caja

El cliente realiza la compra. El operador atiende y registra la venta. La caja
identifica la terminal configurada. El nombre de operador es declarado y queda
en el comprobante, pero no verifica identidad ni otorga permisos de acceso.

## Registrar una venta

1. Verifica la caja y escribe el nombre del operador de prueba.
2. Selecciona un cliente o usa Cliente general de demostración.
3. Agrega productos desde el catálogo y ajusta cantidades enteras.
4. Revisa subtotal, impuestos y total estimados. Se admiten hasta 50 productos
   distintos y cantidades entre 1 y 9999 por línea.
5. Pulsa Confirmar venta y espera la respuesta del servidor.
6. Revisa el comprobante: referencia, fecha, cliente, operador, caja, líneas y total.

Después de confirmar y persistir el estado local, el carrito se vacía y se
habilita Último comprobante. El operador se conserva para la siguiente venta.
Los precios del catálogo son antes de impuesto. Los importes definitivos se
calculan en el servidor y se muestran en COP.

## Resolver una confirmación pendiente

Si se pierde la respuesta, el sistema conserva el carrito y la solicitud.
Pulsa Reintentar confirmación: se envía exactamente la misma intención y el
servidor recupera o confirma esa venta. No borres el almacenamiento, descartes
la pestaña o registres otra venta para intentar resolver la anterior.

Un rechazo definitivo por cambio de catálogo habilita Revisar carrito y precios.
Comprueba la nueva versión, cantidades y disponibilidad antes de confirmar de
nuevo. Un producto inactivo debe retirarse. Un aviso de cambios desde otra
pestaña de la misma caja exige recargar el estado antes de continuar.

Si el navegador no puede guardar el estado, la confirmación queda bloqueada.
Resuelve ese problema de almacenamiento sin borrar una solicitud incierta.

## Mantener productos y clientes

En Productos puedes crear un producto o editar nombre, precio, tasa y estado.
Escribe precios sin separadores de miles, por ejemplo 5000.00 o 5000,00. La tasa
es un porcentaje de demostración. Si otra terminal modificó el registro, vuelve
a consultarlo antes de intentar guardar.

En Clientes puedes registrar identificación y nombre o cambiar el nombre de un
cliente existente. La identificación se conserva como texto, incluidos ceros
iniciales. Corregir tipo o número exige registrar otro cliente.

Los buscadores filtran los registros cargados; Cargar más amplía ese conjunto.
No es una búsqueda global de toda la base de datos.

## Consultar historial

Selecciona Historial y el criterio Día del comercio, Cliente o Caja. El día
corresponde a Colombia. En rangos, Desde se incluye y Hasta se excluye: para ver
todo el día 12, utiliza como fin el día 13. El intervalo máximo es 31 días.

Los resultados se ordenan del más reciente al más antiguo. Cargar más conserva
los filtros y continúa el cursor. Cambiar un filtro inicia otra consulta. Una
venta reciente puede tardar en aparecer en el índice; refresca y usa el detalle
por ID si ya tienes la referencia.

Ver comprobante recupera el documento histórico. Un cambio de precio o nombre
en el catálogo no altera una factura emitida.

## Imprimir

Abre el comprobante y pulsa Imprimir comprobante. Revisa la vista previa, las
columnas, el total y el alcance académico. Puedes elegir Guardar como PDF en
el diálogo de impresión. Esta comprobación debe completarse manualmente.

## Diagnóstico

Diagnóstico muestra estado de API/DynamoDB/Redis y las últimas 40 peticiones de
esa terminal. X-Data-Source indica procedencia y X-Cache muestra hit, miss u otro
resultado. Si Redis falla, la lectura puede continuar desde DynamoDB. Si el
servidor central o DynamoDB no responden, no se garantiza confirmar ventas.

Los comprobantes y datos son académicos. No constituyen facturas fiscales.
