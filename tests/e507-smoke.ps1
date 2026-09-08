param([Parameter(Mandatory)][string]$Port,[Parameter(Mandatory)][uint32]$Probe,[Parameter(Mandatory)][string]$Elf)
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
$exe=Join-Path $frameRoot 'build/app/frame.exe'
$writer=[IO.StreamWriter]::new((Join-Path $frameRoot 'build/e507-nine-feature.ndjson'),$false,[Text.UTF8Encoding]::new($false))
$writer.AutoFlush=$true
function Invoke-Frame([string[]]$Arguments){
    $text=& $exe @Arguments --json
    $code=$LASTEXITCODE
    $result=$text | ConvertFrom-Json
    $writer.WriteLine(([ordered]@{time=(Get-Date).ToString('o');arguments=$Arguments;exit=$code;result=$result}|ConvertTo-Json -Depth 12 -Compress))
    if($code -or -not $result.ok){throw "FRAME failed ($code): $($Arguments -join ' ')"}
    return $result.data
}
$serial=@('--port',$Port)
$jlink=@('--probe',"$Probe",'--elf',$Elf)
try {
    $ports=Invoke-Frame @('serial','ports')
    if(-not ($ports | Where-Object {$_ -eq $Port -or $_.port -eq $Port})){throw 'Port is not enumerated'}
    $parameters=Invoke-Frame (@('param','list')+$serial)
    $counter=$parameters | Where-Object name -eq DEMO_SHELL_COUNTER
    if(-not $counter){throw 'Expected diagnostic parameter is absent'}
    try {
        Invoke-Frame (@('param','write','--name','DEMO_SHELL_COUNTER','--value','17')+$serial)|Out-Null
        $read=Invoke-Frame (@('param','read','--name','DEMO_SHELL_COUNTER')+$serial)
        if($read.value -ne 17){throw 'Parameter readback failed'}
    } finally {Invoke-Frame (@('param','write','--name','DEMO_SHELL_COUNTER','--value',"$($counter.value)")+$serial)|Out-Null}
    try {
        Invoke-Frame (@('param','report','--name','DEMO_SHELL_COUNTER','--enable','on')+$serial)|Out-Null
        $wave=Invoke-Frame (@('wave','capture','--duration','1','--output','build/e507-wave.json')+$serial)
        if($wave.count -lt 1 -or -not $wave.stop_confirmed){throw 'Wave capture failed'}
    } finally {Invoke-Frame (@('param','report','--name','DEMO_SHELL_COUNTER','--enable',$(if($counter.flags -band 1){'on'}else{'off'}))+$serial)|Out-Null}
    Invoke-Frame (@('perf','info','--record','build/e507-raw-query.ndjson')+$serial)|Out-Null
    $wire=Get-Content (Join-Path $frameRoot 'build/e507-raw-query.ndjson') -Encoding UTF8 | ForEach-Object {$_|ConvertFrom-Json} | Where-Object tx | Select-Object -First 1
    $raw=Invoke-Frame (@('serial','raw','--hex',$wire.tx,'--duration','0.3','--output','build/e507-serial.json')+$serial)
    if($raw.count -lt 1){throw 'Raw serial response missing'}
    $scope=Invoke-Frame (@('scope','list')+$serial)
    Invoke-Frame (@('scope','channels','--id','0')+$serial)|Out-Null
    Invoke-Frame (@('scope','start','--id','0')+$serial)|Out-Null
    Start-Sleep -Milliseconds 1300
    Invoke-Frame (@('scope','trigger','--id','0')+$serial)|Out-Null
    Start-Sleep -Milliseconds 700
    $capture=Invoke-Frame (@('scope','pull','--id','0','--output','build/e507-scope.json')+$serial)
    if($capture.count -ne 100){throw 'Scope sample count failed'}
    $original=Invoke-Frame (@('sfra','info','--id','0')+$serial)
    try {
        Invoke-Frame (@('sfra','configure','--id','0','--start-hz','500','--stop-hz','1000','--amplitude','1')+$serial)|Out-Null
        Invoke-Frame (@('sfra','start','--id','0')+$serial)|Out-Null
        for($attempt=0;$attempt -lt 120;$attempt++){
            Start-Sleep -Milliseconds 500
            $info=Invoke-Frame (@('sfra','info','--id','0')+$serial)
            if($info.done -and $info.ready -and $info.table_length -eq $info.count){break}
        }
        $points=Invoke-Frame (@('sfra','points','--id','0','--output','build/e507-sfra.json')+$serial)
        if($points.count -ne 300){throw 'SFRA point count failed'}
    } finally {
        Invoke-Frame (@('sfra','stop','--id','0')+$serial)|Out-Null
        Invoke-Frame (@('sfra','configure','--id','0','--start-hz',"$($original.start_hz)",'--stop-hz',"$($original.stop_hz)",'--amplitude',"$($original.amplitude)")+$serial)|Out-Null
    }
    $perf=Invoke-Frame (@('perf','samples')+$serial)
    if($perf.Count -ne 31){throw 'Perf dictionary/sample completeness failed'}
    $trace=Invoke-Frame (@('trace','capture','--duration','1','--output','build/e507-trace.json')+$serial)
    if($trace.count -lt 1 -or -not $trace.stop_confirmed){throw 'Trace capture failed'}
    $lists=Invoke-Frame (@('section','list')+$serial)
    foreach($list in $lists){
        $nodes=@(Invoke-Frame (@('section','nodes','--id',"$($list.list_id)")+$serial))
        if($nodes.Count -ne $list.node_count){throw "Section node count failed: $($list.name)"}
    }
    $ram=Invoke-Frame (@('jlink','read','--name','s_demo_shell_counter')+$jlink)
    try {Invoke-Frame (@('jlink','write','--name','s_demo_shell_counter','--value','23')+$jlink)|Out-Null}
    finally {Invoke-Frame (@('jlink','write','--name','s_demo_shell_counter','--value',"$($ram.value)")+$jlink)|Out-Null}
    $drop=Invoke-Frame (@('jlink','read','--name','g_bsp_usart_dbg_tx_drop_count')+$jlink)
    if($drop.value -ne 0){throw 'Firmware TX loss counter is nonzero'}
    [ordered]@{Passed=$true;Port=$Port;Probe=$Probe;Parameters=$parameters.Count;Wave=$wave.count;Scope=$capture.count;Sfra=$points.count;Perf=$perf.Count;Trace=$trace.count;Sections=$lists.Count;TxDrops=$drop.value;BackendSha256=(Get-FileHash (Join-Path $frameRoot 'build/app/frame_backend.dll')).Hash}|ConvertTo-Json|Set-Content (Join-Path $frameRoot 'build/e507-nine-feature-report.json') -Encoding UTF8
} finally {$writer.Dispose()}
'PASS: E507 nine feature smoke; diagnostic parameter/RAM values and SFRA configuration restored'
