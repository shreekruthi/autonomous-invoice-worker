function Get-WorkerPython {
    param([string]$Root)
    $candidates = @(
        (Join-Path $Root '.venv\Scripts\python.exe'),
        ([IO.Path]::GetFullPath((Join-Path $Root '..\..\work\.venv\Scripts\python.exe')))
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw 'Install Python 3.11+ and follow the README setup instructions first.'
}
