param(
    [string]$BatchTime = "03:00"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$User = "$env:USERDOMAIN\$env:USERNAME"
$Password = Read-Host "Windows 작업 계정 암호" -AsSecureString
$Credential = [System.Net.NetworkCredential]::new("", $Password)
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -WakeToRun

$WebAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Repo\scripts\run-web.ps1`"" `
    -WorkingDirectory $Repo
$BatchAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Repo\scripts\run-batch.ps1`"" `
    -WorkingDirectory $Repo

Register-ScheduledTask -TaskName "repobite-web" -Action $WebAction `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $Settings `
    -User $User -Password $Credential.Password -RunLevel Limited -Force
Register-ScheduledTask -TaskName "repobite-batch" -Action $BatchAction `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $BatchTime) -Settings $Settings `
    -User $User -Password $Credential.Password -RunLevel Limited -Force
