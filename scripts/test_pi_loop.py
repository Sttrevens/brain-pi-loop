import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("pi_loop.py")
SPEC = importlib.util.spec_from_file_location("pi_loop", MODULE_PATH)
pi_loop = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi_loop)

FAKE_PI = textwrap.dedent("""\
    #!{python}
    import json, os, sys, time
    from pathlib import Path
    name, prompt = sys.argv[2], sys.argv[-1]
    sessions = Path(os.environ["FAKE_SESSIONS"]) / "--repo--"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"2026_{{name}}.jsonl").write_text("{{}}\\n")
    probe = {{"stdin": sys.stdin.read(), "ownSession": os.getsid(0) == os.getpid(),
              "flag": sys.argv[1], "extra": sys.argv[3:-1]}}
    Path(os.environ["FAKE_PROBE"]).write_text(json.dumps(probe))
    if prompt == "hang":
        time.sleep(60)
    print(json.dumps({{"status": "ok", "sessionId": name, "stopReason": "stop",
                      "usage": {{"totalTokens": 7}}, "final": "handoff: " + prompt}}))
""")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = self.tmp / "pi-compact"
        self.fake.write_text(FAKE_PI.format(python=sys.executable))
        self.fake.chmod(0o755)
        self.probe = self.tmp / "probe.json"
        os.environ["FAKE_SESSIONS"] = str(self.tmp / "sessions")
        os.environ["FAKE_PROBE"] = str(self.probe)

    def _run(self, prompt, **kwargs):
        contract = self.tmp / "contract.md"
        contract.write_text(prompt)
        return pi_loop.run("task-1", contract, self.tmp / "out.json", executable=str(self.fake),
                           sessions_root=self.tmp / "sessions", poll_seconds=0.1, **kwargs)

    @unittest.skipUnless(os.name == "posix", "session detach is POSIX")
    def test_detaches_with_null_stdin_and_returns_compact_handoff(self):
        result = self._run("do it", extra=["--tools", "read"])
        probe = json.loads(self.probe.read_text())
        self.assertEqual(probe, {"stdin": "", "ownSession": True, "flag": "--session-id",
                                 "extra": ["--tools", "read"]})
        self.assertEqual(result["final"], "handoff: do it")
        self.assertEqual(pi_loop.load_result(self.tmp / "out.json"), result)
        header, final = pi_loop.format_result(result).split("\n", 1)
        self.assertEqual(json.loads(header)["lastTurnTokens"], 7)
        self.assertEqual(final, "handoff: do it")

    def test_resume_uses_existing_session_flag(self):
        self._run("again", resume=True)
        self.assertEqual(json.loads(self.probe.read_text())["flag"], "--session")

    @unittest.skipUnless(os.name == "posix", "process-group stop is POSIX")
    def test_idle_safety_net_stops_a_stuck_executor(self):
        result = self._run("hang", idle_timeout=0.5)
        self.assertEqual(result["status"], "watchdog_killed")
        self.assertEqual(pi_loop.load_result(self.tmp / "out.json")["status"], "watchdog_killed")


class DigestTests(unittest.TestCase):
    def test_keeps_prompts_and_final_reply_bounded(self):
        events = [
            {"type": "session", "id": "s-1", "cwd": "/repo"},
            {"type": "message", "timestamp": "t1",
             "message": {"role": "user", "content": [{"type": "text", "text": "x" * 500}]}},
            {"type": "message", "message": {
                "role": "assistant", "provider": "p", "model": "m",
                "usage": {"input": 90, "cacheRead": 10, "output": 5},
                "content": [{"type": "thinking", "thinking": "secret"},
                            {"type": "text", "text": "final reply"}]}},
            {"type": "message", "message": {"role": "toolResult", "content": [
                {"type": "text", "text": "huge tool output"}]}},
        ]
        path = Path(tempfile.mkdtemp()) / "s.jsonl"
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        lines = pi_loop.digest(path, prompt_chars=20).splitlines()
        self.assertEqual(json.loads(lines[0]), {
            "turns": 1, "outputTokens": 5, "models": ["p/m"], "id": "s-1", "cwd": "/repo",
            "contextTokens": 100})
        self.assertEqual(lines[1:], ["PROMPTS:", "t1 | " + "x" * 20, "FINAL:", "final reply"])


if __name__ == "__main__":
    unittest.main()
