param([string]$BatchTime = '03:00', [switch]$PromptForCredential)
$ErrorActionPreference = 'Stop'
$Triggers = @(0, 6, 12, 18 | ForEach-Object {
    New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.Add([TimeSpan]::Parse($BatchTime)).AddHours($_))
})
# 기존 작업의 계정, 동작, 인증 정보를 보존하고 트리거만 변경한다.
if ($PromptForCredential) {
    $Task = Get-ScheduledTask -TaskName 'repobite-batch'
    # GUI 인증창 대신 가려진 콘솔 입력을 받아 `ssh -t`로 접속한 원격 터미널에서도 입력할 수 있게 한다.
    $Password = Read-Host -AsSecureString "기존 RepoBite 예약 작업 계정($($Task.Principal.UserId))의 Windows 암호"
    if (-not $Password.Length) { throw '예약 변경을 취소했습니다.' }
    try {
        $null = Set-ScheduledTask -TaskName 'repobite-batch' -Trigger $Triggers -User $Task.Principal.UserId -Password ([Net.NetworkCredential]::new('', $Password).Password)
    } finally { Remove-Variable Password -ErrorAction SilentlyContinue }
} else {
    $null = Set-ScheduledTask -TaskName 'repobite-batch' -Trigger $Triggers
}
$Task = Get-ScheduledTask -TaskName 'repobite-batch'
if ($Task.Triggers.Count -ne 4) { throw '6시간 간격 트리거 반영을 확인하지 못했습니다.' }
$Task.Triggers | Select-Object StartBoundary, DaysInterval, Enabled
Get-ScheduledTaskInfo -TaskName 'repobite-batch' | Select-Object NextRunTime, LastTaskResult
