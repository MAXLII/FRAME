param([Parameter(Mandatory)][string]$Port,[int]$Seconds=1800,[string]$EvidenceName='e507-shell')
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
$folder=Join-Path $frameRoot 'build/integration-app'
New-Item -ItemType Directory -Force $folder | Out-Null
Get-ChildItem (Join-Path $frameRoot 'build/app') -File | Copy-Item -Destination $folder
$log=Join-Path $frameRoot "build/$EvidenceName-integration.ndjson"
$writer=[IO.StreamWriter]::new($log,$false,[Text.UTF8Encoding]::new($false));$writer.AutoFlush=$true
$info=[Diagnostics.ProcessStartInfo]::new()
$info.FileName=Join-Path $folder 'frame.exe';$info.Arguments='shell';$info.WorkingDirectory=$frameRoot
$info.UseShellExecute=$false;$info.CreateNoWindow=$true
$info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
$process=[Diagnostics.Process]::Start($info);$errors=$process.StandardError.ReadToEndAsync()
function Invoke-FrameShell([string]$Command){
    $process.StandardInput.WriteLine($Command);$process.StandardInput.Flush()
    $read=$process.StandardOutput.ReadLineAsync()
    if(-not $read.Wait(20000)){throw "Shell response timeout: $Command"}
    if($null -eq $read.Result){throw "Shell exited: $($errors.Result)"}
    $result=$read.Result|ConvertFrom-Json
    $writer.WriteLine(([ordered]@{time=(Get-Date).ToString('o');command=$Command;result=$result}|ConvertTo-Json -Depth 10 -Compress))
    if($result.PSObject.Properties['ok'] -and -not $result.ok){throw "Command failed: $Command $($result.error)"}
    return $result
}
$elapsed=[Diagnostics.Stopwatch]::StartNew();$iterations=0;$passed=$false;$waveId=0
try{
    Invoke-FrameShell "connect --port $Port --record build/e507-integration-wire.ndjson --json"|Out-Null
    Invoke-FrameShell 'param report --name DEMO_SHELL_COUNTER --enable on --json'|Out-Null
    $wave=Invoke-FrameShell "wave capture --duration $($Seconds+30) --output build/e507-long-wave.json --background --json";$waveId=$wave.job_id
    $elf='D:/OneDrive/LWX/GD32/base/platform/gd32e507/build/gd32e507_demo.elf'
    Invoke-FrameShell "jlink read --elf `"$elf`" --name s_demo_shell_counter --json"|Out-Null
    while($elapsed.Elapsed.TotalSeconds -lt $Seconds){
        $counter=Invoke-FrameShell 'param read --name DEMO_SHELL_COUNTER --json'
        if($counter.data.value -ne 0){throw 'Diagnostic counter changed unexpectedly'}
        if($iterations%30 -eq 0){$perf=Invoke-FrameShell 'perf samples --json';if($perf.data.Count -ne 31){throw 'Incomplete Perf samples'}}
        if($iterations%60 -eq 0){Invoke-FrameShell 'jlink read --name s_demo_shell_counter --json'|Out-Null}
        $iterations++;Start-Sleep -Milliseconds 1000
    }
    Invoke-FrameShell "cancel --id $waveId --json"|Out-Null
    Start-Sleep -Milliseconds 300
    Invoke-FrameShell "data export --dataset $waveId --output build/e507-long-wave.json --json"|Out-Null
    # A cancelled dataset deliberately returns partial-completion code 6 on read.
    # Inspect the exported evidence without causing fail-fast Shell termination.
    $data=Get-Content (Join-Path $frameRoot 'build/e507-long-wave.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    if(-not $data.stop_confirmed -or $data.records.Count -lt 100){throw 'Waveform completion evidence missing'}
    Invoke-FrameShell 'param report --name DEMO_SHELL_COUNTER --enable off --json'|Out-Null
    Invoke-FrameShell 'disconnect --json'|Out-Null
    $process.StandardInput.WriteLine('exit');$process.StandardInput.Flush()
    if(-not $process.WaitForExit(5000)){throw 'Shell did not close'}
    if($process.ExitCode -ne 0){throw 'Shell exit failed'}
    $passed=$true
}finally{
    if(-not $process.HasExited){$process.StandardInput.WriteLine('exit');$process.StandardInput.Flush();if(-not $process.WaitForExit(5000)){$process.Kill()}}
    if(-not $passed){& $info.FileName param report --port $Port --name DEMO_SHELL_COUNTER --enable off --json | Out-Null}
    $writer.Dispose()
    [IO.File]::WriteAllText((Join-Path $frameRoot "build/$EvidenceName-stderr.log"),$errors.Result,[Text.UTF8Encoding]::new($false))
    [ordered]@{Passed=$passed;Seconds=$elapsed.Elapsed.TotalSeconds;Iterations=$iterations;Port=$Port;WaveJob=$waveId;BackendSha256=(Get-FileHash (Join-Path $folder 'frame_backend.dll')).Hash}|ConvertTo-Json|Set-Content -Encoding UTF8 (Join-Path $frameRoot "build/$EvidenceName-report.json")
}
if(-not $passed){throw 'E507 Shell integration failed'}
'PASS: persistent serial/J-Link sessions, wave acquisition, parameter reads, Perf, stop ACK, export and shutdown'
