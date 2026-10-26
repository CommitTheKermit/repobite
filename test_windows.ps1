# No external API calls or scheduled task registration.
$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
foreach ($file in Get-ChildItem "$Repo\scripts\*.ps1") {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "PowerShell syntax error: $($file.Name): $errors" }
}

# Each wrapper runs in its own shell because it calls exit.
$Probe = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString() + '.json')
$PreviousUrl = $env:UPSTASH_REDIS_REST_URL
$PreviousToken = $env:UPSTASH_REDIS_REST_TOKEN
$env:REPOBITE_TEST_PROBE = $Probe
$env:REPOBITE_TEST_ROOT = $Repo
try {
    foreach ($case in @(
        @('run-batch.ps1', '', '', 'radar.py', 'batch', 0),
        @('run-batch.ps1', 'test-url', 'test-token', 'community_batch.py', '', 0),
        @('run-batch.ps1', 'test-url', '', '', '', 1),
        @('run-batch.ps1', '', 'test-token', '', '', 1),
        @('run-web.ps1', '', '', 'web.py', '--status-port|8767', 0),
        @('run-batch.ps1', '', '', 'radar.py', 'batch', 7)
    )) {
        $env:UPSTASH_REDIS_REST_URL = $case[1]
        $env:UPSTASH_REDIS_REST_TOKEN = $case[2]
        $env:REPOBITE_TEST_SCRIPT = $case[0]
        $env:REPOBITE_TEST_EXIT = [string]$case[5]
        Remove-Item $Probe -ErrorAction SilentlyContinue
        $command = @'
function py {
    @{ argv = @($args); cwd = (Get-Location).Path } | ConvertTo-Json | Set-Content -Encoding UTF8 $env:REPOBITE_TEST_PROBE
    $global:LASTEXITCODE = [int]$env:REPOBITE_TEST_EXIT
}
Set-Location $env:TEMP
try {
    & (Join-Path $env:REPOBITE_TEST_ROOT ('scripts\' + $env:REPOBITE_TEST_SCRIPT))
    exit $LASTEXITCODE
} catch { exit 1 }
'@
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $command *> $null
        if ($LASTEXITCODE -ne $case[5]) { throw "Unexpected wrapper exit: $($case[0])" }
        if ($case[3]) {
            $result = Get-Content -Raw -Encoding UTF8 $Probe | ConvertFrom-Json
            $expected = @('-3.14', $case[3])
            if ($case[4]) { $expected += $case[4].Split('|') }
            if (($result.argv -join '|') -ne ($expected -join '|') -or $result.cwd -ne $Repo) {
                throw "Incorrect command or working directory: $($case[0])"
            }
        } elseif (Test-Path $Probe) { throw 'Partial DB configuration must not launch Python' }
    }
    # Exercise native Python stderr through the real wrapper and a temporary transcript.
    # Both API entry points are fixtures; no credentials or external requests are used.
    $LogFixture = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
    $null = New-Item -ItemType Directory -Force (Join-Path $LogFixture 'scripts')
    Copy-Item (Join-Path $Repo 'scripts\run-batch.ps1') (Join-Path $LogFixture 'scripts\run-batch.ps1')
    $fixturePython = @'
import io, json, os, sys
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0, os.environ['REPOBITE_TEST_ROOT'])
import vertex

def fail(*args, **kwargs):
    body = {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED"}]}}
    raise HTTPError('https://fixture.invalid', 429, 'fixture', {}, io.BytesIO(json.dumps(body).encode()))

with patch.object(vertex, 'project_id', return_value='fixture'), patch.object(vertex, 'access_token', return_value='fixture'):
    try:
        vertex.generate_json('fixture', {}, open_url=fail, sleep=lambda _: None)
    except vertex.VertexHTTPError:
        print('FIXTURE child_completed')
        sys.exit(7)
'@
    [IO.File]::WriteAllText((Join-Path $LogFixture 'community_batch.py'), $fixturePython, [Text.UTF8Encoding]::new($false))
    $fixtureRunner = @'
$env:LOCALAPPDATA = Join-Path $PSScriptRoot 'local'
$env:GH_TOKEN = 'fixture-token'
$env:UPSTASH_REDIS_REST_URL = 'https://fixture.invalid'
$env:UPSTASH_REDIS_REST_TOKEN = 'fixture-token'
Remove-Item Env:REPOBITE_TEST_PROBE -ErrorAction SilentlyContinue
& (Join-Path $PSScriptRoot 'scripts\run-batch.ps1')
exit $LASTEXITCODE
'@
    $runnerPath = Join-Path $LogFixture 'runner.ps1'
    [IO.File]::WriteAllText($runnerPath, $fixtureRunner, [Text.UTF8Encoding]::new($false))
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runnerPath *> $null
    if ($LASTEXITCODE -ne 7) { throw 'Native batch exit code was lost' }
    $logText = Get-Content -Raw -Encoding UTF8 (Join-Path $LogFixture 'local\RepoBite\batch.log')
    foreach ($expected in @('http_status=429', 'reason=RATE_LIMIT_EXCEEDED', 'attempts=5', 'FIXTURE child_completed',
        '요청 한도 또는 처리 용량 초과')) {
        if (-not $logText.Contains($expected)) { throw "Missing transcript diagnostic: $expected" }
    }
    # Run the actual registrar with credential/file/task mutations replaced by fixtures.
    # New-ScheduledTaskSettingsSet stays real so the resulting XML duration is checked.
    $registrationProbe = @'
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks -ErrorAction Stop
$global:Registered = @()
function gh { $global:LASTEXITCODE = 0; 'fixture-token' }
function New-Item { param($ItemType, [switch]$Force, $Path) }
function Export-Clixml {
    param([Parameter(ValueFromPipeline)]$InputObject, $Path)
    process {}
}
function Read-Host {
    param($Prompt, [switch]$AsSecureString)
    ConvertTo-SecureString 'fixture-password' -AsPlainText -Force
}
function Register-ScheduledTask {
    param($TaskName, $Action, $Trigger, $Settings, $User, $Password, $RunLevel, [switch]$Force)
    $expectedLimit = if ($TaskName -eq 'repobite-web') { 'PT0S' } else { 'PT72H' }
    if ($Settings.ExecutionTimeLimit -ne $expectedLimit) { throw "Incorrect execution limit: $TaskName" }
    if ($Settings.RestartCount -ne 3) { throw "Missing restart policy: $TaskName" }
    $global:Registered += $TaskName
}
& (Join-Path $env:REPOBITE_TEST_ROOT 'scripts\register-tasks.ps1')
if (($global:Registered -join '|') -ne 'repobite-web|repobite-batch') { throw 'Missing task registration' }

$global:UpdatedTask = [pscustomobject]@{
    State = 'Running'
    Principal = [pscustomobject]@{ UserId = 'fixture-user' }
    Settings = [pscustomobject]@{ ExecutionTimeLimit = 'PT72H'; RestartCount = 3 }
}
$global:UpdateCalls = @()
function Get-ScheduledTask {
    param($TaskName)
    if ($TaskName -ne 'repobite-web') { throw 'Unexpected task access' }
    $global:UpdatedTask
}
function Set-ScheduledTask {
    param($TaskName, $Settings, $User, $Password)
    if ($TaskName -ne 'repobite-web' -or $Settings.ExecutionTimeLimit -ne 'PT0S' -or
        $Settings.RestartCount -ne 3 -or $User -ne 'fixture-user' -or $Password -ne 'fixture-password') {
        throw 'Incorrect existing task update'
    }
    $global:UpdateCalls += 'set'
}
function Stop-ScheduledTask {
    param($TaskName)
    if ($TaskName -ne 'repobite-web') { throw 'Unexpected stop' }
    $global:UpdatedTask.State = 'Ready'
    $global:UpdateCalls += 'stop'
}
function Start-ScheduledTask {
    param($TaskName)
    if ($TaskName -ne 'repobite-web') { throw 'Unexpected start' }
    $global:UpdatedTask.State = 'Running'
    $global:UpdateCalls += 'start'
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec)
    if ($Uri -notin @('http://127.0.0.1:8765/', 'http://127.0.0.1:8767/status.json')) {
        throw 'Unexpected network request'
    }
    [pscustomobject]@{ StatusCode = 200 }
}
& (Join-Path $env:REPOBITE_TEST_ROOT 'scripts\update-web-task.ps1')
if (($global:UpdateCalls -join '|') -ne 'set|stop|start') { throw 'Incorrect update and restart order' }
'@
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $registrationProbe
    if ($LASTEXITCODE -ne 0) { throw 'Task registration settings test failed' }
} finally {
    Remove-Item $Probe -ErrorAction SilentlyContinue
    if ($LogFixture -and (Test-Path $LogFixture)) { Remove-Item -Recurse -Force $LogFixture }
    $env:UPSTASH_REDIS_REST_URL = $PreviousUrl
    $env:UPSTASH_REDIS_REST_TOKEN = $PreviousToken
    Remove-Item Env:REPOBITE_TEST_PROBE, Env:REPOBITE_TEST_ROOT, Env:REPOBITE_TEST_SCRIPT, Env:REPOBITE_TEST_EXIT -ErrorAction SilentlyContinue
}
Write-Output 'PASS: PowerShell syntax, batch selection, working directory, exit codes, native HTTP transcript, web unlimited runtime'
exit 0
