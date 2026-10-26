param([switch]$SkipTest)
$ErrorActionPreference = 'Stop'
if ((Get-TimeZone).Id -ne 'Korea Standard Time') { throw '서버 시간대를 한국 시간으로 확인하세요.' }
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$WebTask = Get-ScheduledTask -TaskName 'repobite-web'
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$TaskIdentity = [Security.Principal.NTAccount]::new($WebTask.Principal.UserId).Translate([Security.Principal.SecurityIdentifier])
if ($TaskIdentity.Value -ne $CurrentIdentity.User.Value) { throw '웹 예약 작업과 같은 Windows 계정으로 실행하세요.' }
$Directory = Join-Path $env:LOCALAPPDATA 'RepoBite'
$null = New-Item -ItemType Directory -Force -Path $Directory
$KeyPath = Join-Path $Directory 'resend-key.clixml'
$SecureKey = Read-Host 'Resend API 키 (입력 내용은 표시되지 않습니다)' -AsSecureString
if (-not $SecureKey.Length) { throw '키 입력을 취소했습니다.' }
try {
    $env:RESEND_API_KEY = [Net.NetworkCredential]::new('', $SecureKey).Password
    if ($env:RESEND_API_KEY -notmatch '^re_[A-Za-z0-9_-]+$') { throw 'Resend API 키 형식을 확인하세요.' }
    # 같은 Windows 계정과 컴퓨터에서만 복호화할 수 있는 DPAPI 형식이다.
    $Temporary = Join-Path $Directory ([guid]::NewGuid().ToString() + '.clixml')
    $SecureKey | Export-Clixml -LiteralPath $Temporary
    $Acl = [Security.AccessControl.FileSecurity]::new()
    $Acl.SetAccessRuleProtection($true, $false)
    $Acl.SetOwner($CurrentIdentity.User)
    $Acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($CurrentIdentity.User, 'FullControl', 'Allow'))
    Set-Acl -LiteralPath $Temporary -AclObject $Acl
    Move-Item -LiteralPath $Temporary -Destination $KeyPath -Force
    if (-not $SkipTest) {
        $Recipient = Read-Host '연결 확인 메일을 받을 본인 이메일 주소'
        $env:PYTHONIOENCODING = 'utf-8'
        & py -3.14 automatic_delivery.py --state (Join-Path $Directory 'private\delivery.sqlite') --test-recipient $Recipient
        if ($LASTEXITCODE -ne 0) { throw '확인 메일 접수에 실패해 예약 등록을 중단했습니다.' }
    }
} finally {
    Remove-Item Env:RESEND_API_KEY -ErrorAction SilentlyContinue
    Remove-Variable SecureKey -ErrorAction SilentlyContinue
    if ($Temporary -and (Test-Path $Temporary)) { Remove-Item -LiteralPath $Temporary -Force }
}
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Repo\scripts\run-email.ps1`"" -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -Daily -At '11:00'
$Password = Read-Host '자동 발송 예약에 사용할 기존 Windows 작업 계정 암호' -AsSecureString
if (-not $Password.Length) { throw '키 저장은 완료했지만 예약 등록을 취소했습니다.' }
try {
    $null = Register-ScheduledTask -TaskName 'repobite-email' -Action $Action -Trigger $Trigger -Settings $Settings `
        -User $WebTask.Principal.UserId -Password ([Net.NetworkCredential]::new('', $Password).Password) -RunLevel Limited -Force
} finally { Remove-Variable Password -ErrorAction SilentlyContinue }
$Task = Get-ScheduledTask -TaskName 'repobite-email'
$Info = Get-ScheduledTaskInfo -TaskName 'repobite-email'
[pscustomobject]@{ KeyEncrypted = (Test-Path $KeyPath); State = [string]$Task.State; NextRunTime = $Info.NextRunTime; Trigger = $Task.Triggers[0].StartBoundary }
Write-Output '암호화 키 저장과 매일 오전 11시 예약을 등록했습니다. 실제 수신과 예약 실행 결과는 별도 확인하세요.'
