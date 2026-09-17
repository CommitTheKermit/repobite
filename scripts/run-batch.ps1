$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

if ($env:UPSTASH_REDIS_REST_URL -and $env:UPSTASH_REDIS_REST_TOKEN) {
    & py -3.14 community_batch.py
} elseif ($env:UPSTASH_REDIS_REST_URL -or $env:UPSTASH_REDIS_REST_TOKEN) {
    Write-Error "공용 DB 환경변수 두 개를 모두 설정하세요."
    exit 1
} else {
    & py -3.14 radar.py batch
}
exit $LASTEXITCODE
