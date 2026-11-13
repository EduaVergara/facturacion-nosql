[CmdletBinding()]
param([switch]$CompartirEnRed,[ValidateRange(1024,65535)][int]$Puerto=8080)
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    & docker compose ps
    if($LASTEXITCODE -ne 0){throw 'No se pudo consultar Docker.'}
    Write-Host 'Ejecutando pruebas Python antes de modificar el despliegue...'
    & docker compose exec -T cdk-dev python -m pytest tests -q
    if($LASTEXITCODE -ne 0){throw 'Hay pruebas pendientes; no se desplego la etapa 6.'}
    Write-Host 'Ejecutando pruebas de la terminal con la imagen existente...'
    & docker compose -f docker-compose.yml -f docker-compose.web.yml run --rm --no-deps --pull never frontend node --test /frontend/test/domain.test.mjs /frontend/test/api.test.mjs
    if($LASTEXITCODE -ne 0){throw 'Hay pruebas pendientes en la terminal; no se desplego la etapa 6.'}
    & docker compose exec -T cdk-dev python scripts/preparar_etapa3.py
    if($LASTEXITCODE -ne 0){throw 'No se pudo respaldar y preparar la actualizacion.'}
    & docker compose exec -T cdk-dev cdklocal deploy FacturacionStack --require-approval never --output /tmp/facturacion-cdk.out --outputs-file /app/cdk-outputs.json
    if($LASTEXITCODE -ne 0){throw 'No se pudo actualizar el stack local.'}
    & docker compose exec -T cdk-dev python scripts/publicar_api.py
    if($LASTEXITCODE -ne 0){throw 'No se pudo publicar prod.'}
    foreach($taskCheck in @('seed_demo.py','smoke_check.py','check_catalog.py','check_invoices.py','check_history.py')){
        & docker compose exec -T cdk-dev python "scripts/$taskCheck"
        if($LASTEXITCODE -ne 0){throw "Fallo la comprobacion $taskCheck; conserva la salida para revisar."}
    }
    & (Join-Path $PSScriptRoot 'Iniciar-Web.ps1') -Puerto $Puerto -CompartirEnRed:$CompartirEnRed
    & docker compose exec -T cdk-dev python scripts/check_frontend.py
    if($LASTEXITCODE -ne 0){throw 'Fallo la comprobacion HTTP de la interfaz y sus dos cajas.'}
    Write-Host 'Etapa 6 verificada automaticamente: servidor web, API y dos cajas. Abre ambas URLs y realiza la revision visual de ETAPA6.md.'
}
finally {Pop-Location}
