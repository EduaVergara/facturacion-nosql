[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    Get-Command docker -ErrorAction Stop | Out-Null
    & docker info --format '{{.ServerVersion}}'
    if ($LASTEXITCODE -ne 0) {
        throw 'No hay acceso al motor Docker. Comprueba Docker Desktop desde esta terminal.'
    }
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'La configuracion de Compose no es valida.' }
    & docker compose up -d --build --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'No fue posible levantar todos los servicios.' }
    & docker compose exec -T cdk-dev cdklocal bootstrap aws://000000000000/us-east-1
    if ($LASTEXITCODE -ne 0) { throw 'Fallo bootstrap; revisa los logs del emulador.' }
    & docker compose exec -T cdk-dev cdklocal deploy FacturacionStack --require-approval never --output /tmp/facturacion-cdk.out --outputs-file /app/cdk-outputs.json
    if ($LASTEXITCODE -ne 0) { throw 'Fallo el despliegue local de CDK.' }
    & docker compose exec -T cdk-dev python scripts/publicar_api.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo publicar prod en la API local.' }
    & docker compose exec -T cdk-dev python scripts/smoke_check.py
    if ($LASTEXITCODE -ne 0) { throw 'El despliegue no supero la comprobacion de servicios.' }
    & docker compose exec -T cdk-dev python scripts/seed_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la carga de datos ficticios.' }
    & docker compose exec -T cdk-dev python scripts/check_catalog.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion HTTP del catalogo.' }
    & docker compose exec -T cdk-dev python scripts/check_invoices.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion HTTP de facturas.' }
    & docker compose exec -T cdk-dev python scripts/check_history.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion HTTP de historiales.' }
    & (Join-Path $PSScriptRoot 'Probar-Cache.ps1')
    & docker compose exec -T cdk-dev python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw 'No pasaron todas las pruebas.' }
    Write-Host 'Etapa 5 verificada. Consulta app/cdk-outputs.json para las URLs y el nombre de tabla.'
}
finally {
    Pop-Location
}
