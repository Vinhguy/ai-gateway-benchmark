[CmdletBinding()]
param(
    [string]$TargetUrl = $env:TARGET_URL,
    [int]$VuCount = 0,
    [int]$MaxInFlight = 0,
    [ValidateSet('burst', 'sustained')]
    [string]$Profile = 'sustained',
    [ValidateSet('bifrost', 'litellm', 'direct-mocker')]
    [string]$Gateway = 'bifrost',
    [double]$DurationSeconds = 600,
    [int]$BurstCount = 1000,
    [string]$RunId,
    [double]$ThinkTimeMin = 2,
    [double]$ThinkTimeMax = 5,
    [double]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($TargetUrl)) {
    throw 'TargetUrl is required (pass -TargetUrl or set TARGET_URL).'
}
if ($VuCount -lt 1 -or $VuCount -gt 5000) {
    throw 'VuCount must be between 1 and 5000.'
}
if ($MaxInFlight -lt 1 -or $MaxInFlight -gt [Math]::Min(1000, $VuCount)) {
    throw 'MaxInFlight must be between 1 and min(1000, VuCount).'
}
if ([string]::IsNullOrWhiteSpace($RunId) -or $RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') {
    throw 'RunId is required and must contain 1-80 safe filename characters.'
}
if ($Profile -eq 'sustained' -and ($DurationSeconds -le 0 -or $DurationSeconds -gt 3600)) {
    throw 'DurationSeconds must be greater than 0 and at most 3600.'
}
if ($Profile -eq 'burst' -and ($BurstCount -lt 1 -or $BurstCount -gt [Math]::Min($VuCount, $MaxInFlight))) {
    throw 'BurstCount must be between 1 and min(VuCount, MaxInFlight).'
}
if ($ThinkTimeMin -lt 0 -or $ThinkTimeMax -lt $ThinkTimeMin -or $ThinkTimeMax -gt 60) {
    throw 'Think-time range must satisfy 0 <= ThinkTimeMin <= ThinkTimeMax <= 60.'
}
if ($TimeoutSeconds -le 0 -or $TimeoutSeconds -gt 600) {
    throw 'TimeoutSeconds must be greater than 0 and at most 600.'
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Client venv is missing. Run: python -m venv .venv; .venv\Scripts\python -m pip install -e ".[test]"'
}

$resultsDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'results'
New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
$outputPath = Join-Path $resultsDir "$RunId.json"
$abortPath = Join-Path $resultsDir "$RunId-abort.json"
$resourcePath = Join-Path $resultsDir "$RunId-client-resources.csv"
Remove-Item -LiteralPath $abortPath -Force -ErrorAction SilentlyContinue
[System.IO.File]::WriteAllText(
    $resourcePath,
    'timestamp_utc,host_available_mb,process_working_set_mb,process_private_mb,cpu_cores_used' + [Environment]::NewLine,
    [System.Text.Encoding]::UTF8
)

$pythonArgs = @(
    (Join-Path $PSScriptRoot 'loadgen.py'),
    '--target-url', $TargetUrl,
    '--vu-count', $VuCount.ToString(),
    '--max-in-flight', $MaxInFlight.ToString(),
    '--profile', $Profile,
    '--duration-seconds', $DurationSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--burst-count', $BurstCount.ToString(),
    '--timeout-seconds', $TimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--run-id', $RunId,
    '--gateway', $Gateway,
    '--output', $outputPath,
    '--think-time-min', $ThinkTimeMin.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--think-time-max', $ThinkTimeMax.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--job-memory-gb', '8',
    '--job-cpu-cores', '8'
)
$quotedArgs = $pythonArgs | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }
$process = Start-Process -FilePath $python -ArgumentList ($quotedArgs -join ' ') -PassThru -NoNewWindow
$lastCpuSeconds = 0.0
$lastSampleAt = [DateTime]::UtcNow

while (-not $process.HasExited) {
    Start-Sleep -Seconds 1
    $process.Refresh()
    if ($process.HasExited) { break }

    $availableKb = [long](Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
    if ($availableKb -lt 2097152) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $abortReport = [ordered]@{
            run_id = $RunId
            valid = $false
            event = 'host_memory_below_2_gib'
            host_available_kb = $availableKb
            timestamp_utc = [DateTime]::UtcNow.ToString('o')
        }
        [System.IO.File]::WriteAllText(
            $abortPath,
            ($abortReport | ConvertTo-Json -Depth 4) + [Environment]::NewLine,
            [System.Text.Encoding]::UTF8
        )
        $process.WaitForExit()
        throw "Load stopped: host available RAM is below 2 GiB ($([Math]::Round($availableKb / 1024)) MiB)."
    }

    $sampleAt = [DateTime]::UtcNow
    $elapsedSeconds = [Math]::Max(0.001, ($sampleAt - $lastSampleAt).TotalSeconds)
    $current = Get-Process -Id $process.Id
    $cpuCoresUsed = [Math]::Max(0, ($current.CPU - $lastCpuSeconds) / $elapsedSeconds)
    $freeMb = [Math]::Round($availableKb / 1024, 1)
    $workingMb = [Math]::Round($current.WorkingSet64 / 1MB, 1)
    $privateMb = [Math]::Round($current.PrivateMemorySize64 / 1MB, 1)
    $line = '{0},{1},{2},{3},{4}' -f $sampleAt.ToString('o'), $freeMb, $workingMb, $privateMb, [Math]::Round($cpuCoresUsed, 2)
    [System.IO.File]::AppendAllText($resourcePath, $line + [Environment]::NewLine, [System.Text.Encoding]::UTF8)
    $lastCpuSeconds = $current.CPU
    $lastSampleAt = $sampleAt
}

$process.WaitForExit()
if ($process.ExitCode -ne 0) {
    $abortReport = [ordered]@{
        run_id = $RunId
        valid = $false
        event = 'load_generator_exit_nonzero'
        process_exit_code = $process.ExitCode
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
    }
    [System.IO.File]::WriteAllText(
        $abortPath,
        ($abortReport | ConvertTo-Json -Depth 4) + [Environment]::NewLine,
        [System.Text.Encoding]::UTF8
    )
    throw "Load generator exited with code $($process.ExitCode). See $outputPath and console output."
}
Write-Host "Run complete: $outputPath"
Write-Host "Client resource samples: $resourcePath"
