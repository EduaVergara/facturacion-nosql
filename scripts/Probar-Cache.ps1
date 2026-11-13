[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    & docker compose exec -T cdk-dev python scripts/check_cache.py --mode online
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion inicial de cache; Redis no fue detenido.' }
    $taskRestoreRedis=$false
    try {
        Write-Host 'Deteniendo Redis para comprobar consultas y ventas con DynamoDB...'
        $taskRestoreRedis=$true
        & docker compose stop --timeout 5 redis
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo detener Redis para la prueba.' }
        & docker compose exec -T cdk-dev python scripts/check_cache.py --mode offline
        if ($LASTEXITCODE -ne 0) { throw 'Fallo la prueba de continuidad sin Redis.' }
    }
    finally {
        if ($taskRestoreRedis) {
            Write-Host 'Restaurando Redis...'
            & docker compose up -d --wait --wait-timeout 60 redis
            if ($LASTEXITCODE -ne 0) { throw 'Redis no pudo restaurarse; ejecuta docker compose up -d --wait redis.' }
        }
    }
    & docker compose exec -T cdk-dev python scripts/smoke_check.py
    if ($LASTEXITCODE -ne 0) { throw 'Los servicios no quedaron saludables tras restaurar Redis.' }
    & docker compose exec -T cdk-dev python scripts/check_cache.py --mode recovered
    if ($LASTEXITCODE -ne 0) { throw 'Redis volvio a arrancar pero no se confirmo la cache.' }
    Write-Host 'Cache verificada: hit, miss, TTL, invalidacion y continuidad sin Redis.'
}
finally {
    Pop-Location
}
