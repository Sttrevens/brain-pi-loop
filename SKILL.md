---
name: brain-pi-loop
description: Provides a provider-neutral Brain-to-Pi execution and independent-review protocol. Use when Codex, Claude, or another capable agent should plan and judge while Pi Agent performs bounded implementation, commands, or tests, especially when compact JSON handoff, session resume, portable setup, or a host-bundled Pi executable is involved.
---

# Brain × Pi 协作闭环

## Core principle

Keep judgment and execution separate. The brain agent owns objectives, falsifiers, permissions, independent verification, and delivery. Pi owns bounded execution. Treat Pi's report as evidence, never as the acceptance verdict.

## First use

Run `pi-compact doctor` if installed. Otherwise read [references/setup.md](references/setup.md), run `scripts/install.py`, then verify `pi --version` and `pi-compact doctor`.

The protocol is provider-neutral. Configure any Pi provider/model; load provider-specific credentials only through environment variables or an OS secret store.
If a provider or model ID is not confirmed, run `pi --list-models <search>` or inspect existing Pi configuration. Never invent an ID.

## Workflow

1. Inspect the real workspace, repository instructions, current state, and user authority before dispatch.
2. Frame a compact execution contract:

```text
OBJECTIVE: observable end state
FALSIFIER: evidence that proves the change is wrong or incomplete
SCOPE: allowed paths and systems
AUTHORITY: allowed mutations; forbidden destructive or external actions
VERIFY: exact tests, runtime checks, and evidence
HANDOFF: changed paths, commands/results, risks, and remaining gaps
```

3. Isolate execution in a worktree or bounded directory when practical. Preserve unrelated user changes.
4. Start one named Pi session per task. Allow only required tools. Example:

```sh
pi-compact --session-id task-slug --tools read,grep,find,ls,bash,edit,write "<contract>"
```

5. Read only the compact result. Never ingest raw Pi JSONL, thinking deltas, signatures, or full tool output into the brain context.
6. Independently inspect actual state: targeted diff/status, relevant contracts, tests, runtime, and authority boundaries. Do not limit review to Pi's diff summary.
7. If findings remain, resume the returned session with `pi-compact --session <sessionId> "<findings>"`. Re-review after each correction.
8. Deliver only when the falsifier is defeated and required verification is current. Report unverified gaps explicitly.

## Permission profiles

| Phase | Pi tools |
|---|---|
| Research/review | `read,grep,find,ls` |
| Implementation | add only needed `bash,edit,write` |
| Destructive/external action | require explicit user authority first |

## Common mistakes

- Hard-coding any provider into the supervision protocol.
- Guessing provider/model IDs instead of discovering the target Pi configuration.
- Assuming a host application's bundled Pi path is stable.
- Letting the executor self-certify completion.
- Passing raw streaming JSON into the brain context.
- Putting API keys in prompts, task files, config JSON, logs, or shell history.
- Starting a fresh Pi session for review corrections and losing execution context.

For configuration schema, OS-specific setup, migration paths, and compact output fields, read [references/setup.md](references/setup.md).
