param([switch]$SkipTest)
$ErrorActionPreference = 'Stop'
if ((Get-TimeZone).Id -ne 'Korea Standard Time') { throw '서버 시간대를 한국 시간으로 확인하세요.' }
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$WebTask = Get-ScheduledTask -TaskName 'repobite-web'
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$TaskIdentity = [Security.Principal.NTAccount]::new($WebTask.Principal.UserId).Translate([Security.Principal.SecurityIdentifier])
if ($TaskIdentity.Value -ne $CurrentIdentity.User.Value) { throw '웹 예약 작업과 같은 Windows 계정으로 실행하세요.' }
# 공개키 SSH에서는 사용자 DPAPI를 열 수 없으므로 암호 로그온 토큰을 이 프로세스 안에서만 사용한다.
# 암호는 명령 인자나 파일로 넘기지 않으며 같은 암호로 예약 작업도 등록한다.
$Password = Read-Host '기존 Windows 작업 계정 암호 (암호화 저장과 예약 등록에 사용)' -AsSecureString
if (-not $Password.Length) { throw '설정을 취소했습니다. 아직 API 키를 받지 않았습니다.' }
$LogonToken = [IntPtr]::Zero
$Impersonation = $null
$LogonIdentity = $null
try {
    Add-Type -AssemblyName System.Security
    if (-not ('RepoBiteEmailLogon' -as [type])) {
        Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class RepoBiteEmailLogon {
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool LogonUser(string user, string domain, string password, int type, int provider, out IntPtr token);
    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr handle);
}
'@
    }
    $Account = $CurrentIdentity.Name.Split('\', 2)
    if ($Account.Count -ne 2) { throw 'Windows 작업 계정을 확인하세요.' }
    $Credential = [Net.NetworkCredential]::new('', $Password)
    if (-not [RepoBiteEmailLogon]::LogonUser($Account[1], $Account[0], $Credential.Password, 2, 0, [ref]$LogonToken)) {
        throw 'Windows 계정 암호 로그온에 실패했습니다. 실제 계정 암호를 확인하세요. 아직 API 키를 받지 않았습니다.'
    }
    $LogonIdentity = [Security.Principal.WindowsIdentity]::new($LogonToken)
    $Impersonation = $LogonIdentity.Impersonate()
    try {
        $Probe = [Security.Cryptography.ProtectedData]::Protect([byte[]](1, 2, 3), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $null = [Security.Cryptography.ProtectedData]::Unprotect($Probe, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    } catch {
        throw 'Windows 사용자 암호화 저장소를 열지 못했습니다. 서버 콘솔에서 다시 실행하세요. 아직 API 키를 받거나 저장하지 않았습니다.'
    }
    $Directory = Join-Path $env:LOCALAPPDATA 'RepoBite'
    $null = New-Item -ItemType Directory -Force -Path $Directory
    $KeyPath = Join-Path $Directory 'resend-key.clixml'
    $SecureKey = Read-Host 'Resend API 키 (입력 내용은 표시되지 않습니다)' -AsSecureString
    if (-not $SecureKey.Length) { throw '키 입력을 취소했습니다.' }
    $env:RESEND_API_KEY = [Net.NetworkCredential]::new('', $SecureKey).Password
    if ($env:RESEND_API_KEY -notmatch '^re_[A-Za-z0-9_-]+$') { throw 'Resend API 키 형식을 확인하세요.' }
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
    # 예약 등록은 원래의 SSH 토큰에서 수행한다. 비밀은 프로세스 밖으로 넘기지 않는다.
    $Impersonation.Undo()
    $Impersonation.Dispose()
    $Impersonation = $null
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
    $Action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Repo\scripts\run-email.ps1`"" -WorkingDirectory $Repo
    $Trigger = New-ScheduledTaskTrigger -Daily -At '11:00'
    $null = Register-ScheduledTask -TaskName 'repobite-email' -Action $Action -Trigger $Trigger -Settings $Settings `
        -User $WebTask.Principal.UserId -Password $Credential.Password -RunLevel Limited -Force
    $Task = Get-ScheduledTask -TaskName 'repobite-email'
    $Info = Get-ScheduledTaskInfo -TaskName 'repobite-email'
    [pscustomobject]@{ KeyEncrypted = (Test-Path $KeyPath); State = [string]$Task.State; NextRunTime = $Info.NextRunTime; Trigger = $Task.Triggers[0].StartBoundary }
    Write-Output '암호화 키 저장과 매일 오전 11시 예약을 등록했습니다. 실제 수신과 예약 실행 결과는 별도 확인하세요.'
} finally {
    Remove-Item Env:RESEND_API_KEY -ErrorAction SilentlyContinue
    if ($Impersonation) { $Impersonation.Undo(); $Impersonation.Dispose() }
    if ($LogonIdentity) { $LogonIdentity.Dispose() }
    if ($LogonToken -ne [IntPtr]::Zero) { $null = [RepoBiteEmailLogon]::CloseHandle($LogonToken) }
    if ($Temporary -and (Test-Path $Temporary)) { Remove-Item -LiteralPath $Temporary -Force }
    if ($SecureKey) { $SecureKey.Dispose() }
    $Password.Dispose()
    Remove-Variable Password, SecureKey, Credential -ErrorAction SilentlyContinue
}
