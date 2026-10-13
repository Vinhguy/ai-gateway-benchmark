[CmdletBinding()]
param(
    [string]$VmName,
    [ValidateRange(1, 60)]
    [int]$PollSeconds = 1,
    [long]$MinimumAvailableKb = 2097152,
    [string]$RunId = (Get-Date -Format 'yyyyMMddTHHmmssfff')
)

function Get-BenchmarkHostAvailableMemoryKb {
    return [long](Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).FreePhysicalMemory
}

function Invoke-BenchmarkVmMemoryGuard {
    param(
        [Parameter(Mandatory = $true)][string]$VmName,
        [scriptblock]$AvailableMemoryReader = { Get-BenchmarkHostAvailableMemoryKb },
        [scriptblock]$VmStateReader = { param($Name) (Get-VM -Name $Name -ErrorAction Stop).State },
        [scriptblock]$VmStopper = { param($Name) Stop-VM -Name $Name -TurnOff -Force -Confirm:$false -ErrorAction Stop }
    )

    $availableKb = [long](& $AvailableMemoryReader)
    if ($availableKb -ge $MinimumAvailableKb) {
        return $true
    }

    Write-Warning "Windows host has $availableKb KiB available; powering off benchmark VM '$VmName' below $MinimumAvailableKb KiB."
    $vmState = & $VmStateReader $VmName
    if ($vmState -eq 'Running') {
        & $VmStopper $VmName
    }
    return $false
}

function Start-BenchmarkVmMemoryGuard {
    param(
        [Parameter(Mandatory = $true)][string]$VmName,
        [Parameter(Mandatory = $true)][int]$PollSeconds,
        [Parameter(Mandatory = $true)][string]$RunId
    )

    $serverRoot = Split-Path -Parent $PSScriptRoot
    $resultsDir = Join-Path $serverRoot 'results'
    New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
    $metricsPath = Join-Path $resultsDir "$RunId-windows-host-resources.csv"
    [System.IO.File]::WriteAllText(
        $metricsPath,
        'timestamp_utc,host_available_mb' + [Environment]::NewLine,
        [System.Text.Encoding]::UTF8
    )

    while ($true) {
        $availableKb = Get-BenchmarkHostAvailableMemoryKb
        $line = '{0},{1}' -f [DateTime]::UtcNow.ToString('o'), [Math]::Round($availableKb / 1024, 1)
        [System.IO.File]::AppendAllText($metricsPath, $line + [Environment]::NewLine, [System.Text.Encoding]::UTF8)
        if (-not (Invoke-BenchmarkVmMemoryGuard -VmName $VmName)) {
            exit 1
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if ([string]::IsNullOrWhiteSpace($VmName)) {
        throw 'VmName is required.'
    }
    if ($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') {
        throw 'RunId must contain 1-80 safe filename characters.'
    }
    Start-BenchmarkVmMemoryGuard -VmName $VmName -PollSeconds $PollSeconds -RunId $RunId
}
