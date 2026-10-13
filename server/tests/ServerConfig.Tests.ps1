Describe 'Server gateway benchmark configuration' {
    $repoRoot = Split-Path -Parent $PSScriptRoot

    It 'defines the bounded Compose stack' {
        $compose = Join-Path $repoRoot 'compose.yaml'
        (Test-Path $compose) | Should Be $true
        $text = Get-Content -Raw $compose
        $text | Should Match 'mocker'
        $text | Should Match 'bifrost'
        $text | Should Match 'litellm'
        $text | Should Match 'mem_limit:\s*["'']?1g'
        $text | Should Match 'mem_limit:\s*["'']?6g'
    }

    It 'routes both gateways to the same zero-latency mock provider' {
        $compose = Get-Content -Raw (Join-Path $repoRoot 'compose.yaml')
        $compose | Should Match '\-latency.*"0"'
        $bifrost = Get-Content -Raw (Join-Path $repoRoot 'bifrost\config.json')
        $litellm = Get-Content -Raw (Join-Path $repoRoot 'litellm\config.yaml')
        $bifrost | Should Match 'http://mocker:8000'
        $litellm | Should Match 'http://mocker:8000/v1'
        $bifrost | Should Match '"max_retries":\s*0'
        $litellm | Should Match 'num_retries:\s*0'
        $litellm | Should Match 'model_name:\s*openai/gpt-4o-mini'
        $bifrost | Should Match '"models":\s*\["\*"\]'
    }

    It 'provides a gateway selector and memory guard' {
        $selectorPath = Join-Path $repoRoot 'scripts\select-gateway.sh'
        $guardPath = Join-Path $repoRoot 'scripts\guard-server.sh'
        (Test-Path $selectorPath) | Should Be $true
        (Test-Path $guardPath) | Should Be $true
        $selector = Get-Content -Raw $selectorPath
        $selector | Should Match 'bifrost.*litellm'
        $selector.IndexOf('stop "$service"') | Should BeLessThan $selector.IndexOf('up -d mocker')
        $guard = Get-Content -Raw $guardPath
        $guard | Should Match 'MemAvailable'
        $guard | Should Match 'stop "\$gateway"'
    }

    It 'includes the Windows host memory guard' {
        (Test-Path (Join-Path $repoRoot 'windows\Watch-BenchmarkVm.ps1')) | Should Be $true
    }

    It 'includes a Hyper-V VM cap preflight' {
        $preflight = Join-Path $repoRoot 'windows\Test-BenchmarkVm.ps1'
        (Test-Path $preflight) | Should Be $true
        . $preflight -VmName 'test'
        { Assert-BenchmarkVmLimits -MemoryMaximumBytes 9GB -ProcessorCount 9 -HostAvailableKb 3000000 } | Should Throw
        { Assert-BenchmarkVmLimits -MemoryMaximumBytes 8GB -ProcessorCount 10 -HostAvailableKb 3000000 } | Should Throw
        { Assert-BenchmarkVmLimits -MemoryMaximumBytes 8GB -ProcessorCount 9 -HostAvailableKb 1000000 } | Should Throw
        { Assert-BenchmarkVmLimits -MemoryMaximumBytes 8GB -ProcessorCount 9 -HostAvailableKb 3000000 } | Should Not Throw
    }

    It 'powers off the benchmark VM when Windows host memory is below 2 GiB' {
        $hostGuard = Join-Path $repoRoot 'windows\Watch-BenchmarkVm.ps1'
        . $hostGuard
        $stoppedVms = New-Object System.Collections.Generic.List[string]
        $stopVm = { param($name) $stoppedVms.Add($name) }.GetNewClosure()

        $safe = Invoke-BenchmarkVmMemoryGuard -VmName 'AI-Benchmark' `
            -AvailableMemoryReader { 1000000 } `
            -VmStateReader { param($name) 'Running' } `
            -VmStopper $stopVm
        $safe | Should Be $false
        $stoppedVms.Count | Should Be 1
        $stoppedVms[0] | Should Be 'AI-Benchmark'
    }

    It 'leaves the benchmark VM running when Windows host memory is safe' {
        $hostGuard = Join-Path $repoRoot 'windows\Watch-BenchmarkVm.ps1'
        . $hostGuard
        $stoppedVms = New-Object System.Collections.Generic.List[string]
        $stopVm = { param($name) $stoppedVms.Add($name) }.GetNewClosure()

        $safe = Invoke-BenchmarkVmMemoryGuard -VmName 'AI-Benchmark' `
            -AvailableMemoryReader { 4000000 } `
            -VmStateReader { param($name) 'Running' } `
            -VmStopper $stopVm
        $safe | Should Be $true
        $stoppedVms.Count | Should Be 0
    }
}
