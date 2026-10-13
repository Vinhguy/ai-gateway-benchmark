# Bifrost vs LiteLLM Latency Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not begin implementation until the human partner approves this written plan.

**Goal:** Build a standalone Git workspace that compares Bifrost and LiteLLM using direct HTTP requests to one mock provider. Represent 5,000 virtual users and cap simultaneous in-flight requests at 1,000; this is concurrency, not 1,000 requests per second.

**Architecture:** Both physical hosts run Windows. The Windows server hosts a capped Linux VM for the gateway stack, avoiding unsupported Docker Desktop on Windows Server. The local Windows machine runs a native Python asyncio/aiohttp generator inside a Windows Job Object. The generator creates 5,000 lightweight async user workers and never allows more than 1,000 in-flight requests. Gateways run sequentially.

**Tech Stack:** Hyper-V Linux VM; Linux Docker Compose v2; Bifrost v2.2.6; LiteLLM v1.105.0; Python 3.12 + pinned aiohttp; official `maximhq/bifrost-benchmarking` mocker pinned to a Git commit; Windows Job Objects for generator limits.

**Spec:** [2026-10-13-ai-gateway-benchmark-design.md](2026-10-13-ai-gateway-benchmark-design.md)

## Global Constraints

- Each Windows host has 16 GB RAM; reserve 5 GB for existing tasks. Cap benchmark workload at 8 GB, leaving about 3 GB headroom.
- Server VM: 8 GB maximum RAM and at most 9 logical CPUs. Inside the VM, mocker is capped at 1 GB / 1 CPU, selected gateway at 6 GB / 8 CPUs, leaving about 1 GB for Linux guest overhead. Use the VM memory cap as the outer limit. A Windows host monitor powers off the VM if physical available RAM falls below 2 GiB.
- Local generator: Windows Job Object hard memory cap of 8 GB and CPU cap of 8 logical CPUs. Poll host available memory; abort below 2 GB.
- Server guard polls Linux `MemAvailable` and stops the selected gateway below 2 GiB. Do not start if already below the threshold.
- Use only the zero-latency mock provider, identical payload/model, retries disabled, keep-alive, discarded bodies, no per-request logging, and 2 to 5 seconds think time.
- Workload target: synchronized burst of 1,000 concurrent requests, then 10-minute sustained traffic with no more than 1,000 requests in flight while rotating the 5,000-user population. Do not claim 1,000 RPS unless the measured completion rate actually reaches it.

## Review Focus

- Server preflight confirms Windows edition, Hyper-V role, CPU virtualization, and enough memory. If Hyper-V cannot host the capped Linux VM, stop and revise instead of substituting unsupported Docker Desktop or raising resource caps.
- Both Windows host available RAM and Linux guest `MemAvailable` are monitored; Windows stops the VM and Linux stops the active gateway under 2 GiB.
- VM maximum is 8 GB; gateway and mocker hard caps total 7 GB. Tests/config review check these limits.
- Both gateway routes use the same mocker URL/model and disable retries.
- Generator config creates 5,000 async user workers but enforces a maximum of 1,000 in-flight HTTP requests, with no unbounded semaphore queue. Tests check the cap and synchronized 1,000-request burst.
- Results keep configured population, observed in-flight concurrency, RPS, and latency separate. Invalid resource/drop events cannot be reported as valid comparisons.

---

### Task 1: Create the standalone Git workspace and operator documentation

**Files:** `README.md`, `.gitignore`, `docs/2026-10-13-ai-gateway-benchmark-design.md`, `docs/2026-10-13-bifrost-litellm-latency-benchmark.md`.

**Interface:** New public GitHub repository `ai-gateway-benchmark`, checked out locally at `C:\code\vnm\ai-gateway-benchmark`, branch `benchmark-setup`, independent of the Odoo repo.

- [x] After plan approval, create the directory and standalone Git repository; create branch `benchmark-setup`.
- [x] Add this approved spec and plan, plus setup/run instructions, Windows/Hyper-V preflight, private-network setup, resource caps, and secrets policy.
- [ ] Create `.superpowers/sdd/2026-10-13-bifrost-litellm-latency-benchmark/progress.md` as the execution ledger before implementation tasks.
- [x] Review Git status and confirm the new repo shares no Git metadata or working tree with the Odoo repo.
- [x] Commit the docs and project files; the SDD execution ledger remains ignored because the required helper marks its `.superpowers/sdd` directory self-ignoring.

### Task 2: Prepare the capped Linux gateway VM and server stack

**Files:** `server/compose.yaml`, `server/litellm/config.yaml`, `server/scripts/configure-bifrost.sh`, `server/scripts/guard-server.sh`, `server/scripts/select-gateway.sh`, `server/windows/Watch-BenchmarkVm.ps1`, `server/tests/ServerConfig.Tests.ps1`, `.gitmodules`, pinned `upstream-benchmarking` submodule.

