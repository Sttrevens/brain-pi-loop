import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("install.py")
SPEC = importlib.util.spec_from_file_location("pi_supervisor_install", MODULE_PATH)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class ShellCredentialMigrationTests(unittest.TestCase):
    def test_extracts_export_from_later_line_in_regular_shell_config(self):
        text = 'export OTHER="safe"\nexport PROVIDER_API_KEY="later-line"\n'
        self.assertEqual(installer.extract_shell_secret(text, "PROVIDER_API_KEY"), "later-line")

    def test_extracts_last_export_without_printing_or_retaining_quotes(self):
        text = (
            'export OTHER="safe"\n'
            'export PROVIDER_API_KEY="old-value"\n'
            ': 123:0;export PROVIDER_API_KEY=\'new-value\'\n'
        )
        self.assertEqual(installer.extract_shell_secret(text, "PROVIDER_API_KEY"), "new-value")

    def test_scrub_removes_only_lines_that_assign_target_variable(self):
        text = (
            'export OTHER="safe"\n'
            'export PROVIDER_API_KEY="sensitive"\n'
            'echo \'export PROVIDER_API_KEY="history-sensitive"\' >> ~/.zshrc\n'
            'echo PROVIDER_API_KEY docs\n'
        )
        scrubbed, removed = installer.scrub_shell_secret(text, "PROVIDER_API_KEY")
        self.assertEqual(removed, 2)
        self.assertIn('export OTHER="safe"', scrubbed)
        self.assertIn("echo PROVIDER_API_KEY docs", scrubbed)
        self.assertNotIn("sensitive", scrubbed)

    def test_atomic_scrub_changes_file_without_secret_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".zshrc"
            path.write_text('export PROVIDER_API_KEY="sensitive"\nexport SAFE=1\n', encoding="utf-8")
            removed = installer.scrub_file(path, "PROVIDER_API_KEY")
            self.assertEqual(removed, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), "export SAFE=1\n")
            self.assertEqual(list(path.parent.glob("*.bak")), [])

    def test_atomic_scrub_preserves_non_utf8_history_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".zsh_history"
            path.write_bytes(b"\xab\nexport PROVIDER_API_KEY=secret\nSAFE=1\n")
            removed = installer.scrub_file(path, "PROVIDER_API_KEY")
            self.assertEqual(removed, 1)
            self.assertEqual(path.read_bytes(), b"\xab\nSAFE=1\n")


if __name__ == "__main__":
    unittest.main()
