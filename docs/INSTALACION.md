# Instalación y operación

## Windows

Necesitas Git y Docker Desktop con contenedores Linux, Compose y el motor
iniciado. Normalmente se utilizan 4566 para LocalStack y 8080 para Folio.
Desde un clon nuevo ejecuta:

```powershell
.\scripts\Iniciar-Proyecto.ps1
```

Si falta .env se copia .env.example. El script construye el entorno, ejecuta
bootstrap, despliega, publica prod, crea datos ficticios y comprueba API/caché.
Después prueba e inicia la web. La primera construcción descarga dependencias.

Un clon nuevo no copia local-config.json, cdk-outputs.json ni respaldos de otro
equipo. CDK genera sus propias salidas. Una configuración local recuperada ya
existente se conserva y se utiliza mediante Verificar-Etapa6.

## Linux/macOS · clon nuevo

Con Docker y Compose iniciados, desde la raíz:

```bash
cp .env.example .env
docker compose up -d --build --wait --wait-timeout 180
docker compose exec -T cdk-dev python -m pytest tests -q
docker compose exec -T cdk-dev cdklocal bootstrap aws://000000000000/us-east-1
docker compose exec -T cdk-dev cdklocal deploy FacturacionStack --require-approval never --output /tmp/facturacion-cdk.out --outputs-file /app/cdk-outputs.json
docker compose exec -T cdk-dev python scripts/publicar_api.py
docker compose exec -T cdk-dev python scripts/seed_demo.py
docker compose exec -T cdk-dev python scripts/smoke_check.py
docker compose exec -T cdk-dev python scripts/check_catalog.py
docker compose exec -T cdk-dev python scripts/check_invoices.py
docker compose exec -T cdk-dev python scripts/check_history.py
docker compose -f docker-compose.yml -f docker-compose.web.yml run --rm --no-deps --pull never frontend node --test /frontend/test/domain.test.mjs /frontend/test/api.test.mjs
docker compose -f docker-compose.yml -f docker-compose.web.yml up -d --no-build --pull never --wait --wait-timeout 60 frontend
docker compose exec -T cdk-dev python scripts/check_frontend.py
```

Comprueba cada resultado antes de continuar. La prueba de detener/restaurar Redis
está automatizada en Probar-Cache.ps1 para PowerShell. La ruta manual Linux/macOS
queda por comprobar en un equipo de ese sistema.

## Arranque posterior

Para iniciar contenedores existentes:

```powershell
docker compose up -d --wait --wait-timeout 180
.\scripts\Iniciar-Web.ps1
```

Después de reiniciar/recrear LocalStack comprueba /api/health; un volumen por sí
solo no garantiza restaurar el estado del emulador. Conserva respaldos antes de
actualizar y consulta RECUPERACION_API.md ante rollback. No elimines volúmenes
como parte de un arranque.

Puedes usar `Iniciar-Proyecto.ps1 -Puerto 8081` o
`Iniciar-Web.ps1 -CompartirEnRed`. En la LAN abre
`http://IP-DEL-SERVIDOR:8080/?caja=c02`. El cliente solo necesita navegador.
El script no modifica firewall ni agrega autenticación.

## Datos y diagnóstico

Los seeds conservan registros existentes. Las comprobaciones crean ventas
ficticias e informan sus cantidades e identificadores. El historial de prueba
reutiliza solicitudes mientras exista su contexto local.

Cada caja conserva borrador y solicitud pendiente en el almacenamiento del
navegador, asociado al origen. Usa una pestaña por caja. Ante una confirmación
incierta conserva el estado y reintenta la misma solicitud.

| Síntoma | Acción |
| --- | --- |
| Docker no responde | Esperar el inicio del motor de Docker Desktop |
| No existe la imagen cdk-dev | Ejecutar Iniciar-Proyecto para construirla |
| Puerto 8080 ocupado | Utilizar -Puerto 8081 |
| Stage already exists / rollback | Conservar la salida y consultar RECUPERACION_API.md |
| Redis no disponible | Revisar Diagnóstico; DynamoDB permite continuar |
| Producto desactualizado | Revisar el carrito con la respuesta del servidor |
| cdklocal obsoleto | Se conserva el CLI probado del curso; el aviso no implica por sí solo un fallo |

```powershell
docker compose -f docker-compose.yml -f docker-compose.web.yml ps
docker compose -f docker-compose.yml -f docker-compose.web.yml logs --tail 80 frontend
```
