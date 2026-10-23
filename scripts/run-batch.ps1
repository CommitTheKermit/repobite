$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

# Task Scheduler can retain an older logon environment. Read current user values at
# launch so newly configured credentials and CLI paths work without signing out.
foreach ($Name in @(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN"
)) {
    if (-not $env:REPOBITE_TEST_PROBE -and -not [Environment]::GetEnvironmentVariable($Name, "Process")) {
        $Value = [Environment]::GetEnvironmentVariable($Name, "User")
        if ($Value) { [Environment]::SetEnvironmentVariable($Name, $Value, "Process") }
    }
}
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath) { $env:Path = "$env:Path;$UserPath" }

# Password-logon scheduled tasks cannot always read GitHub CLI's interactive keyring.
# Use the per-user, DPAPI-encrypted copy created by register-tasks.ps1.
if (-not $env:GH_TOKEN -and -not $env:REPOBITE_TEST_PROBE) {
    $GitHubTokenPath = Join-Path $env:LOCALAPPDATA "RepoBite\github-token.clixml"
    if (Test-Path -LiteralPath $GitHubTokenPath) {
        $SecureToken = Import-Clixml -LiteralPath $GitHubTokenPath
        $TokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
        try {
            $env:GH_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($TokenPointer)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($TokenPointer)
        }
    }
}

$TranscriptStarted = $false
if (-not $env:REPOBITE_TEST_PROBE) {
    try {
        $LogDirectory = Join-Path $env:LOCALAPPDATA "RepoBite"
        $null = New-Item -ItemType Directory -Force -Path $LogDirectory
        $null = Start-Transcript -Append -Path (Join-Path $LogDirectory "batch.log")
        $TranscriptStarted = $true
    } catch {
        # Logging must never prevent the batch itself from running.
    }
}

$ExitCode = 1
try {
    $PythonArguments = $null
    if ($env:UPSTASH_REDIS_REST_URL -and $env:UPSTASH_REDIS_REST_TOKEN) {
        $PythonArguments = @('community_batch.py')
    } elseif ($env:UPSTASH_REDIS_REST_URL -or $env:UPSTASH_REDIS_REST_TOKEN) {
        if (-not $env:REPOBITE_TEST_PROBE) {
            [Console]::Error.WriteLine("공용 DB 환경변수 두 개를 모두 설정하세요.")
        }
    } else {
        $PythonArguments = @('radar.py', 'batch')
    }
    if ($PythonArguments) {
        $PythonCommand = Get-Command py -ErrorAction Stop
        # Native console output can bypass Start-Transcript. Route both streams
        # through PowerShell without treating Python stderr as a terminating error.
        $PreviousErrorAction = $ErrorActionPreference
        $PreviousEncoding = [Console]::OutputEncoding
        $PreviousPythonEncoding = $env:PYTHONIOENCODING
        try {
            $ErrorActionPreference = 'Continue'
            [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
            $env:PYTHONIOENCODING = 'utf-8'
            & $PythonCommand -3.14 @PythonArguments 2>&1 | ForEach-Object { Write-Output $_.ToString() }
            $ExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $PreviousErrorAction
            [Console]::OutputEncoding = $PreviousEncoding
            $env:PYTHONIOENCODING = $PreviousPythonEncoding
        }
    }
} catch {
    if (-not $env:REPOBITE_TEST_PROBE) { [Console]::Error.WriteLine($_.Exception.Message) }
} finally {
    if ($TranscriptStarted) { $null = Stop-Transcript }
}
exit $ExitCode
