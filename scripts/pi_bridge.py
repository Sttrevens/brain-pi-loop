#!/usr/bin/env python3
"""Provider-neutral launcher and compact JSONL bridge for Pi Agent."""

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path


CONFIG_ENV = "PI_SUPERVISOR_CONFIG"


def config_path():
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "pi-supervisor" / "config.json"


def load_config():
    path = config_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Pi supervisor config must be a JSON object")
    return data


def _is_usable_pi(path, self_path=None):
    if not path:
        return False
    candidate = Path(path).expanduser()
    if not candidate.exists() or candidate.is_dir():
        return False
    if self_path:
        try:
            if candidate.resolve() == Path(self_path).resolve():
                return False
        except OSError:
            pass
    return os.name == "nt" or os.access(str(candidate), os.X_OK)


def discover_pi(config, self_path=None):
    """Find a real Pi executable without assuming a provider or host app."""
    candidates = []
    for value in (os.environ.get("PI_REAL_BIN"), config.get("realPi")):
        if value:
            candidates.append(Path(value).expanduser())

    home = Path.home()
    if sys.platform == "darwin":
        candidates.extend(
            [
                home / ".local/bin/pi-real",
                Path("/opt/homebrew/bin/pi"),
                Path("/usr/local/bin/pi"),
            ]
        )
    elif os.name == "nt":
        candidates.append(home / "bin/pi-real.cmd")
    else:
        candidates.extend(
            [
                home / ".local/bin/pi-real",
                Path("/usr/local/bin/pi"),
                Path("/usr/bin/pi"),
            ]
        )

    path_pi = shutil.which("pi")
    if path_pi:
        candidates.append(Path(path_pi))

    for candidate in candidates:
        if _is_usable_pi(candidate, self_path=self_path):
            return candidate
    raise FileNotFoundError(
        "No usable Pi Agent executable found. Install Pi or set PI_REAL_BIN/config realPi."
    )


def read_platform_secret(config):
    service = config.get("secretService")
    account = config.get("secretAccount") or os.environ.get("USER") or os.environ.get("USERNAME")
    command = config.get("secretCommand")
    if command:
        if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
            raise ValueError("secretCommand must be a JSON array of command arguments")
    elif sys.platform == "darwin" and service and account:
        command = [
            "/usr/bin/security",
            "find-generic-password",
            "-w",
            "-s",
            service,
            "-a",
            account,
        ]
    elif sys.platform.startswith("linux") and service and account and shutil.which("secret-tool"):
        command = ["secret-tool", "lookup", "service", service, "account", account]
    else:
        return None

    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    secret = result.stdout.rstrip("\r\n")
    return secret or None


def child_environment(config):
    env = os.environ.copy()
    credential_env = config.get("credentialEnv")
    if credential_env and not env.get(credential_env):
        secret = read_platform_secret(config)
        if secret:
            env[credential_env] = secret
    return env


def _has_flag(args, *names):
    return any(arg in names for arg in args)


def build_compact_args(user_args, config):
    args = list(user_args)
    defaults = [
        ("--provider", config.get("provider")),
        ("--model", config.get("model")),
        ("--thinking", config.get("thinking")),
    ]
    prefix = []
    for flag, value in defaults:
        if value and not _has_flag(args, flag):
            prefix.extend([flag, str(value)])
    if not _has_flag(args, "--mode"):
        prefix.extend(["--mode", "json"])
    if not _has_flag(args, "--print", "-p"):
        prefix.append("--print")
    return prefix + args


