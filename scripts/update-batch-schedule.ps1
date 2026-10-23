param([string]$BatchTime = '03:00')
$ErrorActionPreference = 'Stop'
$Triggers = @(0, 6, 12, 18 | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.Add([TimeSpan]::Parse($BatchTime)).AddHours($_))
})
# 기존 작업의 계정, 동작, 인증 정보를 보존하고 트리거만 변경한다.
$null = Set-ScheduledTask -TaskName 'repobite-batch' -Trigger $Triggers
$Task = Get-ScheduledTask -TaskName 'repobite-batch'
if ($Task.Triggers.Count -ne 4) { throw '6시간 간격 트리거 반영을 확인하지 못했습니다.' }
$Task.Triggers | Select-Object StartBoundary, DaysInterval, Enabled
Get-ScheduledTaskInfo -TaskName 'repobite-batch' | Select-Object NextRunTime, LastTaskResult
