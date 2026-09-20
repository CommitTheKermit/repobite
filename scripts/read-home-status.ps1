$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()

$services = foreach ($name in @('Tailscale', 'sshd')) {
    $service = Get-CimInstance Win32_Service -Filter "Name='$name'"
    [pscustomobject]@{
        name = $name
        state = $(if ($service) { $service.State } else { 'Missing' })
        start_mode = $(if ($service) { $service.StartMode } else { 'Unknown' })
    }
}
$tasks = foreach ($name in @('repobite-web', 'repobite-batch')) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    $info = if ($task) { Get-ScheduledTaskInfo -TaskName $name } else { $null }
    [pscustomobject]@{
        name = $name
        state = $(if ($task) { [string]$task.State } else { 'Missing' })
        last_result = $(if ($info) { $info.LastTaskResult } else { $null })
        last_run = $(if ($info -and $info.LastRunTime.Year -gt 2000) { $info.LastRunTime.ToUniversalTime().ToString('o') } else { $null })
        next_run = $(if ($info -and $info.NextRunTime.Year -gt 2000) { $info.NextRunTime.ToUniversalTime().ToString('o') } else { $null })
    }
}
$webStatus = $null
try {
    $webStatus = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8765/' -TimeoutSec 4).StatusCode
} catch { }
[pscustomobject]@{
    available = $true
    services = @($services)
    tasks = @($tasks)
    web_status = $webStatus
    booted_at = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
} | ConvertTo-Json -Depth 5 -Compress
