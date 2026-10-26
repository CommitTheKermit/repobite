$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$ExitCode = 1
try {
    foreach ($Name in @('UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN')) {
        [Environment]::SetEnvironmentVariable($Name, [Environment]::GetEnvironmentVariable($Name, 'User'), 'Process')
    }
    $Directory = Join-Path $env:LOCALAPPDATA 'RepoBite'
    $SecureKey = Import-Clixml -LiteralPath (Join-Path $Directory 'resend-key.clixml')
    $env:RESEND_API_KEY = [Net.NetworkCredential]::new('', $SecureKey).Password
    $GitHubKey = Import-Clixml -LiteralPath (Join-Path $Directory 'github-token.clixml')
    $env:GH_TOKEN = [Net.NetworkCredential]::new('', $GitHubKey).Password
    $env:Path = "$env:Path;$([Environment]::GetEnvironmentVariable('Path', 'User'))"
    $env:PYTHONIOENCODING = 'utf-8'
    & py -3.14 automatic_delivery.py --state (Join-Path $Directory 'private\delivery.sqlite')
    $ExitCode = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine('자동 발송 설정 또는 실행에 실패했습니다. 암호화 키와 예약 계정을 확인하세요.')
} finally {
    Remove-Item Env:RESEND_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue
    Remove-Variable SecureKey, GitHubKey -ErrorAction SilentlyContinue
    if ($Directory -and (Test-Path $Directory)) {
        # 요청·수신자·인증값 없이 실행 시각과 종료 코드만 남긴다.
        $Summary = '{"at":"' + [DateTimeOffset]::Now.ToString('o') + '","exit_code":' + $ExitCode + '}'
        $Summary | Out-File -LiteralPath (Join-Path $Directory 'email-runs.log') -Encoding utf8 -Append
    }
}
exit $ExitCode
