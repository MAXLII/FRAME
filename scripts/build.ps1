[CmdletBinding()]
param([ValidateSet('Debug','Release')][string]$Configuration='Release',[switch]$CliOnly,[switch]$SkipNative,[switch]$NativeOnly)
$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
Push-Location $frameRoot
try {
    $llvmRoot=Join-Path $frameRoot 'build/deps/llvm-project'
    if(-not $SkipNative){
        if(-not (Test-Path -LiteralPath "$llvmRoot/llvm/CMakeLists.txt")){
            New-Item -ItemType Directory -Force build/deps | Out-Null
            git clone --depth 1 --branch llvmorg-20.1.8 --filter=blob:none --sparse https://github.com/llvm/llvm-project.git $llvmRoot
            if($LASTEXITCODE){throw 'LLVM clone failed'}
            git -C $llvmRoot sparse-checkout set llvm cmake third-party
            if($LASTEXITCODE){throw 'LLVM checkout failed'}
        }
        cmake -S . -B build/native -G 'Visual Studio 18 2026' -A x64 -DLLVM_ENABLE_RTTI=ON
        if($LASTEXITCODE){throw 'Native configure failed'}
        cmake --build build/native --config $Configuration --target frame_backend frame_native_tests frame_runtime_tests frame_console_tests --parallel 12
        if($LASTEXITCODE){throw 'Native build failed'}
        ctest --test-dir build/native -C $Configuration --output-on-failure
        if($LASTEXITCODE){throw 'Native tests failed'}
    }
    if($NativeOnly){return}
    dotnet build frontend/Frame.Cli -c $Configuration -o build/app --nologo
    if($LASTEXITCODE){throw 'CLI build failed'}
    if(-not $CliOnly){
        dotnet build frontend/Frame.Desktop -c $Configuration -o build/app --nologo
        if($LASTEXITCODE){throw 'Desktop build failed'}
    }
    Copy-Item -LiteralPath "build/native/$Configuration/frame_backend.dll" -Destination build/app/frame_backend.dll
    Write-Host "FRAME build ready: $frameRoot/build/app"
} finally {Pop-Location}
