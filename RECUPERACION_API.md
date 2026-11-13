# Recuperación de la API local

El stack original quedó en ROLLBACK_COMPLETE al intentar actualizar prod mediante
AWS::ApiGateway::Stage en LocalStack 4.14. La tabla Facturacion continúa ACTIVE,
pero la API no tiene etapas publicadas. Esta corrección conserva la tabla y no
elimina el stack original, las tablas, los contenedores ni los volúmenes.

## Aplicación

Extrae el paquete en una carpeta de actualización y ejecuta Aplicar-Recuperacion.ps1
desde esa carpeta. El script necesita la carpeta facturacion-nosql que viene junto
a él. Respalda los archivos sustituidos en .actualizaciones dentro de tu proyecto.

Después, desde C:\Users\eduve\Desktop\facturacion-nosql:

```powershell
.\scripts\Recuperar-Local.ps1
```

La recuperación hace lo siguiente:

1. Comprueba el esquema y estado de Facturacion, exporta todos sus registros y
   verifica el número de registros de la copia en app/backups/recuperacion-... .
   Esta exportación administrativa usa Scan paginado; las rutas de negocio
   siguen consultando por clave o Query.
2. Guarda app/local-config.json para reutilizar esa tabla desde un stack nuevo
   de servicios llamado FacturacionServiciosStack. No vuelve a crear la tabla.
3. Despliega la API y las Lambdas mediante CDK. El snapshot de API se genera
   después de sus métodos y cambia cuando cambia la infraestructura.
4. Publica o actualiza prod mediante el SDK de API Gateway, después del deploy,
   para evitar el proveedor Stage de CloudFormation que ocasionó el conflicto.
5. Carga los datos ficticios sin sobrescribir existentes, comprueba las rutas
   y ejecuta las pruebas.

El stack original puede continuar apareciendo en ROLLBACK_COMPLETE: se conserva
para no alterar sus recursos. El stack activo de servicios figura en las nuevas
salidas CDK como ActiveStackName. Si un intento de crear ese stack también falló,
la preparación elige un nombre con fecha y conserva igualmente el intento anterior.
No se intenta modificar un stack cuya operación siga en progreso.

El archivo app/cdk-outputs.json se actualiza con el nuevo API ID. Las comprobaciones
incluidas admiten ambos nombres de stack. Una referencia manual al API anterior
deberá cambiarse por el nuevo ID. Para ver las nuevas salidas desde PowerShell:

```powershell
$salidas=Get-Content .\app\cdk-outputs.json -Raw | ConvertFrom-Json
$salidas.PSObject.Properties.Value
```

## Alcance y verificación

Se conserva el diseño de datos y los tres índices. La referencia a la tabla
existente es una importación en el código CDK, no una migración de los registros.
Un arranque nuevo sin local-config.json sigue creando la tabla mediante CDK.
Esta variante de publicación de prod es una adaptación al emulador local.

Las pruebas aisladas del respaldo, la configuración y la publicación se ejecutan
con dobles de servicios. La verificación completa de CDK, API Gateway y DynamoDB
debe ejecutarse en tu contenedor; no se presenta esta recuperación como ya
desplegada en tu equipo.

Para las siguientes actualizaciones se usa scripts/Verificar-Etapa2.ps1, que ya
incluye el paso de publicación. No es necesario repetir Recuperar-Local si la
versión de servicios queda desplegada y operativa.

Referencias:

- Limitaciones de actualización de CDK en LocalStack:
  https://docs.localstack.cloud/aws/connecting/infrastructure-as-code/aws-cdk/
- Deployment y dependencias de métodos:
  https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_apigateway/Deployment.html
- Actualización de una etapa por SDK:
  https://docs.aws.amazon.com/apigateway/latest/api/API_UpdateStage.html
- Referencia CDK a una tabla existente:
  https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_dynamodb/TableAttributes.html
