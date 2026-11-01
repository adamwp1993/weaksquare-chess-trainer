#!/usr/bin/env python3
"""Claude Code PreToolUse guard for the WeakSquare Chess Trainer repo.

Blocks tool calls that would:
  1. Read or print stored credentials from a shell (keyring, cmdkey, vault APIs).
  2. Put a secret-looking value into a command or a file (API keys, Lichess
     tokens, Bearer tokens).
  3. Touch keyring from any file other than the single secret-store module.

Exit code 2 blocks the call, and stderr is fed back to Claude as the reason.
Exit code 0 lets the normal permission flow continue.
Self-test:  python .claude/hooks/guard_secrets.py --self-test
"""
import json
import re
import sys

# The one module allowed to call keyring. Everything else goes through it.
SECRET_STORE_SUFFIX = "secret_store.py"

SECRET_VALUE_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "an Anthropic API key"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), "an OpenAI API key"),
    (re.compile(r"\bli[a-z]_[A-Za-z0-9]{16,}"), "a Lichess token or auth code"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-.]{20,}"), "a Bearer token"),
]

SHELL_CREDENTIAL_ACCESS = [
    (re.compile(r"keyring\.(get_password|get_credential)", re.I), "reads a keyring secret"),
    (re.compile(r"\bkeyring\s+get\b", re.I), "uses the keyring CLI to read a secret"),
    (re.compile(r"\bcmdkey\b", re.I), "queries Windows Credential Manager"),
    (re.compile(r"\bvaultcmd\b", re.I), "queries the Windows Vault"),
    (re.compile(r"Get-StoredCredential|CredRead|PasswordVault", re.I), "calls a credential-store API"),
]

KEYRING_IN_CODE = re.compile(r"\bimport\s+keyring\b|\bfrom\s+keyring\b|keyring\.(get_password|set_password|delete_password|get_credential)")

SHELL_TOOLS = {"Bash", "PowerShell"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

BLOCK_SUFFIX = (
    " Credentials must never enter the Claude Code transcript or the repo. "
    "Use the app's secret_store module through normal app code paths, use "
    "obvious placeholders like 'lip_FAKE' / 'sk-ant-FAKE' in tests, or ask Adam to run this step himself."
)


def strings_in(obj):
    """Yield every string value nested in the tool input."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings_in(v)


def check(payload):
    """Return a block reason, or None to allow."""
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    texts = list(strings_in(tool_input))

    for text in texts:
        for pattern, what in SECRET_VALUE_PATTERNS:
            if pattern.search(text):
                return f"Blocked: this {tool} call contains what looks like {what}."

    if tool in SHELL_TOOLS:
        command = tool_input.get("command", "") or ""
        for pattern, what in SHELL_CREDENTIAL_ACCESS:
            if pattern.search(command):
                return f"Blocked: this shell command {what}."

    if tool in WRITE_TOOLS:
        path = (tool_input.get("file_path") or tool_input.get("notebook_path") or "").replace("\\", "/")
        if path.endswith(".py") and not path.endswith(SECRET_STORE_SUFFIX):
            for text in texts:
                if KEYRING_IN_CODE.search(text):
                    return (f"Blocked: keyring may only be used in {SECRET_STORE_SUFFIX}; "
                            f"'{path or 'this file'}' must call the secret_store module instead.")
    return None


def self_test():
    cases = [
        ({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}, False),
        ({"tool_name": "Bash", "tool_input": {"command": "python -c \"import keyring; print(keyring.get_password('x','y'))\""}}, True),
        ({"tool_name": "PowerShell", "tool_input": {"command": "cmdkey /list"}}, True),
        ({"tool_name": "Bash", "tool_input": {"command": "curl -H 'Authorization: Bearer " + "lip_" + "abcdefghijklmnopqrstu' https://lichess.org/api/account"}}, True),
        ({"tool_name": "Write", "tool_input": {"file_path": "tests/fixtures/x.json", "content": "{\"token\": \"lip_FAKE\"}"}}, False),
        ({"tool_name": "Write", "tool_input": {"file_path": "tests/fixtures/x.json", "content": "sk-ant-api03-" + "a" * 40}}, True),
        ({"tool_name": "Write", "tool_input": {"file_path": "src/weaksquare/secret_store.py", "content": "import keyring\nkeyring.get_password('a','b')"}}, False),
        ({"tool_name": "Edit", "tool_input": {"file_path": "src/weaksquare/sync.py", "old_string": "x", "new_string": "import keyring"}}, True),
    ]
    ok = True
    for payload, should_block in cases:
        blocked = check(payload) is not None
        status = "ok " if blocked == should_block else "FAIL"
        ok &= blocked == should_block
        print(f"[{status}] {payload['tool_name']}: expected {'block' if should_block else 'allow'}, got {'block' if blocked else 'allow'}")
    return 0 if ok else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # not our business; don't break the session on malformed input
    reason = check(payload)
    if reason:
        print(reason + BLOCK_SUFFIX, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
