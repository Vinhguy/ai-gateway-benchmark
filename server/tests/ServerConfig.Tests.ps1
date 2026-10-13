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
}
