$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

& py -3.14 web.py
exit $LASTEXITCODE
