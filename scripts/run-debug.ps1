[CmdletBinding()]
param([switch]$FullBuild,[switch]$BuildOnly)
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
$appDirectory=Join-Path $frameRoot 'build/app'
$stampPath=Join-Path $frameRoot 'build/run-debug.json'
$watch=[Diagnostics.Stopwatch]::StartNew()

function Get-InputFiles([string[]]$Paths) {
    foreach($relative in $Paths){
        $path=Join-Path $frameRoot $relative
        if(-not (Test-Path -LiteralPath $path)){continue}
        $item=Get-Item -LiteralPath $path
        if(-not $item.PSIsContainer){$item;continue}
        $pending=[Collections.Generic.Stack[string]]::new()
        $pending.Push($path)
        while($pending.Count -gt 0){
            foreach($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force){
                if($entry.PSIsContainer){
                    if($entry.Name -notin @('bin','obj','.git')){$pending.Push($entry.FullName)}
                }else{$entry}
            }
        }
    }
}
function Get-Fingerprint([object[]]$Files) {
    $metadata=@($Files | Sort-Object FullName -Unique | ForEach-Object {
        '{0}|{1}|{2}' -f $_.FullName,$_.Length,$_.LastWriteTimeUtc.Ticks
    }) -join "`n"
    $hash=[Security.Cryptography.SHA256]::Create()
    try{[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($metadata)))}finally{$hash.Dispose()}
}

$shared=@('VERSION','scripts/build.ps1','scripts/run-debug.ps1')
$native=Get-Fingerprint @(Get-InputFiles ($shared+@('CMakeLists.txt','backend')))
$desktop=Get-Fingerprint @(Get-InputFiles ($shared+@('Directory.Build.props','Directory.Build.targets','global.json','NuGet.Config',
    'frontend/Frame.Interop','frontend/Frame.Client','frontend/Frame.Desktop','assets','docs/help')))
$nativeOutputs=@('build/native/Release/frame_backend.dll','build/app/frame_backend.dll')
$required=@('Frame.Desktop.exe','Frame.Desktop.dll','Frame.Desktop.deps.json','Frame.Desktop.runtimeconfig.json','Frame.Client.dll')
$stamp=$null
if(Test-Path -LiteralPath $stampPath){
    try{$stamp=Get-Content -LiteralPath $stampPath -Raw -Encoding UTF8 | ConvertFrom-Json}catch{$stamp=$null}
}
$nativeMissing=@($nativeOutputs | Where-Object {-not (Test-Path -LiteralPath (Join-Path $frameRoot $_))}).Count -gt 0
$desktopMissing=@($required | Where-Object {-not (Test-Path -LiteralPath (Join-Path $appDirectory $_))}).Count -gt 0
$nativeOutput=Get-Fingerprint @(Get-InputFiles $nativeOutputs)
$desktopOutput=Get-Fingerprint @(Get-InputFiles @('build/app') | Where-Object {$_.Name -ne 'frame_backend.dll'})
$nativeChanged=$nativeMissing -or $null -eq $stamp -or $stamp.native -ne $native -or $stamp.nativeOutput -ne $nativeOutput
$desktopChanged=$desktopMissing -or $null -eq $stamp -or $stamp.desktop -ne $desktop -or $stamp.desktopOutput -ne $desktopOutput

if($FullBuild -or $nativeChanged -or $desktopChanged){
    Write-Host 'Updating debug application...'
    if($FullBuild){& "$PSScriptRoot/build.ps1" -Configuration Release}
    elseif($desktopChanged){& "$PSScriptRoot/build.ps1" -Configuration Release -ForLaunch -SkipNative:(-not $nativeChanged)}
    else{
        & "$PSScriptRoot/build.ps1" -Configuration Release -ForLaunch -NativeOnly
        Copy-Item -LiteralPath (Join-Path $frameRoot 'build/native/Release/frame_backend.dll') -Destination (Join-Path $appDirectory 'frame_backend.dll')
    }
    $result=[ordered]@{native=$native;desktop=$desktop
        nativeOutput=(Get-Fingerprint @(Get-InputFiles $nativeOutputs))
        desktopOutput=(Get-Fingerprint @(Get-InputFiles @('build/app') | Where-Object {$_.Name -ne 'frame_backend.dll'}))}
    [IO.File]::WriteAllText($stampPath,($result | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
}else{Write-Host 'Debug application is up to date.'}

if(-not $env:FRAME_COMM_LOG_DIR){$env:FRAME_COMM_LOG_DIR=Join-Path $frameRoot 'logs/communication'}
Write-Host "Communication logs: $env:FRAME_COMM_LOG_DIR"
Write-Host ('Debug application ready in {0:N2} s.' -f $watch.Elapsed.TotalSeconds)
if(-not $BuildOnly){Start-Process -FilePath (Join-Path $appDirectory 'Frame.Desktop.exe') -WorkingDirectory $frameRoot}
