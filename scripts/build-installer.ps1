[CmdletBinding()]
param([switch]$SkipNative,[string]$IsccPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
function Invoke-Checked([string]$Command,[string[]]$Arguments) {
    & $Command @Arguments
    if($LASTEXITCODE){throw "$Command failed: $LASTEXITCODE"}
}
Push-Location $frameRoot
try {
    $version=(Get-Content VERSION -Encoding UTF8 -Raw).Trim()
    if($version -notmatch '^\d+\.\d+\.\d+$'){throw 'VERSION must contain a.b.c'}
    if(-not $IsccPath){
        $compiler=Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if($compiler){$IsccPath=$compiler.Source}
        else {foreach($candidate in @("$env:LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe","${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe")){if(Test-Path -LiteralPath $candidate){$IsccPath=$candidate;break}}}
    }
    if(-not $IsccPath -or -not(Test-Path -LiteralPath $IsccPath)){throw 'Install Inno Setup 6 or pass -IsccPath'}
    if(-not $SkipNative){& "$PSScriptRoot/build.ps1" -NativeOnly}
    $native=Join-Path $frameRoot 'build/native/Release/frame_backend.dll'
    if(-not(Test-Path -LiteralPath $native)){throw 'Release backend missing'}
    if((Get-Item $native).VersionInfo.ProductVersion -ne $version){throw 'Backend version does not match VERSION; rebuild without -SkipNative'}
    # Unique staging prevents stale binaries or local user data entering a release.
    $stage=Join-Path $frameRoot ('build/package/'+$version+'-'+[Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    foreach($project in @('Frame.Cli','Frame.Desktop')){
        Invoke-Checked dotnet @('publish',"frontend/$project",'-c','Release','-r','win-x64','--self-contained','true','-p:PublishSingleFile=false','-p:DebugType=None','-p:DebugSymbols=false','-o',$stage,'--nologo')
    }
    Copy-Item -LiteralPath $native -Destination $stage
    Copy-Item -LiteralPath VERSION,LICENSE -Destination $stage
    Copy-Item -LiteralPath scripts/frame-package.bat -Destination "$stage/frame.bat"
    $vswhere="${env:ProgramFiles(x86)}/Microsoft Visual Studio/Installer/vswhere.exe"
    $vs=& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if($LASTEXITCODE -or -not $vs){throw 'MSVC x64 redistributable files not found'}
    $redist=Get-ChildItem "$vs/VC/Redist/MSVC" -Directory | Where-Object {$_.Name -match '^\d+\.\d+'} | Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1
    $crt=Get-ChildItem "$($redist.FullName)/x64" -Directory -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
    if(-not $crt){throw 'MSVC CRT directory not found'}
    Get-ChildItem $crt.FullName -Filter '*.dll' | Copy-Item -Destination $stage
    $licenses=New-Item -ItemType Directory -Path "$stage/licenses" -Force
    Copy-Item -LiteralPath build/deps/llvm-project/llvm/LICENSE.TXT -Destination "$licenses/LLVM.txt"
    Copy-Item -LiteralPath build/native/_deps/json-src/LICENSE.MIT -Destination "$licenses/nlohmann-json.txt"
    $nuget=if($env:NUGET_PACKAGES){$env:NUGET_PACKAGES}else{Join-Path $env:USERPROFILE '.nuget/packages'}
    foreach($assets in @('frontend/Frame.Cli/obj/project.assets.json','frontend/Frame.Desktop/obj/project.assets.json')){
        $graph=Get-Content $assets -Encoding UTF8 -Raw | ConvertFrom-Json
        foreach($entry in $graph.libraries.PSObject.Properties){
            if($entry.Value.type -ne 'package'){continue}
            $directory=Join-Path $nuget $entry.Name.ToLowerInvariant()
            $dest=Join-Path $licenses.FullName ($entry.Name.Replace('/','-'))
            New-Item -ItemType Directory -Path $dest -Force | Out-Null
            Get-ChildItem $directory -File | Where-Object {$_.Name -match 'license|notice|copying|\.nuspec$'} | Copy-Item -Destination $dest
            $nuspec=Get-ChildItem $directory -Filter '*.nuspec' | Select-Object -First 1
            [xml]$metadata=Get-Content $nuspec.FullName -Encoding UTF8 -Raw
            $license=$metadata.SelectSingleNode('//*[local-name()="license"]')
            if($license -and $license.GetAttribute('type') -eq 'expression' -and $license.InnerText -eq 'MIT'){
                $mit=Get-Content (Join-Path $frameRoot 'LICENSE') -Encoding UTF8 -Raw
                $copyright=$metadata.SelectSingleNode('//*[local-name()="copyright"]')
                $attribution=if($copyright){$copyright.InnerText}else{'Authors: '+$metadata.SelectSingleNode('//*[local-name()="authors"]').InnerText}
                $text=$entry.Name+"`n"+$attribution+"`n`n"+$mit.Substring($mit.IndexOf('Permission is hereby granted'))
                [IO.File]::WriteAllText("$dest/MIT-NOTICE.txt",$text,[System.Text.UTF8Encoding]::new($false))
            }
        }
    }
    Copy-Item -LiteralPath docs/THIRD_PARTY_NOTICES.md -Destination $licenses
    Copy-Item -LiteralPath docs/third-party/GLWpfControl-LICENSE.md -Destination $licenses
    foreach($name in @('frame.exe','Frame.Desktop.exe','frame_backend.dll')){
        if((Get-Item "$stage/$name").VersionInfo.ProductVersion -ne $version){throw "Version mismatch: $name"}
    }
    $head=(& git rev-parse HEAD).Trim()
    $manifest=[ordered]@{version=$version;commit=$head;runtime='win-x64 self-contained';files=@(Get-ChildItem $stage -File -Recurse | ForEach-Object {[ordered]@{path=$_.FullName.Substring($stage.Length+1);sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}})}
    $utf8=[System.Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText("$stage/package-manifest.json",($manifest|ConvertTo-Json -Depth 5),$utf8)
    if(@(Get-ChildItem $stage -Recurse -File | Where-Object {$_.Extension -in '.py','.pyc','.pyd'}).Count){throw 'Unexpected Python runtime/source in package'}
    Invoke-Checked $IsccPath @("/DMyAppVersion=$version","/DPackageDir=$stage",(Join-Path $frameRoot 'installer/frame_installer.iss'))
    $installer=Join-Path $frameRoot "dist/installer/FRAME-Setup-$version.exe"
    $hash=(Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$installer.sha256","$hash  FRAME-Setup-$version.exe`n",$utf8)
    Copy-Item -LiteralPath "$stage/package-manifest.json" -Destination "$installer.manifest.json"
    Write-Host "Installer: $installer"
    Write-Host "Payload: $stage"
    Write-Host "SHA256: $hash"
} finally {Pop-Location}
