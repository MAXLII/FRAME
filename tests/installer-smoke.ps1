[CmdletBinding()]
param([string]$Installer)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$version=(Get-Content (Join-Path $root 'VERSION') -Encoding UTF8 -Raw).Trim()
if(-not $Installer){$Installer=Join-Path $root "dist/installer/FRAME-Setup-$version.exe"}
$testRoot=Join-Path $root ('build/install-smoke/'+[Guid]::NewGuid().ToString('N'))
$app=Join-Path $testRoot 'app';$data=Join-Path $testRoot 'data'
New-Item -ItemType Directory -Force $app,$data | Out-Null
$installed=Start-Process -FilePath $Installer -ArgumentList @('/FRAMEVALIDATE=1','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',"/DIR=`"$app`"","/LOG=`"$testRoot/install.log`"") -WindowStyle Hidden -PassThru -Wait
if($installed.ExitCode){throw "Installer exited $($installed.ExitCode)"}
$manifest=Get-Content "$app/package-manifest.json" -Encoding UTF8 -Raw | ConvertFrom-Json
foreach($entry in $manifest.files){
    $file=Join-Path $app $entry.path
    if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $entry.sha256){throw "Installed file differs: $($entry.path)"}
}
if(@(Get-ChildItem $app -Recurse -File | Where-Object {$_.Extension -in '.py','.pyc','.pyd'}).Count){throw 'Python payload found'}
$actual=& "$app/frame.exe" --version --json | ConvertFrom-Json
if($LASTEXITCODE -or $actual.version -ne $version){throw 'Installed CLI version failed'}
$ports=& "$app/frame.exe" serial ports --json | ConvertFrom-Json
if($LASTEXITCODE -or -not $ports.ok){throw 'Installed DLL/serial enumeration failed'}
$fixture=Join-Path $PSScriptRoot 'fixtures/parameter-session.json'
$commands=@("connect --replay `"$fixture`"",'param list','param read --name TEST_COUNTER','disconnect')
$result=@(($commands -join "`n") | & "$app/frame.exe" shell --json | ForEach-Object {$_|ConvertFrom-Json})
if($LASTEXITCODE -or $result.Count -ne 4 -or $result[2].data.value -ne 42){throw 'Installed Shell replay failed'}
# Child-only data directory keeps validation out of the user's installed profile.
$start=[Diagnostics.ProcessStartInfo]::new("$app/Frame.Desktop.exe")
$start.UseShellExecute=$false;$start.WorkingDirectory=$data;$start.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden
$start.EnvironmentVariables['FRAME_DATA_DIR']=$data
$ui=[Diagnostics.Process]::Start($start)
try {
    $deadline=[DateTime]::UtcNow.AddSeconds(20)
    do {$ui.Refresh();if($ui.HasExited){throw "Installed WPF exited early ($($ui.ExitCode))"};Start-Sleep -Milliseconds 100} while($ui.MainWindowHandle -eq 0 -and [DateTime]::UtcNow -lt $deadline)
    if($ui.MainWindowHandle -eq 0 -or $ui.MainWindowTitle -ne "FRAME v$version"){throw 'Installed WPF window/version failed'}
} finally {
    if(-not $ui.HasExited){[void]$ui.CloseMainWindow();if(-not $ui.WaitForExit(10000)){throw 'Installed WPF did not close normally'}}
    $ui.Dispose()
}
if(-not(Test-Path "$data/config/native-ui.json")){throw 'Installed settings were not saved in the selected data directory'}
if(Test-Path "$app/config/native-ui.json"){throw 'Installed application wrote settings into its program directory'}
Write-Host "PASS: installer extraction, file hashes, self-contained CLI/DLL, Shell replay, WPF version/close and isolated data directory ($version)."
Write-Host "Evidence: $testRoot"
