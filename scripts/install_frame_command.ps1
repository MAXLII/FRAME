$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRootText = $repoRoot.Path.TrimEnd("\")
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")

$parts = @()
if ($currentPath) {
    $parts = $currentPath -split ";" | Where-Object { $_ -ne "" }
}

$alreadyExists = $false
foreach ($part in $parts) {
    if ($part.TrimEnd("\") -ieq $repoRootText) {
        $alreadyExists = $true
        break
    }
}

if (-not $alreadyExists) {
    $newPath = (($parts + $repoRootText) -join ";")
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Added to user PATH: $repoRootText"
    Write-Host "Open a new PowerShell window, then run: frame serial ports"
} else {
    Write-Host "Already in user PATH: $repoRootText"
}

Write-Host "This PowerShell session can use it now with:"
Write-Host "  .\frame serial ports"
