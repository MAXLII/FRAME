param([int]$Seconds=7200,[string]$EvidenceName='soak')
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
$folder=Join-Path $frameRoot "build/$EvidenceName-app"
New-Item -ItemType Directory -Force $folder | Out-Null
Get-ChildItem (Join-Path $frameRoot 'build/app') -File | Copy-Item -Destination $folder
$fixture=Join-Path $PSScriptRoot 'fixtures/wave-periodic.json'
$output=Join-Path $frameRoot "build/$EvidenceName-result.json"
$errorOutput=Join-Path $frameRoot "build/$EvidenceName-stderr.log"
$process=Start-Process -FilePath (Join-Path $folder 'frame.exe') -ArgumentList @('wave','capture','--replay',('"'+$fixture+'"'),'--duration',"$Seconds",'--json') -WindowStyle Hidden -PassThru -RedirectStandardOutput $output -RedirectStandardError $errorOutput
$watch=[System.Diagnostics.Stopwatch]::StartNew()
$peak=0L
while(-not $process.HasExited){
    $process.Refresh()
    $peak=[Math]::Max($peak,$process.WorkingSet64)
    if($peak -gt 512MB){$process.Kill();throw 'Soak exceeded 512 MiB working set'}
    Start-Sleep -Seconds 10
}
$process.WaitForExit()
$result=Get-Content -Encoding UTF8 $output -Raw | ConvertFrom-Json
$total=[long]$result.data.count+[long]$result.data.dropped
$rate=$total/[Math]::Max(1,$Seconds)
$passed=$rate -ge 1552 -and $rate -le 1648 -and $result.ok -and $result.data.stop_confirmed -and $result.data.count -le 100000 -and $watch.Elapsed.TotalSeconds -ge $Seconds
[pscustomobject]@{Passed=$passed;TotalRecords=$total;RecordsPerSecond=$rate;BackendSha256=(Get-FileHash (Join-Path $folder 'frame_backend.dll')).Hash;DurationSeconds=$watch.Elapsed.TotalSeconds;PeakWorkingSetBytes=$peak;Result=$result} | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $frameRoot "build/$EvidenceName-report.json")
if(-not $passed){throw 'Soak failed'}
'PASS: continuous 16-channel replay, bounded history, completion and stop ACK'
