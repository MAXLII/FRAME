[CmdletBinding()]
param([string]$Repository='MAXLII/FRAME',[Parameter(Mandatory=$true)][string]$NotesFile)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
function Invoke-Checked([string]$Command,[string[]]$Arguments) {
    $result=& $Command @Arguments
    if($LASTEXITCODE){throw "$Command failed: $LASTEXITCODE"}
    return $result
}
Push-Location $frameRoot
try {
    $version=(Get-Content VERSION -Encoding UTF8 -Raw).Trim();$tag="v$version"
    $head=(Invoke-Checked git @('rev-parse','HEAD')).Trim()
    if(@(Invoke-Checked git @('status','--porcelain')).Count){throw 'Commit scoped changes before publishing'}
    if((Invoke-Checked git @('show','HEAD:VERSION')).Trim() -ne $version){throw 'Uncommitted version'}
    $upstream=(Invoke-Checked git @('rev-parse','@{upstream}')).Trim()
    if($head -ne $upstream){throw 'Push the release commit to its upstream before publishing'}
    if(-not(Test-Path -LiteralPath $NotesFile)){throw 'Release notes file missing'}
    $installer=Join-Path $frameRoot "dist/installer/FRAME-Setup-$version.exe"
    $checksum="$installer.sha256";$manifest="$installer.manifest.json"
    if((Get-Item $installer).VersionInfo.ProductVersion.Trim() -ne $version){throw 'Installer version mismatch'}
    $package=Get-Content $manifest -Encoding UTF8 -Raw | ConvertFrom-Json
    if($package.commit -ne $head -or $package.version -ne $version){throw 'Rebuild the installer from the release commit'}
    $hash=(Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if((Get-Content $checksum -Encoding UTF8 -Raw).Trim() -ne "$hash  FRAME-Setup-$version.exe"){throw 'Installer checksum mismatch'}
    $null=Invoke-Checked gh @('auth','status')
    $existing=& gh release view $tag --repo $Repository --json tagName 2>$null
    if($LASTEXITCODE -eq 0){throw "Release $tag already exists; it will not be overwritten"}
    $existingTag=& git rev-parse -q --verify "refs/tags/$tag" 2>$null
    if($LASTEXITCODE -eq 0){if((Invoke-Checked git @('rev-list','-n','1',$tag)).Trim() -ne $head){throw 'Existing tag targets another commit'}}
    else {$null=Invoke-Checked git @('tag','-a',$tag,'-m',"FRAME $tag")}
    $null=Invoke-Checked git @('push','origin',"refs/tags/$tag")
    # Upload as a draft first so a partial upload never becomes a public release.
    $null=Invoke-Checked gh @('release','create',$tag,$installer,$checksum,$manifest,'--repo',$Repository,'--verify-tag','--draft','--title',"FRAME $version",'--notes-file',(Resolve-Path $NotesFile).Path)
    $release=(Invoke-Checked gh @('release','view',$tag,'--repo',$Repository,'--json','assets,isDraft')) | ConvertFrom-Json
    foreach($path in @($installer,$checksum,$manifest)){
        $name=Split-Path $path -Leaf
        $asset=@($release.assets | Where-Object {$_.name -eq $name})
        if($asset.Count -ne 1 -or $asset[0].size -ne (Get-Item $path).Length){throw "Release remains draft: asset validation failed ($name)"}
    }
    $null=Invoke-Checked gh @('release','edit',$tag,'--repo',$Repository,'--draft=false','--latest')
    Invoke-Checked gh @('release','view',$tag,'--repo',$Repository,'--json','url,tagName,isDraft,assets')
} finally {Pop-Location}
