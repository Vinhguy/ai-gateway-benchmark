Describe 'Windows load runner input validation' {
    $runner = Join-Path (Split-Path -Parent $PSScriptRoot) 'run.ps1'

    It 'is present as the validated launch boundary' {
        (Test-Path $runner) | Should Be $true
    }

    It 'rejects a virtual user count above 5000 before launching Python' {
        { & $runner -TargetUrl 'http://127.0.0.1:8080/v1/chat/completions' -VuCount 5001 -MaxInFlight 1000 -Profile burst -RunId invalid } | Should Throw
    }

    It 'rejects an in-flight limit above 1000 before launching Python' {
        { & $runner -TargetUrl 'http://127.0.0.1:8080/v1/chat/completions' -VuCount 5000 -MaxInFlight 1001 -Profile burst -RunId invalid } | Should Throw
    }

    It 'rejects a missing target before launching Python' {
        { & $runner -VuCount 100 -MaxInFlight 100 -Profile burst -RunId invalid } | Should Throw
    }
}
