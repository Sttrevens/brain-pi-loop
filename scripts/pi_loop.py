#!/usr/bin/env python3
"""Brain-side helpers that keep a Pi run out of the brain's context.

run     Start pi-compact in its own session with stdin from the null device,
        wait for it, and print one compact handoff. The executor survives the
        brain's shell; if the waiter dies, the handoff still lands in --out.
result  Print the handoff stored in an --out file.
digest  Print a bounded summary of an existing Pi session, for relaying it.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SESSIONS_ROOT = Path.home() / ".pi" / "agent" / "sessions"
HEADER_KEYS = ("status", "reason", "sessionId", "provider", "model", "stopReason",
               "retryCount", "exitCode", "error", "diagnostic")


def session_file(name, root=SESSIONS_ROOT):
    """Newest session file for a session name or id, or None."""
    matches = sorted(Path(root).glob(f"*/*_{name}.jsonl"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def _size(path):
    return path.stat().st_size if path else -1


def _stop(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


def run(name, contract, out, *, resume=False, idle_timeout=None, extra=(),
        executable="pi-compact", sessions_root=SESSIONS_ROOT, poll_seconds=30):
    """Run one executor turn. Returns the compact result dict.

    idle_timeout is a last-resort safety net measured on session-file growth;
    request deadlines belong to the model transport, not to this waiter.
    """
    out = Path(out)
    prompt = Path(contract).read_text(encoding="utf-8")
    args = [executable, "--session" if resume else "--session-id", name, *extra, prompt]
    detach = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    with open(out, "w", encoding="utf-8") as stdout, \
            open(f"{out}.err", "w", encoding="utf-8") as stderr:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=stdout,
                                   stderr=stderr, **detach)
    last_size = _size(session_file(name, sessions_root))
    last_change = time.monotonic()
    while True:
        try:
            process.wait(timeout=poll_seconds)
            break
        except subprocess.TimeoutExpired:
            pass
        size = _size(session_file(name, sessions_root))
        if size != last_size:
            last_size, last_change = size, time.monotonic()
        elif idle_timeout and time.monotonic() - last_change > idle_timeout:
            _stop(process)
            result = {"status": "watchdog_killed",
                      "reason": f"session file idle for {idle_timeout}s", "sessionId": name}
            out.write_text(json.dumps(result), encoding="utf-8")
            return result
    return load_result(out)


def load_result(out):
    text = Path(out).read_text(encoding="utf-8").strip()
    if not text:
        return {"status": "running_or_lost", "reason": f"{out} is empty"}
    try:
        return json.loads(text.splitlines()[-1])
    except ValueError:
        return {"status": "error", "reason": f"{out} is not compact JSON"}


def format_result(result):
    header = {key: result[key] for key in HEADER_KEYS if result.get(key) is not None}
    usage = result.get("usage") or {}
    if usage.get("totalTokens") is not None:
        header["lastTurnTokens"] = usage["totalTokens"]
    if result.get("failures"):
        header["failures"] = result["failures"]
    lines = [json.dumps(header, ensure_ascii=False, separators=(",", ":"))]
    if result.get("final"):
        lines.append(result["final"])
    return "\n".join(lines)


def _text(message):
    return "\n".join(part.get("text", "") for part in message.get("content") or []
                     if isinstance(part, dict) and part.get("type") == "text").strip()


def digest(path, prompt_chars=300, final_chars=4000):
    """Prompts and the last assistant reply of a session, each truncated."""
    header = {"turns": 0, "outputTokens": 0, "models": []}
    prompts, final = [], ""
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "session":
                header.update(id=event.get("id"), cwd=event.get("cwd"))
            if event.get("type") != "message":
                continue
            message = event.get("message") or {}
            if message.get("role") == "user":
                prompt = " ".join(_text(message).split())[:prompt_chars]
                prompts.append(f"{event.get('timestamp', '')} | {prompt}")
            elif message.get("role") == "assistant":
                usage = message.get("usage") or {}
                header["turns"] += 1
                header["outputTokens"] += usage.get("output") or 0
                header["contextTokens"] = (usage.get("input") or 0) + (usage.get("cacheRead") or 0)
                model = f"{message.get('provider')}/{message.get('model')}"
                if model not in header["models"]:
                    header["models"].append(model)
                final = _text(message) or final
    lines = [json.dumps(header, ensure_ascii=False, separators=(",", ":")), "PROMPTS:"]
    lines += prompts
    lines += ["FINAL:", final[-final_chars:]]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run one detached executor turn")
    run_parser.add_argument("--session", required=True, help="session name (new) or id (resume)")
    run_parser.add_argument("--contract", required=True, help="file holding the prompt")
    run_parser.add_argument("--out", required=True, help="compact result file")
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--idle-timeout", type=int, help="seconds without session growth")
    run_parser.add_argument("extra", nargs="*", help="pi-compact flags, after --")
    result_parser = commands.add_parser("result", help="print a stored handoff")
    result_parser.add_argument("out")
    digest_parser = commands.add_parser("digest", help="summarize an existing session")
    digest_parser.add_argument("session", help="session file path, name or id")
    digest_parser.add_argument("--prompt-chars", type=int, default=300)
    digest_parser.add_argument("--final-chars", type=int, default=4000)
    args = parser.parse_args(argv)

    if args.command == "digest":
        path = Path(args.session)
        path = path if path.is_file() else session_file(args.session)
        if not path:
            print(json.dumps({"status": "error", "error": f"no session {args.session}"}))
            return 1
        print(digest(path, args.prompt_chars, args.final_chars))
        return 0
    if args.command == "run":
        result = run(args.session, args.contract, args.out, resume=args.resume,
                     idle_timeout=args.idle_timeout, extra=args.extra)
    else:
        result = load_result(args.out)
    print(format_result(result))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
