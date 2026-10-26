param(
    [ValidateSet('groq', 'demo', 'openai')][string]$Mode = 'groq',
    [ValidateRange(1024, 65535)][int]$Port = 8001,
    [switch]$Fresh,
    [switch]$Faults
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\python_path.ps1')
$workerPython = Get-WorkerPython -Root $PSScriptRoot
$env:WORKER_MODE = $Mode
$env:ENABLE_FAULTS = if ($Faults) { 'true' } else { 'false' }
if ($Fresh) {
    $runStamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
    $runSuffix = [Guid]::NewGuid().ToString('N').Substring(0, 6)
    $env:WORKER_DB = "data/submission-$Mode-$runStamp-$runSuffix.sqlite3"
    Write-Host "New sandbox database: $env:WORKER_DB"
}
Write-Host "Open http://127.0.0.1:$Port ; mode: $Mode ; fault injection: $Faults"
Write-Host 'Keep this window open. Stop the server with Ctrl+C.'
& $workerPython -m uvicorn worker.api:create_app --factory --host 127.0.0.1 --port $Port --workers 1
exit $LASTEXITCODE
