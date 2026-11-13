[CmdletBinding()]
param(
    [string]$ProjectPath = '.'
)

$ErrorActionPreference = 'Stop'
$taskProject = (Resolve-Path -LiteralPath $ProjectPath).Path
$taskChanges = @(
    @{
        RelativePath = 'app\tests\test_infra.py'
        Old = '"TABLE_NAME": "Facturacion"'
        New = '"TABLE_NAME": {"Ref": next(iter(self.template.find_resources("AWS::DynamoDB::Table")))}'
    },
    @{
        RelativePath = 'app\scripts\smoke_check.py'
        Old = 'cache.setex(key, 20, "ok")'
        New = 'cache.set(key, "ok", ex=20)'
    }
)

# Verificar ambos archivos antes de realizar cualquier cambio.
$taskPlans = foreach ($taskChange in $taskChanges) {
    $taskPath = Join-Path $taskProject $taskChange.RelativePath
    if (-not (Test-Path -LiteralPath $taskPath -PathType Leaf)) {
        throw "No existe $taskPath. Ejecuta el script desde la carpeta facturacion-nosql."
    }
    $taskText = [System.IO.File]::ReadAllText($taskPath)
    $taskOldCount = ([regex]::Matches($taskText, [regex]::Escape($taskChange.Old))).Count
    if ($taskOldCount -eq 0 -and $taskText.Contains($taskChange.New)) {
        [pscustomobject]@{Path=$taskPath; Content=$taskText; Change=$false}
    }
    elseif ($taskOldCount -eq 1) {
        [pscustomobject]@{
            Path=$taskPath
            Content=$taskText.Replace($taskChange.Old, $taskChange.New)
            Change=$true
        }
    }
    else {
        throw "El contenido de $taskPath difiere de la version esperada. No se modifico ningun archivo."
    }
}

$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$taskEncoding = New-Object System.Text.UTF8Encoding($false)
foreach ($taskPlan in $taskPlans) {
    if ($taskPlan.Change) {
        Copy-Item -LiteralPath $taskPlan.Path -Destination ($taskPlan.Path + '.bak-' + $taskStamp)
        [System.IO.File]::WriteAllText($taskPlan.Path, $taskPlan.Content, $taskEncoding)
        Write-Host ('Corregido: ' + $taskPlan.Path)
    }
    else {
        Write-Host ('Ya estaba corregido: ' + $taskPlan.Path)
    }
}

Write-Host ''
Write-Host 'Ahora ejecuta desde la carpeta del proyecto:'
Write-Host 'docker compose exec -T cdk-dev python -m pytest tests -q'
Write-Host 'docker compose exec -T cdk-dev python scripts/smoke_check.py'
Write-Host 'No se requiere reconstruir contenedores ni desplegar de nuevo.'
