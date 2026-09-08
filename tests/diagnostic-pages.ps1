$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
Push-Location $frameRoot
try {
    & arm-none-eabi-g++ -std=c++20 -g -O0 -mcpu=cortex-m4 -mthumb -nostdlib '-Wl,-Ttext=0x08000000' '-Wl,-Tdata=0x20000000' '-Wl,--section-start=.resolved=0x20001000' '-Wl,--section-start=.resolved_node=0x20001010' '-Wl,-e,fixture_entry' tests/native/symbol_fixture.cpp -o build/symbol-fixture.elf
    if($LASTEXITCODE){throw 'ARM symbol fixture build failed'}
    & cmake --build build/native --config Release --target frame_runtime_tests --parallel 12
    if($LASTEXITCODE){throw 'Backend build failed'}
    & ctest --test-dir build/native -C Release --output-on-failure
    if($LASTEXITCODE){throw 'Backend regression failed'}
    & dotnet build tests/ui/Frame.UiTests.csproj -c Release -o build/legacy-ui-tests --nologo
    if($LASTEXITCODE){throw 'WPF test build failed'}
    Copy-Item -LiteralPath build/native/Release/frame_backend.dll -Destination build/legacy-ui-tests/frame_backend.dll
    & ./build/legacy-ui-tests/Frame.UiTests.exe $frameRoot
    if($LASTEXITCODE){throw 'WPF regression failed'}
} finally { Pop-Location }
