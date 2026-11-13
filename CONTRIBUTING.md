# Colaborar en Folio

Trabajamos sobre la etapa 6 funcional del proyecto académico. El cierre de
documentación y sustentación de la etapa 7 sigue pendiente. Antes de cambiar
código, lee el [README](README.md) y la [arquitectura](docs/ARQUITECTURA.md).

## Preparar un cambio

Con acceso al repositorio, clónalo y arráncalo según el README. Cada compañero
utiliza su propio entorno Docker y datos ficticios. Desde la raíz del proyecto:

```powershell
git switch main
git pull --ff-only
git switch -c mejora/descripcion-breve
```

Realiza un cambio con alcance concreto. Describe primero el problema en un
issue si afecta contratos, claves, índices o reglas de facturación.

## Comprobar

Con los contenedores iniciados:

```powershell
docker compose exec -T cdk-dev python -m pytest tests -q
docker compose -f docker-compose.yml -f docker-compose.web.yml run --rm --no-deps --pull never frontend node --test /frontend/test/domain.test.mjs /frontend/test/api.test.mjs
```

Si cambia infraestructura o Lambdas en el entorno recuperado del equipo,
ejecuta `scripts/Verificar-Etapa6.ps1`. Un clon nuevo utiliza
`scripts/Iniciar-Proyecto.ps1`. Las comprobaciones HTTP crean ventas ficticias.
Los resultados unitarios por sí solos no comprueban un despliegue en LocalStack.

## Enviar para revisión

Revisa `git diff` y agrega únicamente los archivos del cambio:

```powershell
git add ruta/al/archivo
git commit -m "Describe el comportamiento que cambia"
git push -u origin mejora/descripcion-breve
```

En GitHub abre un pull request hacia `main` y completa la plantilla. Espera el
resultado de Pruebas y la revisión de un compañero antes de integrar. Si no
tienes permiso de escritura, utiliza una copia mediante fork y un pull request.
El equipo acuerda los permisos y las reglas de integración en GitHub.

## Reglas del dominio

- Los precios, impuestos, fecha y totales definitivos se calculan en el servidor.
- Una venta incierta conserva `solicitud_id` y el cuerpo exacto para reintentar.
- Una factura emitida conserva sus datos históricos y no se edita ni elimina
  desde la API del negocio.
- Los historiales usan Query y los índices definidos. El Scan de administración
  de respaldos no se utiliza como consulta habitual de las ventas.
- Redis acelera lecturas y puede fallar sin impedir la venta en DynamoDB.
- Las claves, índices y cursores forman parte del contrato: documenta y prueba
  cualquier cambio que los afecte.

Publica ejemplos y capturas con datos ficticios. `.env`, las salidas CDK, la
configuración del stack y los respaldos pertenecen a cada entorno local.

## Procedencia

El proyecto utiliza el stack académico del
[profesor](https://gitlab.com/caov_unimag/bd_no_sql). Conserva su atribución y las
referencias. Este paquete no agrega una licencia de terceros ni cambia los
permisos de materiales del curso.
