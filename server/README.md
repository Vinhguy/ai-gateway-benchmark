# Server gateway stack

Run the gateway stack inside the capped Linux VM on the Windows server. Both physical gateway services are Linux containers. The mocker is built from the pinned upstream submodule and remains internal to the Compose network.

## VM and network preflight

The server needs a Hyper-V-capable Windows edition, firmware virtualization enabled, and an available private virtual switch. Use the Xeon Gold 6130 server's capacity to assign at most 9 vCPUs to the VM. Allocate 8 GB RAM maximum to the Linux VM; within it, the mocker is limited to 1 GB and the selected gateway to 6 GB. Keep about 1 GB for the guest OS. Do not install Docker Desktop on Windows Server.

Install a supported Linux distribution in the VM and Docker Engine/Compose v2. Give it a private IP reachable from the load-generator Windows machine. On the Windows firewall and any network firewall, allow TCP 8080 (Bifrost) or TCP 4000 (LiteLLM) only from the load-generator IP. Do not publish port 8000; the mocker is reachable only inside Compose.

## Configure and start

1. Copy `.env.example` to `.env`; the checked-in values are test-only local keys. Keep `.env` untracked.
2. Run `docker compose -f compose.yaml config` to validate configuration.
3. Select exactly one gateway:

   ```bash
   ./scripts/select-gateway.sh bifrost
   # or, after the Bifrost container is stopped:
   ./scripts/select-gateway.sh litellm
   ```

4. In a second terminal, run `./scripts/guard-server.sh monitor`. It stops the active gateway if guest `MemAvailable` falls below 2 GiB. Stop this monitor with Ctrl+C after the run.
5. From the local Windows machine, target `http://<server-private-ip>:8080/v1/chat/completions` or port 4000 for LiteLLM.

The selector removes any previous gateway container before starting the requested one. Do not bypass it with manual `docker compose up` commands. Results are comparable only when both gateways use the same Compose and mocker versions, limits, and load profile.
