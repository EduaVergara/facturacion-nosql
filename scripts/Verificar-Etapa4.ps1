[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    & docker compose ps
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Docker.' }
    Write-Host 'Ejecutando pruebas antes de modificar el despliegue...'
    & docker compose exec -T cdk-dev python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Hay pruebas pendientes; no se desplego la etapa 4.' }
    & docker compose exec -T cdk-dev python scripts/preparar_etapa3.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo respaldar y preparar la actualizacion.' }
    & docker compose exec -T cdk-dev cdklocal deploy FacturacionStack --require-approval never --output /tmp/facturacion-cdk.out --outputs-file /app/cdk-outputs.json
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar el stack local.' }
    & docker compose exec -T cdk-dev python scripts/publicar_api.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo publicar prod.' }
    & docker compose exec -T cdk-dev python scripts/seed_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron cargar los datos ficticios.' }
    & docker compose exec -T cdk-dev python scripts/smoke_check.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion de infraestructura.' }
    & docker compose exec -T cdk-dev python scripts/check_catalog.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion del catalogo.' }
    & docker compose exec -T cdk-dev python scripts/check_invoices.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion de facturas.' }
    & (Join-Path $PSScriptRoot 'Probar-Cache.ps1')
    Write-Host 'Etapa 4 verificada: cache de productos y facturas, TTL, invalidacion y continuidad sin Redis.'
}
finally {
    Pop-Location
}
