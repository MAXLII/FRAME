$ErrorActionPreference='Stop'
$frameRoot=Split-Path -Parent $MyInvocation.MyCommand.Path
$frameArgs=@($args)
$program=Join-Path $frameRoot 'build/app/frame.exe'
if($frameArgs.Count -gt 0 -and $frameArgs[0] -eq 'gui'){
    $program=Join-Path $frameRoot 'build/app/Frame.Desktop.exe'
    if(-not(Test-Path -LiteralPath $program)){throw 'Run ./scripts/build.ps1 first'}
    Start-Process -FilePath $program -WorkingDirectory $frameRoot
    exit 0
}
if(-not(Test-Path -LiteralPath $program)){throw 'Run ./scripts/build.ps1 -CliOnly first'}
& $program @frameArgs
exit $LASTEXITCODE
