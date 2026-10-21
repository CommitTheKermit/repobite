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
'@
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $registrationProbe
    if ($LASTEXITCODE -ne 0) { throw 'Task registration settings test failed' }
} finally {
    Remove-Item $Probe -ErrorAction SilentlyContinue
    $env:UPSTASH_REDIS_REST_URL = $PreviousUrl
    $env:UPSTASH_REDIS_REST_TOKEN = $PreviousToken
    Remove-Item Env:REPOBITE_TEST_PROBE, Env:REPOBITE_TEST_ROOT, Env:REPOBITE_TEST_SCRIPT, Env:REPOBITE_TEST_EXIT -ErrorAction SilentlyContinue
}
Write-Output 'PASS: PowerShell syntax, batch selection, working directory, exit codes, web unlimited runtime'
exit 0
