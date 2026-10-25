import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("pi_bridge.py")
SPEC = importlib.util.spec_from_file_location("pi_bridge", MODULE_PATH)
pi_bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_bridge)


class CompactJsonlTests(unittest.TestCase):
    def test_keeps_handoff_metadata_and_drops_thinking_payloads(self):
        events = [
            {"type": "session", "id": "session-123", "cwd": "/repo"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "thinking_delta",
                    "delta": "x" * 100_000,
                    "thinkingSignature": "secret-like-signature" * 1000,
                },
            },
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "bash",
                "args": {"command": "pytest tests/test_feature.py"},
            },
            {
                "type": "tool_execution_end",
                "toolCallId": "call-1",
                "toolName": "bash",
                "isError": False,
                "result": {"content": [{"type": "text", "text": "large output" * 1000}]},
            },
            {
                "type": "turn_end",
                "message": {
                    "provider": "provider-x",
                    "model": "model-y",
                    "stopReason": "stop",
                    "usage": {"input": 100, "output": 20, "totalTokens": 120},
                    "content": [
                        {"type": "thinking", "thinking": "private reasoning"},
                        {"type": "text", "text": "DONE\nTests passed."},
                    ],
                },
            },
        ]
        stream = io.StringIO("\n".join(json.dumps(event) for event in events))

        compact = pi_bridge.compact_jsonl(stream)

        self.assertEqual(compact["status"], "ok")
        self.assertEqual(compact["sessionId"], "session-123")
        self.assertEqual(compact["final"], "DONE\nTests passed.")
        self.assertEqual(compact["provider"], "provider-x")
        self.assertEqual(compact["model"], "model-y")
        self.assertEqual(compact["usage"]["totalTokens"], 120)
        self.assertEqual(compact["tools"], [{"name": "bash", "ok": True}])
        rendered = json.dumps(compact)
        self.assertNotIn("private reasoning", rendered)
        self.assertNotIn("secret-like-signature", rendered)
        self.assertNotIn("large output", rendered)

    def test_reports_error_when_no_final_turn_exists(self):
        compact = pi_bridge.compact_jsonl(io.StringIO('{"type":"agent_start"}\n'))
        self.assertEqual(compact["status"], "error")
        self.assertIn("turn_end", compact["error"])


class CommandTests(unittest.TestCase):
    def test_compact_command_adds_defaults_but_respects_overrides(self):
        config = {
            "provider": "default-provider",
            "model": "default-model",
            "thinking": "high",
        }
        args = pi_bridge.build_compact_args(
            ["--model", "chosen-model", "Do the task"], config
        )
        self.assertEqual(args.count("--mode"), 1)
        self.assertIn("json", args)
        self.assertIn("--print", args)
        self.assertEqual(args[args.index("--model") + 1], "chosen-model")
        self.assertEqual(args[args.index("--provider") + 1], "default-provider")
        self.assertEqual(args[args.index("--thinking") + 1], "high")

    def test_env_credential_wins_without_touching_platform_store(self):
        with mock.patch.dict(os.environ, {"PROVIDER_API_KEY": "from-env"}, clear=False):
            with mock.patch.object(pi_bridge, "read_platform_secret") as secret_reader:
                env = pi_bridge.child_environment({"credentialEnv": "PROVIDER_API_KEY"})
        self.assertEqual(env["PROVIDER_API_KEY"], "from-env")
        secret_reader.assert_not_called()


class DiscoveryTests(unittest.TestCase):
    def test_configured_real_pi_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "pi-real"
            candidate.write_text("#!/bin/sh\n", encoding="utf-8")
            candidate.chmod(0o755)
            found = pi_bridge.discover_pi({"realPi": str(candidate)}, self_path=Path(__file__))
        self.assertEqual(found, candidate)


if __name__ == "__main__":
    unittest.main()
