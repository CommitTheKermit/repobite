$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

& py -3.14 radar.py batch
exit $LASTEXITCODE
