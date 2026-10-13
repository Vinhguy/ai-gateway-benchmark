[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$VmName
)

function Assert-BenchmarkVmLimits {
    param(
        [Parameter(Mandatory = $true)][long]$MemoryMaximumBytes,
        [Parameter(Mandatory = $true)][int]$ProcessorCount,
        [Parameter(Mandatory = $true)][long]$HostAvailableKb
    )

    if ($MemoryMaximumBytes -gt 8GB) {
        throw "VM maximum memory is above 8 GiB: $MemoryMaximumBytes bytes."
    }
    if ($ProcessorCount -gt 9) {
        throw "VM has more than 9 virtual CPUs: $ProcessorCount."
    }
    if ($HostAvailableKb -lt 2097152) {
        throw "Windows host has less than 2 GiB available: $HostAvailableKb KiB."
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not (Get-Command Get-VM -ErrorAction SilentlyContinue)) {
        throw 'Hyper-V PowerShell tools are unavailable. Enable the Hyper-V role and tools first.'
    }
    $vm = Get-VM -Name $VmName -ErrorAction Stop
    $processor = Get-VMProcessor -VM $vm -ErrorAction Stop
    $availableKb = [long](Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).FreePhysicalMemory
    Assert-BenchmarkVmLimits `
        -MemoryMaximumBytes ([long]$vm.MemoryMaximumBytes) `
        -ProcessorCount ([int]$processor.Count) `
        -HostAvailableKb $availableKb

    $cpu = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
    if (-not $cpu.VirtualizationFirmwareEnabled) {
        throw 'CPU virtualization is disabled in firmware or is not visible to Windows.'
    }
    Write-Host "Preflight passed for '$VmName': max memory $([Math]::Round($vm.MemoryMaximumBytes / 1GB, 1)) GiB, $($processor.Count) vCPU, host available $([Math]::Round($availableKb / 1MB, 1)) GiB."
}
