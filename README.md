# AI Gateway Latency Benchmark

Compare Bifrost and LiteLLM against the same zero-latency mock provider. The load generator sends direct HTTP requests from native Windows Python; it does not use k6.

Public repository: [Vinhguy/ai-gateway-benchmark](https://github.com/Vinhguy/ai-gateway-benchmark), branch `benchmark-setup`.

## Workload definition

- 5,000 async user workers represent the user population.
- At most 1,000 requests may be in flight at once.
- A synchronized 1,000-request burst is measured separately from the 10-minute sustained profile.
- 1,000 concurrent requests is not 1,000 requests per second. See the [design](docs/2026-10-13-ai-gateway-benchmark-design.md) for the exact workload and metrics.

## Host layout

Both physical hosts run Windows. The local Windows host runs the Python load generator. The server hosts a Linux VM for Docker Compose, Bifrost/LiteLLM, and the mock provider. The VM is capped at 8 GB RAM; the gateway and mocker limits total 7 GB, leaving guest overhead. Hyper-V and hardware virtualization must pass the preflight before setup. Docker Desktop is not used on Windows Server.

Each host has 16 GB RAM. Reserve 5 GB for other work, keep benchmark resources at or below 8 GB, and maintain the 2 GB available-memory abort threshold. Do not raise caps to make an invalid run pass.

## Run the client

Install Python 3.12 on the local Windows machine, then from `client/`:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
```

Run a synchronized 1,000 request burst against one gateway (replace the private server IP):

```powershell
$id = "bifrost-burst-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\run.ps1 -TargetUrl "http://192.168.1.50:8080/v1/chat/completions" `
  -Gateway bifrost -VuCount 5000 -MaxInFlight 1000 -Profile burst `
  -BurstCount 1000 -RunId $id
```

For LiteLLM use port `4000` and `-Gateway litellm`. Run gateways sequentially. The sustained profile defaults to 10 minutes; use `-Profile sustained -VuCount 5000 -MaxInFlight 1000`. Each run writes JSON plus client resource CSV under `results/`. The server's `sample-resources.sh` writes a server CSV with the same run ID. Validate the run before comparing:

```powershell
.venv\Scripts\python .\report.py ..\results\$id.json `
  --client-resources ..\results\$id-client-resources.csv `
  --server-resources ..\server\results\$id-server-resources.csv `
  --server-host-resources ..\server\results\$id-windows-host-resources.csv `
  --abort-event ..\results\$id-abort.json
```

The validator writes `*-validation.json` and exits nonzero if workload shape is incomplete, resource evidence is missing, success is below 99.9%, work was dropped, resource thresholds were crossed, sustained p95 drift is 20% or higher, or required pin metadata is missing. Result JSON records gateway versions and the checked out mocker submodule commit. Direct-mocker runs are useful for measuring client overhead, not gateway comparison.

## Run guides

- [Local Windows guide](docs/huong-dan-local.md)
- [Server AI installation runbook](docs/huong-dan-server-ai.md)

## Documents

- [Design spec](docs/2026-10-13-ai-gateway-benchmark-design.md)
- [Implementation plan](docs/2026-10-13-bifrost-litellm-latency-benchmark.md)

The operator must configure the server's private IP locally; never commit credentials or `.env` files. Raw run JSON and CSV resource traces are ignored by Git.
