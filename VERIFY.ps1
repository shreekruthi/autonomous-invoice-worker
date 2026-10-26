$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\python_path.ps1')
$workerPython = Get-WorkerPython -Root $PSScriptRoot
& $workerPython -m scripts.verify_submission
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Verification is incomplete. See artifacts/submission-check/report.json and the stage logs.'
    exit 1
}
Write-Host 'All final verification stages passed. Keep artifacts/submission-check/report.json.'