class _Compactor:
    def __init__(self):
        self.session_id = None
        self.cwd = None
        self.final = ""
        self.provider = None
        self.model = None
        self.usage = None
        self.stop_reason = None
        self.tools = []
        self.pending_tools = {}
        self.parse_errors = 0
        self.saw_turn_end = False

    def accept(self, event):
        event_type = event.get("type")
        if event_type == "session":
            self.session_id = event.get("id")
            self.cwd = event.get("cwd")
            return

        if event_type in ("tool_execution_start", "tool_start"):
            call_id = event.get("toolCallId") or event.get("id")
            name = event.get("toolName") or event.get("name") or "unknown"
            if call_id:
                self.pending_tools[call_id] = name
            return

        if event_type in ("tool_execution_end", "tool_end"):
            call_id = event.get("toolCallId") or event.get("id")
            name = event.get("toolName") or event.get("name")
            name = name or self.pending_tools.pop(call_id, "unknown")
            is_error = bool(event.get("isError")) or event.get("status") == "error"
            self.tools.append({"name": name, "ok": not is_error})
            return

        if event_type != "turn_end":
            return

        self.saw_turn_end = True
        message = event.get("message") or {}
        self.provider = message.get("provider")
        self.model = message.get("model")
        self.usage = message.get("usage")
        self.stop_reason = message.get("stopReason")
        content = message.get("content") or []
        self.final = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()

    def result(self):
        if not self.saw_turn_end:
            return {
                "status": "error",
                "error": "Pi JSON stream ended without turn_end",
                "sessionId": self.session_id,
                "parseErrors": self.parse_errors,
            }
        status = "error" if self.stop_reason in ("error", "aborted") else "ok"
        result = {
            "status": status,
            "sessionId": self.session_id,
            "cwd": self.cwd,
            "provider": self.provider,
            "model": self.model,
            "stopReason": self.stop_reason,
            "usage": self.usage,
            "tools": self.tools,
            "final": self.final,
        }
        if self.parse_errors:
            result["parseErrors"] = self.parse_errors
        return result


def compact_jsonl(stream):
    compactor = _Compactor()
    for line in stream:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            compactor.parse_errors += 1
            continue
        if isinstance(event, dict):
            compactor.accept(event)
    return compactor.result()


def _redact_diagnostic(text):
    if not text:
        return None
    clean = text.strip().splitlines()[-1][:500]
    for marker in ("sk-", "api_key=", "token="):
        index = clean.lower().find(marker.lower())
        if index >= 0:
            clean = clean[:index] + "<redacted>"
    return clean


def run_compact(real_pi, user_args, config):
    args = build_compact_args(user_args, config)
    stderr_tail = deque(maxlen=20)
    process = subprocess.Popen(
        [str(real_pi)] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=child_environment(config),
    )

    def drain_stderr():
        for line in process.stderr:
            stderr_tail.append(line)

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    result = compact_jsonl(process.stdout)
    return_code = process.wait()
    stderr_thread.join(timeout=1)
    result["exitCode"] = return_code
    if return_code != 0:
        result["status"] = "error"
        diagnostic = _redact_diagnostic("".join(stderr_tail))
        if diagnostic:
            result["diagnostic"] = diagnostic
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return return_code if return_code else (0 if result.get("status") == "ok" else 1)


def doctor(real_pi, config):
    version = subprocess.run(
        [str(real_pi), "--version"],
        text=True,
        capture_output=True,
        check=False,
        env=child_environment(config),
    )
    credential_env = config.get("credentialEnv")
    credential_ready = True
    if credential_env:
        credential_ready = bool(child_environment(config).get(credential_env))
    report = {
        "status": "ok" if version.returncode == 0 and credential_ready else "error",
        "realPi": str(real_pi),
        "version": version.stdout.strip() or None,
        "config": str(config_path()),
        "provider": config.get("provider"),
        "model": config.get("model"),
        "thinking": config.get("thinking"),
        "credentialEnv": credential_env,
        "credentialReady": credential_ready,
    }
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["status"] == "ok" else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    config = load_config()
    self_path = Path(__file__)
    real_pi = discover_pi(config, self_path=self_path)
    invoked_as = Path(sys.argv[0]).name.lower()

    if argv and argv[0] == "doctor":
        return doctor(real_pi, config)
    if argv and argv[0] == "compact":
        return run_compact(real_pi, argv[1:], config)
    if invoked_as in ("pi-compact", "pi-supervise"):
        return run_compact(real_pi, argv, config)

    os.execve(str(real_pi), [str(real_pi)] + argv, child_environment(config))
    return 127


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, separators=(",", ":")))
        sys.exit(1)
