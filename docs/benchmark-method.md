# Benchmark method

## Before each trial

1. Confirm the load generator and server VM have the planned 8 GiB caps and the 2 GiB host/guest free-memory guards are running.
2. Start the server resource sampler with the run ID, then start the Windows VM monitor with the same ID. The Windows host monitor CSV is required evidence alongside client and Linux guest/container CSVs.
3. Stop the previously selected gateway and use `server/scripts/select-gateway.sh` to start only the gateway being measured.
4. Wait for startup and warm-up requests to finish. Use the same payload, model, request timeout, client, network path, mocker commit, and resource caps for both gateways.
5. Run `client/report.py` with the result, client CSV, server CSV, Windows server-host CSV, and abort marker paths. Compare only results whose validation JSON says `valid: true`.

## Trial sequence

- First run direct mocker and a small 100 in-flight smoke to verify the client path and request shape. These are diagnostics, not gateway scores.
- Run three 1,000-request synchronized bursts per gateway, alternating order (Bifrost, LiteLLM, LiteLLM, Bifrost, Bifrost, LiteLLM).
- Run three 10-minute sustained trials per gateway with 5,000 async workers, at most 1,000 in-flight requests, and 2 to 5 seconds think time. Alternate gateway order using the same sequence.
- Use a unique run ID per trial and preserve the client/server CSV files together with the result JSON outside Git.

## Validity and comparison

A run is invalid if it is not the full 5,000-user/1,000-in-flight comparison profile, lacks client/guest/server-host resource evidence, or any resource CSV has fewer than 80% of expected one-second samples or covers less than 80% of the run. It is also invalid if it has an abort or memory-cap event, any host/guest available-memory sample below 2 GiB, a generator process at 95% of its 8 GiB cap, generator CPU at 7.6 core-equivalents or above, mocker CPU at 95% of its 1-core cap, gateway CPU at 95% of its 8-core cap, an observed in-flight count above its configured limit, any dropped work, success below 99.9%, or missing gateway/mocker version metadata. Burst comparison trials must complete 1,000 requests and observe 1,000 in flight. Sustained trials must last 10 minutes and have p95 drift under 20%. Do not silently remove failed requests when calculating success rate.

For each profile and gateway, report each trial and the median of valid trials for p50/p95/p99 latency, achieved RPS, success rate, maximum observed concurrency, admission delay, and resource use. Report burst and sustained results separately. Sustained RPS counts responses completed before the hold deadline divided by the hold duration; later drain completions remain in total success/error counts but not the RPS numerator. A sustained comparison is accepted only if p95 drift from the first five minutes to the final five minutes is under 20% for every included trial. The configured 5,000-user population is not a throughput claim; achieved RPS is measured completions divided by elapsed hold seconds.

No gateway-level numbers are checked into this repository until trials have actually run and the owner requests a sanitized aggregate report. Raw requests use only the local mock provider and test-only credentials.
