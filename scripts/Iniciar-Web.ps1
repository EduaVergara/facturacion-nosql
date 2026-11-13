[CmdletBinding()]
param([switch]$CompartirEnRed,[ValidateRange(1024,65535)][int]$Puerto=8080)
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
$taskOldBind=$env:FRONTEND_BIND_ADDRESS
$taskOldPort=$env:FRONTEND_PORT
Push-Location -LiteralPath $taskProject
try {
    $env:FRONTEND_BIND_ADDRESS=if($CompartirEnRed){'0.0.0.0'}else{'127.0.0.1'}
    $env:FRONTEND_PORT=[string]$Puerto
    & docker compose -f docker-compose.yml -f docker-compose.web.yml up -d --no-build --pull never --wait --wait-timeout 60 frontend
    if($LASTEXITCODE -ne 0){throw 'No se pudo iniciar la interfaz. Conserva la salida para revisar.'}
    Write-Host "Caja 1: http://localhost:$Puerto/?caja=c01"
    Write-Host "Caja 2: http://localhost:$Puerto/?caja=c02"
    if($CompartirEnRed){Write-Host "En otros equipos usa http://IP-DEL-COMPUTADOR-CENTRAL:$Puerto/?caja=c02"}
}
finally {
    $env:FRONTEND_BIND_ADDRESS=$taskOldBind
    $env:FRONTEND_PORT=$taskOldPort
    Pop-Location
}
