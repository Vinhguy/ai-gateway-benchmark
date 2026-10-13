# Bifrost vs LiteLLM Latency Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not begin implementation until the human partner approves this written plan.

**Goal:** Build a standalone Git workspace that compares Bifrost and LiteLLM using direct HTTP requests to one mock provider. Represent 5,000 virtual users and cap simultaneous in-flight requests at 1,000; this is concurrency, not 1,000 requests per second.

**Architecture:** Both physical hosts run Windows. The Windows server hosts a capped Linux VM for the gateway stack, avoiding unsupported Docker Desktop on Windows Server. The local Windows machine runs a native Python asyncio/aiohttp generator inside a Windows Job Object. The generator creates 5,000 lightweight async user workers and never allows more than 1,000 in-flight requests. Gateways run sequentially.

**Tech Stack:** Hyper-V Linux VM; Linux Docker Compose v2; Bifrost v2.2.6; LiteLLM v1.105.0; Python 3.12 + pinned aiohttp; official `maximhq/bifrost-benchmarking` mocker pinned to a Git commit; Windows Job Objects for generator limits.

**Spec:** [2026-10-13-ai-gateway-benchmark-design.md](2026-10-13-ai-gateway-benchmark-design.md)

## Global Constraints

- Each Windows host has 16 GB RAM; reserve 5 GB for existing tasks. Cap benchmark workload at 8 GB, leaving about 3 GB headroom.
- Server VM: 8 GB maximum RAM and at most 9 logical CPUs. Inside the VM, mocker is capped at 1 GB / 1 CPU, selected gateway at 6 GB / 8 CPUs, leaving about 1 GB for Linux guest overhead. Use the VM memory cap as the outer limit.
- Local generator: Windows Job Object hard memory cap of 8 GB and CPU cap of 8 logical CPUs. Poll host available memory; abort below 2 GB.
- Server guard polls Linux `MemAvailable` and stops the selected gateway below 2 GiB. Do not start if already below the threshold.
- Use only the zero-latency mock provider, identical payload/model, retries disabled, keep-alive, discarded bodies, no per-request logging, and 2 to 5 seconds think time.
- Workload target: synchronized burst of 1,000 concurrent requests, then 10-minute sustained traffic with no more than 1,000 requests in flight while rotating the 5,000-user population. Do not claim 1,000 RPS unless the measured completion rate actually reaches it.

## Review Focus

- Server preflight confirms Windows edition, Hyper-V role, CPU virtualization, and enough memory. If Hyper-V cannot host the capped Linux VM, stop and revise instead of substituting unsupported Docker Desktop or raising resource caps.
- VM maximum is 8 GB; gateway and mocker hard caps total 7 GB. Tests/config review check these limits.
- Both gateway routes use the same mocker URL/model and disable retries.
- Generator config creates 5,000 async user workers but enforces a maximum of 1,000 in-flight HTTP requests, with no unbounded semaphore queue. Tests check the cap and synchronized 1,000-request burst.
- Results keep configured population, observed in-flight concurrency, RPS, and latency separate. Invalid resource/drop events cannot be reported as valid comparisons.

---

### Task 1: Create the standalone Git workspace and operator documentation

**Files:** `README.md`, `.gitignore`, `docs/2026-10-13-ai-gateway-benchmark-design.md`, `docs/2026-10-13-bifrost-litellm-latency-benchmark.md`.

**Interface:** New repository at `C:\code\vnm\ai-gateway-benchmark`, branch `benchmark-setup`, independent of the Odoo repo.

- [ ] After plan approval, create the directory and standalone Git repository; create branch `benchmark-setup`.
- [ ] Add this approved spec and plan, plus setup/run instructions, Windows/Hyper-V preflight, private-network setup, resource caps, and secrets policy.
- [ ] Create `.superpowers/sdd/2026-10-13-bifrost-litellm-latency-benchmark/progress.md` as the execution ledger before implementation tasks.
- [ ] Review Git status and confirm the new repo shares no Git metadata or working tree with the Odoo repo.
- [ ] Commit the docs and ledger.

### Task 2: Prepare the capped Linux gateway VM and server stack

**Files:** `server/compose.yaml`, `server/litellm/config.yaml`, `server/scripts/configure-bifrost.sh`, `server/scripts/guard-server.sh`, `server/scripts/select-gateway.sh`, `server/tests/ServerConfig.Tests.ps1`, `.gitmodules`, pinned `upstream-benchmarking` submodule.

**Interfaces:** Bifrost `http://<server-private-ip>:8080/v1/chat/completions`; LiteLLM `http://<server-private-ip>:4000/v1/chat/completions`; mocker `http://mocker:8000`; public model `openai/gpt-4o-mini`.

