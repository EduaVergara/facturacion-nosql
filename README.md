# Folio · Facturación NoSQL

Sistema académico de ventas centralizadas: varias cajas registran compras desde
el navegador y un servidor local conserva cada factura completa en DynamoDB.
Redis acelera las consultas repetidas sin sustituir la persistencia de las ventas.

**Bases de Datos NoSQL · Universidad del Magdalena.** Etapa 6 funcional;
documentación final y sustentación de la etapa 7 pendientes. Prototipo académico,
sin autorización fiscal ni integración DIAN.

[Instalación](docs/INSTALACION.md) · [Arquitectura](docs/ARQUITECTURA.md) ·
[API](docs/API.md) · [Validación](docs/VALIDACION.md) · [Colaborar](CONTRIBUTING.md)

## Funcionalidades

- Ventas desde dos cajas con carritos independientes.
- Creación y actualización de productos y clientes.
- Precios, impuestos y totales definitivos calculados en el servidor.
- Reintentos de una misma venta sin crear facturas duplicadas.
- Historial por cliente, caja o día de Colombia, con paginación.
- Comprobantes históricos e impresión desde el navegador.
- Diagnóstico de servicios y procedencia de las consultas de caché.

## Tecnologías

| Componente | Implementación |
| --- | --- |
| Persistencia | DynamoDB, Single Table Design, PK/SK y tres GSI |
| Caché | Redis 7, Cache-Aside |
| Backend | Python 3.11, Lambda y API Gateway REST |
| Infraestructura | AWS CDK con Python |
| Entorno local | Docker Compose y LocalStack 4.14 |
| Interfaz | HTML, CSS y JavaScript con módulos; sin dependencias npm |
| Pruebas | pytest, moto, fakeredis y node:test |

## Inicio rápido en Windows

Necesitas Git y Docker Desktop funcionando con contenedores Linux. Python,
Node y CDK se instalan en Docker; no necesitas una cuenta AWS. La primera
construcción requiere Internet y puede tardar varios minutos.

Copia la URL **Code → HTTPS** de este repositorio. En PowerShell:

```powershell
$urlRepositorio = Read-Host "Pega la URL HTTPS de este repositorio"
git clone $urlRepositorio facturacion-nosql
cd facturacion-nosql
.\scripts\Iniciar-Proyecto.ps1
```

El script prepara el entorno, despliega la API, carga datos ficticios, comprueba
el sistema e inicia la web. Si ya existe una configuración local recuperada,
la conserva y utiliza la verificación de etapa 6.

Abre [Caja 1](http://localhost:8080/?caja=c01) y
[Caja 2](http://localhost:8080/?caja=c02). Escribe un operador, selecciona un
cliente, agrega productos y confirma. El operador es un nombre declarado;
este prototipo no tiene inicio de sesión.

Cada clon tiene su propio entorno y datos. El repositorio no transporta la base
de datos del autor. Consulta [instalación](docs/INSTALACION.md) para Linux/macOS,
puertos alternativos, arranque posterior y recuperación del emulador.

## Organización

| Ruta | Contenido |
| --- | --- |
| app/infra/ | CDK, tabla e índices |
| app/lambdas/catalogo/ | Productos, clientes y cajas |
| app/lambdas/facturacion/ | Ventas, idempotencia e historiales |
| app/lambdas/cache_layer.py | Lecturas con Cache-Aside |
| app/lambdas/health/ | Estado de los servicios |
| app/scripts/ | Seeds, verificaciones y servidor web |
| app/tests/ | Pruebas de dominio, repositorios, caché e infraestructura |
| frontend/ | Interfaz y pruebas de la terminal |
| scripts/ | Arranque y verificaciones con PowerShell |
| docs/ | Documentación de uso y colaboración |
| .github/ | Integración continua y plantillas |

Los archivos ETAPA4.md, ETAPA5.md, ETAPA6.md y RECUPERACION_API.md conservan notas
del desarrollo por etapas. Para arrancar desde GitHub utiliza este README.

## Persistencia y caché

La tabla **Facturacion** contiene productos, clientes, cajas, facturas y
solicitudes. Cada factura guarda una copia histórica del cliente y de las líneas
vendidas; los cambios posteriores en los maestros no alteran esa compra.

Los historiales consultan GSI1 por cliente, GSI2 por caja y GSI3 por día.
Cache-Aside conserva detalles de productos durante **60 segundos** y facturas
durante **300 segundos**. Una actualización de producto invalida su copia.
La confirmación de una venta verifica DynamoDB directamente. Redis puede fallar
sin impedir que el sistema consulte o registre ventas en la base principal.

## Pruebas

Con los contenedores iniciados, desde la raíz:

```powershell
docker compose exec -T cdk-dev python -m pytest tests -q
docker compose -f docker-compose.yml -f docker-compose.web.yml run --rm --no-deps --pull never frontend node --test /frontend/test/domain.test.mjs /frontend/test/api.test.mjs
```

La [CI](.github/workflows/ci.yml) ejecuta las pruebas Python y Node y valida
Compose en cada push y pull request. Su primer resultado se conocerá al subir
el código. No despliega en AWS ni sustituye la demostración con LocalStack.

La etapa 6 se verificó en Docker con **208 pruebas Python, 147 subpruebas y
23 pruebas Node**, además de comprobaciones HTTP de dos cajas, reintentos,
comprobantes e historial. [Resultados y pendientes](docs/VALIDACION.md).

## Capturas

<!-- CAPTURAS:INICIO -->
Puedes incorporar las capturas originales de la demostración con el
[comando de importación](docs/CAPTURAS.md). Esta preparación no incluye imágenes
descargadas ni utiliza vistas simuladas como evidencia.
<!-- CAPTURAS:FIN -->

## Colaborar

Trabaja en una rama y envía un pull request hacia `main`. La guía
[CONTRIBUTING.md](CONTRIBUTING.md) explica cómo comprobar y proponer cambios.
Para la primera publicación consulta [Publicar en GitHub](docs/PUBLICAR_GITHUB.md).

## Alcance académico

Los comprobantes y tasas son de demostración. No se implementan autorización
fiscal, inventario, pagos, autenticación ni permisos de usuarios de producción.
La API no ofrece edición o borrado de facturas emitidas. Utiliza datos ficticios
en ejemplos, pruebas y capturas.

## Procedencia

El stack y enfoque académico parten de
[bd_no_sql del profesor Carlos Oliveros](https://gitlab.com/caov_unimag/bd_no_sql).
Folio adapta ese entorno al dominio de facturación y agrega interfaz,
transacciones, idempotencia, historiales, pruebas y operación por etapas.

Referencias: [DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html),
[AWS CDK](https://docs.aws.amazon.com/cdk/api/v2/python/) y
[Redis](https://redis.io/docs/latest/).

Esta preparación no asigna una licencia nueva al código ni a los materiales del
curso. Conserva las atribuciones del proyecto base.
