---
name: brain-pi-loop
description: Provides a provider-neutral Brain-to-Pi execution and independent-review protocol. Use when Codex, Claude, or another capable agent should plan and judge while Pi Agent performs bounded implementation, commands, or tests, especially when compact JSON handoff, session resume, portable setup, or a host-bundled Pi executable is involved.
---

# Brain × Pi 协作闭环

## Core principle

Keep judgment and execution separate. The brain agent owns objectives, falsifiers, permissions, independent verification, and delivery. Pi owns bounded execution. Treat Pi's report as evidence, never as the acceptance verdict.

The brain's context is the scarce resource: every brain turn carries it again. Spend it on objectives, decisions and findings, and push reading, running and first-pass review to the executor. Count the brain's turns and reads, not the executor's tokens.

## First use

Run `pi-compact doctor` if installed. Otherwise read [references/setup.md](references/setup.md), run `scripts/install.py`, then verify `pi --version` and `pi-compact doctor`.

The protocol is provider-neutral. Configure any Pi provider/model; load provider-specific credentials only through environment variables or an OS secret store.
If a provider or model ID is not confirmed, run `pi --list-models <search>` or inspect existing Pi configuration. Never invent an ID.

## Model routing

The brain agent owns model selection and may switch models without pausing for
user approval solely because a provider is unavailable, over quota, or less
suited to the task. Default to DeepSeek when it is available and sufficient,
unless the user explicitly pins a model for the current task.

Select by current, verified capability rather than model reputation or a stale
label. Until reverified otherwise, treat DeepSeek as text-only with no native
multimodal input. When a task contains images, audio, or video:

1. Prefer purpose-built tools to inspect, OCR, extract, or transcribe the media,
   then give the executor the smallest useful textual or structured context.
2. If native multimodal reasoning is materially necessary, automatically choose
   an authorized model that supports the required modality.
3. Never send unsupported media to a text-only model or pretend that filenames,
   OCR, or a partial transcript prove the full media contents.

Autonomous model routing does not broaden credential authority. Never copy or
reuse another person's OAuth, API key, Access session, or owner runtime. If no
authorized capable model or media-reading tool is available, report that real
blocker instead of fabricating support. Include the effective executor model
and any media-extraction coverage limits in the compact handoff.

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

   Keep stable project rules and history in a repository file the executor reads (a state or handoff doc). The contract then carries only the task delta and path references. Ask for a HANDOFF that maps each falsifier to its evidence: a test name or `file:line`, and each command with its one-line result.
3. For architectural or ambiguous work, make phase 1 a design checkpoint: the executor writes a bounded plan file and ends its turn. Review that file, then resume the same session to implement. A design error then costs one short review instead of a rewrite.
4. Use a worktree only when parallel writers or unrelated user changes require isolation; otherwise work in the checkout the user expects. Preserve unrelated user changes.
5. Start one named Pi session per task with only the required tools, detached from the brain's shell, from a background shell:

```sh
python3 scripts/pi_loop.py run --session <name> --contract <file> --out <result.json> -- --tools read,grep,find,ls,bash,edit,write
```

   It runs `pi-compact` in its own session with stdin from the null device (Pi waits for EOF on a non-TTY stdin) and prints one compact handoff when the executor stops. Add `--resume` to continue a session and `--idle-timeout <s>` as a last-resort safety net. Wait for the completion notification instead of polling. If the waiter dies, the executor keeps running; `pi_loop.py result <result.json>` prints the handoff later.
6. Read only the compact result. Never ingest raw Pi JSONL, thinking deltas, signatures, or full tool output into the brain context. To relay an earlier session, run `pi_loop.py digest <session>`: it prints the prompts and the final reply, truncated.
7. Review by evidence. Run the verification gates yourself and read their one-line results. Read the ranges the handoff anchors, plus the invariants with the highest risk, not the whole diff. When the diff is too large to read cheaply, start a fresh read-only Pi reviewer session with the contract and the diff range. Ask for severity-ranked findings with anchors, and confirm each finding at its anchor before you act on it. The reviewer's report is evidence too.
8. If findings remain, resume the executor's session with them (`--resume`). Re-review after each correction.
9. Deliver only when the falsifier is defeated and required verification is current. Report unverified gaps explicitly.

## Native harness first

When the executor model ships with its own agent harness, run it there instead of through Pi. The model is tuned for its native tools, and its harness handles retries and compaction, so the brain spends less context nursing the run. For OpenAI models (a Codex login) that is `codex exec`. Pi stays the harness for providers without one, such as DeepSeek, Qwen, Kimi and GLM.

Use the Codex app's bundled CLI (`~/.codex/plugins/.plugin-appserver/codex-cli/bin/codex`). An outdated global `codex` cannot serve current models, and on 2026-10-13 it rewrote the default model in `~/.codex/config.toml` on start.

```sh
codex exec -C <worktree> --json --output-schema templates/handoff.schema.json -o <final.json> "<contract>" > <events.jsonl>
codex exec --skip-git-repo-check --json -o <final.json> resume <thread_id> "<findings>" >> <events.jsonl>
```

- `thread_id` comes from the first `thread.started` event.
- The schema-shaped final message is the compact handoff. Never read the events file whole.
- The workflow above still applies: the contract, independent review, and resuming the same session for corrections.

## Permission profiles

| Phase | Pi tools |
|---|---|
| Research/review | `read,grep,find,ls` |
| Implementation | add only needed `bash,edit,write` |
| Destructive/external action | require explicit user authority first |

## Common mistakes

- Hard-coding any provider into the supervision protocol.
- Guessing provider/model IDs instead of discovering the target Pi configuration.
- Asking the user to approve routine model fallback when the user did not pin a model.
- Sending image, audio, or video directly to DeepSeek without current proof of native support.
- Assuming a host application's bundled Pi path is stable.
- Letting the executor self-certify completion.
- Passing raw streaming JSON into the brain context.
- Putting API keys in prompts, task files, config JSON, logs, or shell history.
- Starting a fresh Pi session for review corrections and losing execution context.
- Polling a running executor or reading its session file instead of waiting for the notification.
- Restating repository rules and history in every contract instead of pointing to the file that holds them.
- Reading a whole diff when anchored evidence and the gates decide the review.

For configuration schema, OS-specific setup, migration paths, and compact output fields, read [references/setup.md](references/setup.md).

## Request reliability and recovery

Use the shared installed `pi` / `pi-compact` entrypoint and `pi-compact doctor`
to verify the effective executable. A version number alone does not prove that
the launched module graph contains the managed transport and retry policy.
Do not cache a host application's bundled executable in one-off runner scripts.

Request cancellation, response-header deadlines and stream-idle deadlines
belong to the model transport. Agent silence is not proof of a dead request:
the model may be reasoning or a tool may still be running. A process watchdog
is only a final safety net and must not be the normal recovery mechanism.
Keep one bounded retry owner; do not nest an unlimited launcher restart loop
around the provider's own retries. Do not retry an expired credential as a
network error or replay completed external actions after an ambiguous failure.

The compact handoff preserves at most five sanitized failure records and a
retry count, including when a later retry succeeds. Use `code`, `phase`,
`retryable` and `requestId` to select recovery; unknown transport evidence stays
unknown. Resume the existing session only after inspecting completed tool
results and current workspace state. Preserve the same authority and tool scope.
