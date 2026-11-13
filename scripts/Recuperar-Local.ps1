[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskProject
try {
    & docker compose exec -T cdk-dev python scripts/recuperar_stack.py
    if ($LASTEXITCODE -ne 0) { throw 'La recuperacion no se preparo; revisa el diagnostico anterior.' }
    & (Join-Path $PSScriptRoot 'Verificar-Etapa2.ps1')
}
finally {
    Pop-Location
}
