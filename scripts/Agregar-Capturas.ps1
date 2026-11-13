[CmdletBinding()]
param([string]$PuntoVentaPath,[string]$HistorialPath,[string]$ComprobantePath)
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
$taskReadme=Join-Path $taskProject 'README.md'
$taskText=[System.IO.File]::ReadAllText($taskReadme)
$taskStart='<!-- CAPTURAS:INICIO -->';$taskEnd='<!-- CAPTURAS:FIN -->'
$taskBegin=$taskText.IndexOf($taskStart);$taskFinish=$taskText.IndexOf($taskEnd)
if($taskBegin -lt 0 -or $taskFinish -le $taskBegin){throw 'El README no contiene una seccion de capturas reconocida.'}
$taskInputs=@(
    @{Path=$PuntoVentaPath;Name='punto-venta.png';Label='Punto de venta'},
    @{Path=$HistorialPath;Name='historial.png';Label='Historial de ventas'},
    @{Path=$ComprobantePath;Name='comprobante.png';Label='Comprobante academico'}
)
$taskPlans=@(foreach($taskInput in $taskInputs){
    if(-not $taskInput.Path){continue}
    $taskSource=(Resolve-Path -LiteralPath $taskInput.Path).Path
    $taskBytes=[System.IO.File]::ReadAllBytes($taskSource)
    if($taskBytes.Length -lt 8 -or [System.BitConverter]::ToString($taskBytes,0,8) -ne '89-50-4E-47-0D-0A-1A-0A'){
        throw "El archivo no es PNG: $taskSource"
    }
    [pscustomobject]@{Name=$taskInput.Name;Bytes=$taskBytes}
})
if(-not $taskPlans.Count){throw 'Indica al menos una ruta de captura PNG.'}
$taskDirectory=Join-Path $taskProject 'docs\capturas'
$taskBackup=Join-Path $taskProject ('.actualizaciones\capturas-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $taskDirectory -Force|Out-Null
New-Item -ItemType Directory -Path $taskBackup -Force|Out-Null
Copy-Item -LiteralPath $taskReadme -Destination (Join-Path $taskBackup 'README.md')
foreach($taskPlan in $taskPlans){
    $taskTarget=Join-Path $taskDirectory $taskPlan.Name
    if(Test-Path -LiteralPath $taskTarget -PathType Leaf){Copy-Item -LiteralPath $taskTarget -Destination (Join-Path $taskBackup $taskPlan.Name)}
    [System.IO.File]::WriteAllBytes($taskTarget,$taskPlan.Bytes)
}
$taskLines=@($taskStart)
foreach($taskInput in $taskInputs){
    if(Test-Path -LiteralPath (Join-Path $taskDirectory $taskInput.Name) -PathType Leaf){
        $taskLines+="`n### $($taskInput.Label)`n`n![$($taskInput.Label)](docs/capturas/$($taskInput.Name))`n"
    }
}
$taskLines+=$taskEnd
$taskUpdated=$taskText.Substring(0,$taskBegin)+($taskLines -join "`n")+$taskText.Substring($taskFinish+$taskEnd.Length)
[System.IO.File]::WriteAllText($taskReadme,$taskUpdated,[System.Text.UTF8Encoding]::new($false))
Write-Host 'Capturas copiadas sin alterar pixeles y README actualizado. Revisa las imagenes antes de publicarlas.'
