$ErrorActionPreference = "Stop"

$frameRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $frameRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    & $venvPython (Join-Path $frameRoot "main.py") @args
} else {
    & python (Join-Path $frameRoot "main.py") @args
}

exit $LASTEXITCODE
