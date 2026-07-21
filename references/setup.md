# Portable setup reference

## Components

- `scripts/pi_bridge.py`: discovers the real Pi executable, securely injects an optional provider credential, and exposes raw `pi` plus compact `pi-compact` behavior.
- `scripts/install.py`: installs user-local commands and writes a secret-free config.
- `scripts/test_*.py`: standard-library regression tests.

The skill follows the open [Agent Skills specification](https://agentskills.io/specification). Copy the whole skill directory to an Agent Skills-compatible runtime. Claude Code currently discovers personal skills at `~/.claude/skills/<name>/SKILL.md`; Codex uses its configured skills directory, commonly `~/.codex/skills/<name>/SKILL.md`.

## Install sequence

1. Find Pi without assuming a provider:

```sh
command -v pi
pi --version
```

If absent, locate a host-bundled Pi or install Pi using that distribution's supported method. Pass the real executable to the installer; never point it at the bridge being installed.

Treat a host-bundled Pi as a discovery or bootstrap source, not a durable runtime. For a reproducible personal installation, pin the discovered package version into a user-owned, versioned directory and expose a stable `runtime-current` link. On macOS or Linux with Node 22.19 or newer:

```sh
PI_RUNTIME_VERSION="$(pi --version)"
PI_RUNTIME_ROOT="$HOME/.local/share/pi-supervisor/runtimes/pi-$PI_RUNTIME_VERSION"
npm install --global --ignore-scripts \
  --prefix "$PI_RUNTIME_ROOT" \
  "@earendil-works/pi-coding-agent@$PI_RUNTIME_VERSION"
ln -s "$PI_RUNTIME_ROOT" "$HOME/.local/share/pi-supervisor/runtime-current"
```

Verify the version and provider/model catalog from `runtime-current/bin/pi` before configuring the bridge. Install upgrades side by side, validate them first, and then replace only the stable link. Keep the previous version until the new runtime completes a real provider call. On Windows, use an equivalent user-owned npm prefix and point `realPi` at its generated `pi.cmd`.

2. Run the tests:

```sh
python3 scripts/test_pi_bridge.py
python3 scripts/test_install.py
```

3. Install user-local commands:

```sh
python3 scripts/install.py \
  --real-pi /absolute/path/to/real/pi \
  --provider provider-id \
  --model model-id \
  --thinking high
```

Add `--credential-env PROVIDER_API_KEY` only when the provider needs it. Configure the OS secret adapter below rather than storing its value in JSON.

4. Open a new shell and verify:

```sh
pi --version
pi-compact doctor
pi-compact --no-tools --no-session "Reply exactly: PI_BRIDGE_OK"
```

## Configuration

Default path:

- macOS/Linux: `~/.config/pi-supervisor/config.json`
- Windows: `%APPDATA%\pi-supervisor\config.json`
- Override: `PI_SUPERVISOR_CONFIG`

Supported fields:

```json
{
  "realPi": "/absolute/path/to/real/pi",
  "provider": "provider-id",
  "model": "model-id",
  "thinking": "high",
  "credentialEnv": "PROVIDER_API_KEY",
  "secretService": "pi-supervisor.provider-id",
  "secretAccount": "local-user",
  "secretCommand": ["secure-store-cli", "read", "item-name"]
}
```

Never add a credential value to this file. `secretCommand` must be an argument array, not a shell string.

## OS adapters

### macOS

The bridge reads Keychain when `secretService` and `secretAccount` are configured. To migrate an existing shell variable into Keychain and remove matching assignments from common shell config/history files:

```sh
python3 scripts/install.py \
  --real-pi /absolute/path/to/real/pi \
  --provider provider-id --model model-id --thinking high \
  --credential-env PROVIDER_API_KEY \
  --secret-service pi-supervisor.provider-id \
  --secret-account local-user \
  --migrate-shell-secret PROVIDER_API_KEY
```

Migration is not key rotation. If the old value appeared in history or logs, revoke it with the provider and replace the Keychain item with a newly issued value.

### Linux

The bridge reads Secret Service through `secret-tool` when available and when `secretService`/`secretAccount` are configured. Otherwise inject the provider variable through the machine's approved secret manager or configure `secretCommand`.

### Windows

Run the installer from Python; it creates user-local `.cmd` launchers. Add that directory to the user PATH. Use a credential manager that can return the secret non-interactively and configure it as `secretCommand`, or inject the provider environment variable through the approved host mechanism. Do not store it in the launcher.

## Compact output

`pi-compact` forces Pi `--mode json --print`, consumes the stream locally, and emits one compact JSON object:

```json
{
  "status": "ok",
  "sessionId": "task-id",
  "provider": "provider-id",
  "model": "model-id",
  "stopReason": "stop",
  "usage": {"totalTokens": 1234},
  "tools": [{"name": "bash", "ok": true}],
  "final": "concise executor handoff",
  "exitCode": 0
}
```

Thinking, signatures, tool arguments, and tool results are intentionally discarded. Independently inspect the workspace for review evidence.
