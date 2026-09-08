$ErrorActionPreference='Stop'
$frameRoot=Split-Path $PSScriptRoot -Parent
$exe=Join-Path $frameRoot 'build/app/frame.exe'
& $exe --help | Out-Null
if($LASTEXITCODE){throw 'CLI help failed'}
$portResult=& $exe serial ports --json | ConvertFrom-Json
if($LASTEXITCODE -or -not $portResult.ok){throw 'Port enumeration failed'}
$fixture=Join-Path $PSScriptRoot 'fixtures/parameter-session.json'
$commands=@("connect --replay `"$fixture`" --json",'param list --json','param read --name TEST_COUNTER --json','disconnect --json')
$lines=($commands -join "`n") | & $exe shell
if($LASTEXITCODE){throw 'Shell transaction failed'}
$results=@($lines | ForEach-Object {$_ | ConvertFrom-Json})
if($results.Count -ne 4 -or $results[1].data[0].name -ne 'TEST_COUNTER' -or $results[2].data.value -ne 42){throw 'Unexpected replay values'}
$invalid=& $exe param read --json | ConvertFrom-Json
if($LASTEXITCODE -ne 3 -or $invalid.ok){throw 'Disconnected command exit code failed'}
$help=& $exe scope pull --help --json | ConvertFrom-Json
if($LASTEXITCODE -or $help.command -ne 'pull'){throw 'Structured help failed'}
$version=& $exe --version --json | ConvertFrom-Json
if($LASTEXITCODE -or $version.version -ne (Get-Content (Join-Path $frameRoot 'VERSION') -Encoding UTF8 -Raw).Trim()){throw 'Structured version failed'}
$bad=& $exe param read --unknown-option --json 2> (Join-Path $frameRoot 'build/cli-parse-stderr.log') | ConvertFrom-Json
if($LASTEXITCODE -ne 2 -or $bad.code -ne 2){throw 'Parameter error JSON failed'}
$failed=('param read --json','serial ports --json' -join "`n") | & $exe shell
if($LASTEXITCODE -ne 3 -or @($failed).Count -ne 1){throw 'Noninteractive Shell must stop on first failure'}
$inherited=@(('serial ports','help' -join "`n") | & $exe shell --json | ForEach-Object {$_ | ConvertFrom-Json})
if($LASTEXITCODE -or $inherited.Count -ne 2 -or -not $inherited[0].ok -or -not $inherited[1].subcommands){throw 'Shell JSON mode inheritance failed'}
$waveFixture=Join-Path $PSScriptRoot 'fixtures/wave-periodic.json'
$rows=@(& $exe wave capture --replay $waveFixture --duration 0.3 --ndjson 2> (Join-Path $frameRoot 'build/cli-stream-stderr.log') | ForEach-Object {$_ | ConvertFrom-Json})
if($LASTEXITCODE -or -not $rows[-1].ok -or -not $rows[-1].data.stop_confirmed){throw 'NDJSON completion failed'}
if(@($rows | Where-Object kind -eq record).Count -ne $rows[-1].data.count){throw 'NDJSON record count mismatch'}
& (Join-Path $frameRoot 'build/native/Release/frame_console_tests.exe') $exe $waveFixture
if($LASTEXITCODE){throw 'Actual Ctrl+C validation failed'}
& (Join-Path $frameRoot 'build/native/Release/frame_console_tests.exe') $exe $waveFixture --ndjson
if($LASTEXITCODE){throw 'Cancelled NDJSON tail validation failed'}
'PASS: CLI help/version, JSON/NDJSON, ports, persistent and fail-fast Shell, replay, exit codes and actual Ctrl+C'
