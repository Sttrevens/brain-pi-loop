#!/usr/bin/env python3
"""Install the provider-neutral Pi supervision bridge for one user account."""

import argparse
import ctypes
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def _assignment_pattern(variable):
    return re.compile(
        r"(?:export\s+)?"
        + re.escape(variable)
        + r"\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s;]+))",
        re.MULTILINE,
    )


def extract_shell_secret(text, variable):
    matches = list(_assignment_pattern(variable).finditer(text))
    if not matches:
        return None
    groups = matches[-1].groups()
    return next((value for value in groups if value is not None), None)


def scrub_shell_secret(text, variable):
    pattern = _assignment_pattern(variable)
    kept = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if pattern.search(line):
            removed += 1
        else:
            kept.append(line)
    return "".join(kept), removed


def _atomic_write(path, text, mode=None, errors="strict"):
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", errors=errors) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temporary_path.chmod(mode)
        os.replace(str(temporary_path), str(path))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def scrub_file(path, variable):
    if not path.exists():
        return 0
    original = path.read_text(encoding="utf-8", errors="surrogateescape")
    scrubbed, removed = scrub_shell_secret(original, variable)
    if removed:
        mode = stat.S_IMODE(path.stat().st_mode)
        _atomic_write(path, scrubbed, mode=mode, errors="surrogateescape")
    return removed


def _security_framework():
    security = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/Security.framework/Security"
    )
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    return security


def _macos_read_secret(service, account):
    security = _security_framework()
    service_bytes = service.encode("utf-8")
    account_bytes = account.encode("utf-8")
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None,
        len(service_bytes),
        service_bytes,
        len(account_bytes),
        account_bytes,
        ctypes.byref(length),
        ctypes.byref(data),
        ctypes.byref(item),
    )
    if status != 0:
        return None
    try:
        return ctypes.string_at(data, length.value).decode("utf-8")
    finally:
        security.SecKeychainItemFreeContent(None, data)


def _macos_store_secret(service, account, secret):
    security = _security_framework()
    service_bytes = service.encode("utf-8")
    account_bytes = account.encode("utf-8")
    secret_bytes = secret.encode("utf-8")
    length = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None,
        len(service_bytes),
        service_bytes,
        len(account_bytes),
        account_bytes,
        ctypes.byref(length),
        ctypes.byref(data),
        ctypes.byref(item),
    )
    if status == 0:
        security.SecKeychainItemFreeContent(None, data)
        status = security.SecKeychainItemModifyAttributesAndData(
            item, None, len(secret_bytes), secret_bytes
        )
    elif status == -25300:  # errSecItemNotFound
        status = security.SecKeychainAddGenericPassword(
            None,
            len(service_bytes),
            service_bytes,
            len(account_bytes),
            account_bytes,
            len(secret_bytes),
            secret_bytes,
            None,
        )
    if status != 0:
        raise RuntimeError("macOS Keychain rejected the credential (OSStatus {})".format(status))
    if _macos_read_secret(service, account) != secret:
        raise RuntimeError("macOS Keychain credential verification failed")


def _config_path():
    override = os.environ.get("PI_SUPERVISOR_CONFIG")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "pi-supervisor" / "config.json"


def write_config(config):
    path = _config_path()
    _atomic_write(path, json.dumps(config, ensure_ascii=False, indent=2) + "\n", mode=0o600)
    return path


def _write_windows_command(path, bridge, compact):
    mode = " compact" if compact else ""
    content = '@echo off\r\npython "{}"{} %*\r\n'.format(bridge, mode)
    _atomic_write(path, content)


def install_commands(bridge, bin_dir, force=False):
    bin_dir.mkdir(parents=True, exist_ok=True)
    names = ["pi", "pi-compact"]
    installed = []
    for name in names:
        target = bin_dir / (name + ".cmd" if os.name == "nt" else name)
        if target.exists() or target.is_symlink():
            same = False
            try:
                same = target.resolve() == bridge.resolve()
            except OSError:
                pass
            if not same and not force:
                raise FileExistsError("Refusing to replace existing command: {}".format(target))
            if target.is_symlink():
                target.unlink()
        if os.name == "nt":
            _write_windows_command(target, bridge, compact=(name == "pi-compact"))
        else:
            target.symlink_to(bridge)
        installed.append(str(target))
    return installed


def ensure_unix_path(bin_dir):
    if os.name == "nt":
        return False
    current_parts = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) in current_parts:
        return False
    shell_file = Path.home() / ".zshrc"
    line = 'export PATH="$HOME/.local/bin:$PATH"\n'
    existing = shell_file.read_text(encoding="utf-8") if shell_file.exists() else ""
    if line.strip() not in existing:
        shell_file.parent.mkdir(parents=True, exist_ok=True)
        with shell_file.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(line)
    return True


def migrate_shell_credential(variable, service, account):
    paths = [
        Path.home() / ".zshrc",
        Path.home() / ".zprofile",
        Path.home() / ".zsh_history",
        Path.home() / ".bashrc",
        Path.home() / ".bash_profile",
        Path.home() / ".bash_history",
    ]
    found = os.environ.get(variable)
    for path in paths:
        if path.exists():
            candidate = extract_shell_secret(
                path.read_text(encoding="utf-8", errors="surrogateescape"), variable
            )
            if candidate:
                found = candidate
    if not found:
        raise RuntimeError("No value found for {}".format(variable))
    if sys.platform != "darwin":
        raise RuntimeError("Automatic secure-store migration is currently implemented for macOS only")
    _macos_store_secret(service, account, found)
    removed = sum(scrub_file(path, variable) for path in paths)
    return removed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-pi", required=True)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--thinking")
    parser.add_argument("--credential-env")
    parser.add_argument("--secret-service")
    parser.add_argument("--secret-account")
    parser.add_argument("--migrate-shell-secret")
    parser.add_argument("--bin-dir")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    real_pi = Path(args.real_pi).expanduser().resolve()
    if not real_pi.exists():
        raise FileNotFoundError("Real Pi executable not found: {}".format(real_pi))
    bridge = Path(__file__).with_name("pi_bridge.py").resolve()
    bridge.chmod(bridge.stat().st_mode | stat.S_IXUSR)
    Path(__file__).chmod(Path(__file__).stat().st_mode | stat.S_IXUSR)

    config = {"realPi": str(real_pi)}
    for key, value in (
        ("provider", args.provider),
        ("model", args.model),
        ("thinking", args.thinking),
        ("credentialEnv", args.credential_env),
        ("secretService", args.secret_service),
        ("secretAccount", args.secret_account),
    ):
        if value:
            config[key] = value

    migrated = False
    removed_lines = 0
    if args.migrate_shell_secret:
        if not args.secret_service or not args.secret_account:
            raise ValueError("Credential migration requires --secret-service and --secret-account")
        removed_lines = migrate_shell_credential(
            args.migrate_shell_secret, args.secret_service, args.secret_account
        )
        migrated = True

    saved_config = write_config(config)
    default_bin = Path.home() / ("bin" if os.name == "nt" else ".local/bin")
    bin_dir = Path(args.bin_dir).expanduser() if args.bin_dir else default_bin
    commands = install_commands(bridge, bin_dir, force=args.force)
    path_updated = ensure_unix_path(bin_dir)
    report = {
        "status": "ok",
        "config": str(saved_config),
        "commands": commands,
        "provider": args.provider,
        "model": args.model,
        "thinking": args.thinking,
        "credentialMigrated": migrated,
        "shellSecretLinesRemoved": removed_lines,
        "shellPathUpdated": path_updated,
    }
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, separators=(",", ":")))
        sys.exit(1)