**Interfaces:** Bifrost `http://<server-private-ip>:8080/v1/chat/completions`; LiteLLM `http://<server-private-ip>:4000/v1/chat/completions`; mocker `http://mocker:8000`; public model `openai/gpt-4o-mini`.

- [x] Write tests first for guest/container memory and CPU limits, shared URL/model, disabled retries, selector validation, stop-before-switch, and low-memory refusal. Run them and observe expected failures before implementation.
- [x] Document Hyper-V and Linux VM prerequisites; cap VM memory at 8 GB and vCPU count at 9. Do not install Docker Desktop on Windows Server.
- [x] Add the official mocker repo as a submodule and pin resolved commit `2c416fb234bf4abac25cf61f4470fc2528362afd`.
- [x] Define mocker at 1 GB / 1 CPU and each gateway at 6 GB / 8 CPUs. Only one gateway may be active.
- [x] Configure both gateway routes to the same mocker and `openai/gpt-4o-mini`, with retries disabled and no real provider keys.
- [x] Implement Linux memory guard startup and monitor modes; refuse startup under 2 GiB and stop the active gateway if memory falls below 2 GiB.
- [x] Implement and test a Windows host monitor that checks physical `FreePhysicalMemory` and powers off the benchmark VM below 2 GiB.
- [x] Implement `select-gateway.sh` to accept exactly `bifrost` or `litellm`, stop the previous gateway before switching, check memory, and start only the selected gateway.
- [x] Validate Compose profiles and run PowerShell configuration tests. **Deferred:** request smoke through both gateway containers because Docker daemon and server VM are unavailable in this environment.
- [x] Commit server configuration, VM instructions, selector, and tests.

### Task 3: Implement the direct Windows HTTP generator

**Files:** `client/pyproject.toml`, `client/loadgen.py`, `client/run.ps1`, `client/tests/test_loadgen.py`, `client/tests/test_runner.ps1`.

**Inputs:** `TARGET_URL`, `VU_COUNT` (1 to 5,000), `MAX_IN_FLIGHT` (1 to 1,000), `RAMP_DURATION`, `HOLD_DURATION`, `RUN_ID`. **Output:** `results/<RUN_ID>.json`.

- [x] Write Python tests first for worker population and concurrency ceiling, 1,000 simultaneous start barrier, response-body draining, and latency/RPS measurement. Write PowerShell tests for input validation; low-memory abort handling is validated in the report suite.
- [x] Implement the async generator with 5,000 lightweight worker coroutines and `aiohttp` keep-alive. The admission controller schedules at most 1,000 requests in flight.
- [x] Add synchronized burst and sustained profiles with the shared 1,000-request cap and 2–5 second think time.
- [x] Drain response bodies safely, validate HTTP status, and record errors, admission delay, completions, and gateway/mocker version metadata.
- [x] Implement the PowerShell launcher with input validation, an 8 GB / 8-core Windows Job Object cap, host-memory monitoring, and abort below 2 GB available RAM.
- [x] Verify Python tests and Windows launcher tests. **Deferred:** live 100-concurrency and 1,000-request gateway tests because no gateway target is running here.
- [x] Commit the generator and launcher.

### Task 4: Run and report the fair comparison

**Files:** `docs/benchmark-method.md`, `results/.gitkeep`, updates to `README.md`, `client/report.py`, report-validity tests.

**Recorded dimensions:** gateway, configured VU population, max/observed in-flight requests, run ID, version pins, p50/p95/p99, RPS, successes/failures, queue/admission delays, and Windows/VM/container CPU/RAM.

- [x] Add report validity tests: low-memory abort, memory-cap event, generator saturation, and dropped work mark a run invalid.
- [x] Document the direct-mocker baseline, gateway order, sustained trials, and comparison acceptance rules. **Deferred:** actual trials require the user's Windows server and local machine.
- [x] Enforce 99.9% success, zero drops, resource limits, version metadata, and report p95 drift for comparison acceptance.
- [x] Keep raw result JSON and CSV out of Git; no aggregate trial report exists yet.
- [ ] Perform a fresh whole-workspace review and resolve any critical/important findings.
- [ ] Copy into `C:\code\vnm\ai-gateway-benchmark`, create the public GitHub repository, and push branch `benchmark-setup` (user requested publication).

## Assumptions

- Both hosts are Windows with Hyper-V-capable editions and hardware virtualization enabled. If that is false for the server, pause before implementation and revise the runtime plan.
- The local host can run Python 3.12 and create Windows Job Objects; no Docker or k6 is needed on the client.
- Server private IP is configured by the operator and not committed. GitHub public was selected by the user; publish as `ai-gateway-benchmark`.
- Implementation starts only after explicit approval of this revised plan. Creating the target repo outside the current workspace will require filesystem escalation at that step.
