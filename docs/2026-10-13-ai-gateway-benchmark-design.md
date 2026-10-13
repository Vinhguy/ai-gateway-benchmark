# Bifrost and LiteLLM Latency Benchmark Design

## Goal

Create a separate, reproducible Git workspace to compare Bifrost and LiteLLM request latency through the same mock LLM provider, without sending paid requests to a real provider.

## Workload meaning

The test represents a population of 5,000 virtual users (5,000 lightweight async client workers over the run). At most 1,000 HTTP requests may be in flight at the same time. A synchronized burst phase makes 1,000 users send together; the remaining users do not create an unbounded request queue. A sustained phase rotates the 5,000-user population through groups of at most 1,000 active request workers, with 2 to 5 seconds of think time after each response.

This means 1,000 concurrent in-flight requests, not 1,000 requests per second. RPS is measured from completed requests and depends on response latency and think time. The report keeps concurrency, RPS, and latency as separate metrics.

## Audience and workflow

Both the local load-generator machine and the server run Windows. A native Windows async HTTP generator sends requests over a private network to the server. The server runs one gateway and the mock provider in an isolated Linux VM on Hyper-V. Before implementation, check the Windows edition, Hyper-V role, and hardware virtualization. If no supported Linux VM runtime is available, stop and revise the deployment plan rather than silently changing resource limits.

## Resource limits

Each host has 16 GB RAM, with 5 GB reserved for other tasks. Keep the benchmark workload under 8 GB aggregate, leaving about 3 GB margin:

- Server: Linux VM maximum 8 GB RAM. Inside it, the selected gateway has a 6 GB hard limit and 8 CPU limit; the mock provider has a 1 GB hard limit and 1 CPU limit, leaving about 1 GB for Linux overhead. Gateways run sequentially.
- Local Windows generator: run the native async client in a Windows Job Object capped at 8 GB and 8 CPUs. The script itself should stay far below that ceiling; stop the run if available host RAM falls below 2 GB.
- The server guard monitors available memory and stops the active gateway if Linux `MemAvailable` falls below 2 GiB. VM and process limits remain in force regardless of the monitor.

The required workload is a synchronized 1,000-request burst and a 10-minute sustained phase with up to 1,000 in-flight requests while rotating the 5,000-user population. A 5,000-request simultaneous burst is not implied by the 5,000-user population and is out of scope unless separately approved.

## Architecture

Use a Linux VM on the Windows server for Compose services: Bifrost, LiteLLM, and the official Bifrost benchmark mocker. Pin gateway versions and the mocker Git submodule commit. Both gateways route the same model to the same zero-latency mocker. On the Windows local host, use a small Python asyncio + aiohttp direct HTTP generator, not k6 and not one OS thread per user. Configure 5,000 async user workers, a maximum of 1,000 in-flight HTTP requests, identical request payloads, keep-alive, discarded response bodies, and 2 to 5 seconds think time. Run a direct-to-mocker baseline, then each gateway sequentially.

## Metrics and acceptance

Record configured VU population, maximum and observed in-flight requests, p50/p95/p99 latency, RPS, success/failure counts, skipped/admission-delayed requests, and Windows/VM/container CPU and RAM. The 1,000-concurrency run is valid only with at least 99.9% successful responses, no generator drops, host RAM above the safety threshold, no memory-cap event, no generator CPU saturation, and p95 drift below 20% between the first and final five-minute windows. Report RPS as an observed outcome, never as a synonym for VU count.

## Out of scope

No real model provider, public-facing deployment, gateway feature tuning, streaming benchmark, 5,000 simultaneous in-flight requests, or publishing results to an external service.
