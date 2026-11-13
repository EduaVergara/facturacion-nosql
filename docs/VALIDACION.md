# Validación conocida

El 12 de noviembre de 2026 el estudiante ejecutó Verificar-Etapa6.ps1 y compartió
su salida completa del entorno Docker:

| Comprobación | Resultado informado |
| --- | --- |
| Python | 208 passed, 147 subtests passed |
| Node | 23 pruebas correctas, cero fallos |
| Despliegue | UPDATE_COMPLETE |
| DynamoDB, tres índices y Redis | estado ok |
| Catálogo, ventas e historiales | estado ok |
| Servicio frontend | healthy |
| Proxy web, dos cajas, reenvíos y comprobantes | estado ok |

Las capturas compartidas muestran una venta manual en c01 por 25.500 COP, su
comprobante y aparición en el historial, y otra en c02 por 34.650 COP.
La etapa 4 comprobó lecturas/ventas con Redis detenido y su restauración.

Pendientes: confirmación explícita de la vista previa de impresión, primera
ejecución de CI en GitHub, arranque desde un clon en el equipo de un compañero
y cierre de la etapa 7 (documentación final, evidencias y sustentación).

El script nuevo de arranque y los archivos de colaboración se verifican
separadamente. Los ensayos con Docker sustituido comprueban flujo y propagación
de errores; no equivalen a iniciar servicios reales.

La CI ejecuta pytest, node:test y validación de Compose. Las pruebas aisladas
utilizan moto, fakeredis y mocks. CDK se comprueba con código Lambda inline,
sin desplegar en una cuenta AWS. Una CI correcta complementa la demostración
en LocalStack y no demuestra por sí sola la apariencia de la impresión.
