# AI Gateway Latency Benchmark

Compare Bifrost and LiteLLM against the same zero-latency mock provider. The load generator sends direct HTTP requests from native Windows Python; it does not use k6.

## Workload definition

- 5,000 async user workers represent the user population.
- At most 1,000 requests may be in flight at once.
- A synchronized 1,000-request burst is measured separately from the 10-minute sustained profile.
- 1,000 concurrent requests is not 1,000 requests per second. See the [design](docs/2026-10-13-ai-gateway-benchmark-design.md) for the exact workload and metrics.

## Host layout

Both physical hosts run Windows. The local Windows host runs the Python load generator. The server hosts a Linux VM for Docker Compose, Bifrost/LiteLLM, and the mock provider. The VM is capped at 8 GB RAM; the gateway and mocker limits total 7 GB, leaving guest overhead. Hyper-V and hardware virtualization must pass the preflight before setup. Docker Desktop is not used on Windows Server.

Each host has 16 GB RAM. Reserve 5 GB for other work, keep benchmark resources at or below 8 GB, and maintain the 2 GB available-memory abort threshold. Do not raise caps to make an invalid run pass.

## Documents

- [Design spec](docs/2026-10-13-ai-gateway-benchmark-design.md)
- [Implementation plan](docs/2026-10-13-bifrost-litellm-latency-benchmark.md)

The scripts and gateway stack will be added in the implementation tasks. The operator must configure the server's private IP locally; never commit credentials or `.env` files. Raw run JSON is ignored by Git.
