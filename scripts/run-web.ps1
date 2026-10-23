$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

foreach ($Name in @('UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN', 'REPOBITE_COLLECT_SECRET', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION')) {
    if (-not $env:REPOBITE_TEST_PROBE) { [Environment]::SetEnvironmentVariable($Name, [Environment]::GetEnvironmentVariable($Name, 'User'), 'Process') }
}
$GitHubTokenPath = Join-Path $env:LOCALAPPDATA 'RepoBite\github-token.clixml'
if (-not $env:REPOBITE_TEST_PROBE -and (Test-Path $GitHubTokenPath)) {
    $SecureToken = Import-Clixml $GitHubTokenPath
    $env:GH_TOKEN = [System.Net.NetworkCredential]::new('', $SecureToken).Password
}
$env:HOME_STATUS_HOST = [Environment]::GetEnvironmentVariable('HOME_STATUS_HOST', 'User')
& py -3.14 web.py --status-port 8767
exit $LASTEXITCODE
