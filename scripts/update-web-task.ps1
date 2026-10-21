$ErrorActionPreference = 'Stop'
$TaskName = 'repobite-web'
$Task = Get-ScheduledTask -TaskName $TaskName
$Password = Read-Host 'Windows 웹 작업 계정 암호' -AsSecureString
$Credential = [System.Net.NetworkCredential]::new('', $Password)
try {
    $Task.Settings.ExecutionTimeLimit = 'PT0S'
    # Password-logon tasks require credentials even when only settings change.
    $null = Set-ScheduledTask -TaskName $TaskName -Settings $Task.Settings `
        -User $Task.Principal.UserId -Password $Credential.Password
} finally {
    $Credential = $null
    $Password.Dispose()
}
if ((Get-ScheduledTask -TaskName $TaskName).State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName
    for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
        if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') { break }
        Start-Sleep -Seconds 1
    }
    if ((Get-ScheduledTask -TaskName $TaskName).State -eq 'Running') {
        throw '웹 작업이 아직 종료 중입니다. 중복 기동하지 않습니다.'
    }
}
Start-ScheduledTask -TaskName $TaskName
$Healthy = $false
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    try {
        $Web = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/' -TimeoutSec 2
        $Status = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8767/status.json' -TimeoutSec 2
        $Healthy = $Web.StatusCode -eq 200 -and $Status.StatusCode -eq 200
        if ($Healthy) { break }
    } catch {}
    Start-Sleep -Seconds 1
}
$Updated = Get-ScheduledTask -TaskName $TaskName
if (-not $Healthy -or $Updated.State -ne 'Running' -or $Updated.Settings.ExecutionTimeLimit -ne 'PT0S') {
    throw '실행 제한, 작업 상태 또는 웹 응답을 확인하지 못했습니다.'
}
Write-Output '웹 실행 제한 PT0S, Running, 웹/상태 HTTP 200 확인'
