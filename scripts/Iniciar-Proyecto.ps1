[CmdletBinding()]
param([switch]$CompartirEnRed,[ValidateRange(1024,65535)][int]$Puerto=8080)
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    if(-not (Test-Path -LiteralPath '.env' -PathType Leaf)){
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
    }
    if(Test-Path -LiteralPath 'app/local-config.json' -PathType Leaf){
        Write-Host 'Configuracion local existente: se conserva y se usa la verificacion de etapa 6.'
        & (Join-Path $PSScriptRoot 'Verificar-Etapa6.ps1') -Puerto $Puerto -CompartirEnRed:$CompartirEnRed
    }
    else {
        Write-Host 'Preparando el entorno desde el codigo clonado...'
        & (Join-Path $PSScriptRoot 'Iniciar-Local.ps1')
        & docker compose -f docker-compose.yml -f docker-compose.web.yml run --rm --no-deps --pull never frontend node --test /frontend/test/domain.test.mjs /frontend/test/api.test.mjs
        if($LASTEXITCODE -ne 0){throw 'Fallo una prueba de la terminal web.'}
        & (Join-Path $PSScriptRoot 'Iniciar-Web.ps1') -Puerto $Puerto -CompartirEnRed:$CompartirEnRed
        & docker compose exec -T cdk-dev python scripts/check_frontend.py
        if($LASTEXITCODE -ne 0){throw 'Fallo la comprobacion del servidor web.'}
    }
    Write-Host "Folio listo. Caja 1: http://localhost:$Puerto/?caja=c01"
    Write-Host "Caja 2: http://localhost:$Puerto/?caja=c02"
}
finally {Pop-Location}
