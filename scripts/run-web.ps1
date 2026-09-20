$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$env:HOME_STATUS_HOST = [Environment]::GetEnvironmentVariable('HOME_STATUS_HOST', 'User')
& py -3.14 web.py --status-port 8767
exit $LASTEXITCODE
