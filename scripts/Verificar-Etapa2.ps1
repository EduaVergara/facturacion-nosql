[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    & docker compose ps
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar el entorno Docker.' }
    # El empaquetado pesado ocurre en Linux; solo las salidas pequenas van a Windows.
    & docker compose exec -T cdk-dev cdklocal deploy FacturacionStack --require-approval never --output /tmp/facturacion-cdk.out --outputs-file /app/cdk-outputs.json
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar el stack local.' }
    & docker compose exec -T cdk-dev python scripts/publicar_api.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo publicar la etapa prod del API local.' }
    & docker compose exec -T cdk-dev python scripts/seed_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron cargar los datos de demostracion.' }
    & docker compose exec -T cdk-dev python scripts/smoke_check.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion de infraestructura.' }
    & docker compose exec -T cdk-dev python scripts/check_catalog.py
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion HTTP del catalogo.' }
    & docker compose exec -T cdk-dev python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Hay pruebas pendientes de corregir.' }
    Write-Host 'Etapa 2 verificada: productos, clientes y cajas disponibles.'
}
finally {
    Pop-Location
}
