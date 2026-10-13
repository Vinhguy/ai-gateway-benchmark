# Direct Windows load generator

The client uses Python asyncio/aiohttp to send HTTP requests directly. It does not require k6, Docker, or one OS thread per virtual user.

## Setup (PowerShell)

```powershell
cd client
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Set `TARGET_URL` or pass `-TargetUrl`; use a full chat-completions URL, for example `http://<server-private-ip>:8080/v1/chat/completions`. A separate Git-ignoreable `BENCHMARK_API_KEY` may be set in the shell if a different gateway key is configured.

## Profiles

Synchronized burst of exactly 1,000 requests:

```powershell
$id = Get-Date -Format 'yyyyMMddTHHmmssfff'
.\run.ps1 -TargetUrl $env:TARGET_URL -VuCount 5000 -MaxInFlight 1000 -Profile burst -BurstCount 1000 -RunId $id
```

Sustained 5,000-user population for 10 minutes, maximum 1,000 requests in flight:

```powershell
$id = Get-Date -Format 'yyyyMMddTHHmmssfff'
.\run.ps1 -TargetUrl $env:TARGET_URL -VuCount 5000 -MaxInFlight 1000 -Profile sustained -DurationSeconds 600 -RunId $id
```

The generator records completed-request RPS separately from configured VUs and observed in-flight concurrency. Sustained results include p95 for the first and final halves of the run and their drift. Per-request response bodies are drained in chunks and not retained, allowing HTTP keep-alive without growing a response list in memory.

`run.ps1` validates inputs before starting Python, assigns the generator process to a Windows Job Object capped at 8 GB and 8 CPU equivalents, samples client RAM/CPU once a second, and stops the process below 2 GiB available host RAM. JSON and resource CSV output goes to the root `results/` folder, which Git ignores.