- [ ] Write tests first for guest/container memory and CPU limits, shared URL/model, disabled retries, selector validation, stop-before-switch, and low-memory refusal. Run them and observe expected failures before implementation.
- [ ] Document and verify Hyper-V and Linux VM prerequisites; set VM maximum to 8 GB and cap vCPU count at 9. Do not install Docker Desktop on Windows Server.
- [ ] Add the official mocker repo as a shallow submodule and pin the resolved Git commit.
- [ ] Define mocker at 1 GB / 1 CPU and each gateway at 6 GB / 8 CPUs. Only one gateway may be active.
- [ ] Configure both gateway routes to the same mocker and `openai/gpt-4o-mini`, with retries disabled and no real provider keys.
- [ ] Implement Linux memory guard startup and monitor modes using `/proc/meminfo`; refuse startup under 2 GiB and stop the active gateway if memory falls below 2 GiB.
- [ ] Implement `select-gateway.sh` to accept exactly `bifrost` or `litellm`, stop the previous gateway before switching, check memory, and start only the selected gateway. Require the monitor during a benchmark.
- [ ] Run Compose config validation and tests; smoke-test one request through each gateway and confirm both reach the same mock provider.
- [ ] Commit server configuration, VM instructions, selector, and tests.

### Task 3: Implement the direct Windows HTTP generator

**Files:** `client/pyproject.toml`, `client/loadgen.py`, `client/run.ps1`, `client/tests/test_loadgen.py`, `client/tests/test_runner.ps1`.

**Inputs:** `TARGET_URL`, `VU_COUNT` (1 to 5,000), `MAX_IN_FLIGHT` (1 to 1,000), `RAMP_DURATION`, `HOLD_DURATION`, `RUN_ID`. **Output:** `results/<RUN_ID>.json`.

- [ ] Write Python tests first: worker population and concurrency ceiling, 1,000 simultaneous start barrier, no unbounded pending-request queue, response-body discard, and latency/RPS measurement. Write PowerShell tests for input validation and memory-abort behavior.
- [ ] Implement the async generator with 5,000 lightweight worker coroutines and `aiohttp` keep-alive. The admission controller schedules at most 1,000 requests in flight; waiting users do not accumulate HTTP requests. Reuse the exact same worker behavior across gateway runs.
- [ ] Add a synchronized burst profile that releases exactly 1,000 workers together and records actual in-flight concurrency and response latency. Add a sustained profile that rotates the 5,000-user population, enforces the same 1,000-request cap, and sleeps 2 to 5 seconds after responses.
- [ ] Keep response bodies unread/discarded safely, validate HTTP status, and avoid request-level console output. Record errors, skipped/admission-delayed events, and completion counts.
- [ ] Implement a PowerShell launcher that validates inputs before starting Python, assigns the generator process to a Windows Job Object capped at 8 GB RAM / 8 logical CPUs, polls host available memory, and terminates the run under 2 GB available RAM.
- [ ] Verify unit tests, then run a 100-concurrency smoke and a synchronized 1,000-request burst. Check memory and metadata output.
- [ ] Commit the generator and launcher.

### Task 4: Run and report the fair comparison

**Files:** `docs/benchmark-method.md`, `results/.gitkeep`, updates to `README.md`, report-validity tests.

**Recorded dimensions:** gateway, configured VU population, max/observed in-flight requests, run ID, version pins, p50/p95/p99, RPS, successes/failures, queue/admission delays, and Windows/VM/container CPU/RAM.

- [ ] Add report validity tests: low-memory abort, memory-cap event, generator saturation, or dropped/skipped work marks a run invalid.
- [ ] Run direct-mocker baseline and 100-concurrency smoke; then run each gateway sequentially under identical caps.
- [ ] Run the 1,000-request synchronized burst three times per gateway, alternating gateway order.
- [ ] Run the sustained profile for 10 minutes with 5,000 configured async users and max 1,000 in flight, three trials per gateway with alternating order.
- [ ] Accept comparison only with >=99.9% successful responses, zero generator drops, resource limits intact, and p95 drift under 20% between first and final five-minute windows. Report achieved RPS separately.
- [ ] Keep raw result JSON out of Git; commit only sanitized aggregate reports if requested.
- [ ] Perform a fresh whole-workspace review, resolve critical/important findings, record deferred minor findings, and complete branch handoff without pushing remotely.

## Assumptions

- Both hosts are Windows with Hyper-V-capable editions and hardware virtualization enabled. If that is false for the server, pause before implementation and revise the runtime plan.
- The local host can run Python 3.12 and create Windows Job Objects; no Docker or k6 is needed on the client.
- Server private IP is configured by the operator and not committed. No remote Git host or push is assumed.
- Implementation starts only after explicit approval of this revised plan. Creating the target repo outside the current workspace will require filesystem escalation at that step.
