"""Store (or remove) the Lichess token or an AI key for the live tests (REQUIREMENTS.md SR-13).

Run it yourself in a normal PowerShell window, never inside Claude Code:

    uv run python scripts/set_test_token.py            # prompts for the token (hidden input)
    uv run python scripts/set_test_token.py --delete   # removes it
    uv run python scripts/set_test_token.py --llm anthropic   # v0.7: an AI key for the live Explain test
    uv run python scripts/set_test_token.py --llm openai --delete

Create the token at https://lichess.org/account/oauth/token with only the `puzzle:read` and
`puzzle:write` scopes. It's stored in Windows Credential Manager under `weaksquare-test`, separate
from the app's own sign-in, and is read only by `uv run pytest -m live`. The token is never printed.

The AI key (`--llm`) goes in the same `weaksquare-test` entry, under the provider's name. The live test
makes one real Explain call with the cheapest model and a $0.01 cap. A key with a low spending limit
in the provider's console is a good idea.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys

from weaksquare.adapters.secret_store import (
    ANTHROPIC,
    LICHESS,
    MAX_SECRET_CHARS,
    OPENAI,
    SERVICE_TEST,
    KeyringSecretStore,
    SecretStoreError,
)

# Lichess personal access tokens start with "lip_"; the length check is loose on purpose (FR-6.7).
TOKEN_SHAPE = re.compile(r"^lip_[A-Za-z0-9_\-]{8,}$")
# AI keys: Anthropic's start with sk-ant-, OpenAI's with sk- (v0.7).
KEY_SHAPE = {
    ANTHROPIC: re.compile(r"^sk-ant-[A-Za-z0-9_\-]{16,}$"),
    OPENAI: re.compile(r"^sk-(?!ant-)[A-Za-z0-9_\-]{16,}$"),
}


def looks_like_a_token(value: str) -> bool:
    return bool(TOKEN_SHAPE.match(value)) and len(value) <= MAX_SECRET_CHARS


def main(argv: list[str] | None = None, prompt=getpass.getpass, store_factory=KeyringSecretStore) -> int:  # type: ignore[no-untyped-def]
    ap = argparse.ArgumentParser(description="Store the live-test Lichess token in Windows Credential Manager.")
    ap.add_argument("--delete", action="store_true", help="remove the stored test token")
    ap.add_argument(
        "--llm", choices=[ANTHROPIC, OPENAI], help="store (or with --delete remove) an AI key instead (v0.7)"
    )
    args = ap.parse_args(argv)
    store = store_factory(SERVICE_TEST)
    if args.llm:
        return _llm_key(args.llm, args.delete, store, prompt)
    try:
        if args.delete:
            store.delete(LICHESS)
            print(f"Removed the {SERVICE_TEST} token (if there was one).")
            return 0
        value = prompt("Lichess test token (puzzle:read + puzzle:write; input is hidden): ").strip()
        if not looks_like_a_token(value):
            print("That doesn't look like a Lichess personal access token (they start with lip_). Nothing was stored.")
            return 1
        store.set(LICHESS, value)
    except SecretStoreError as e:
        print(f"Couldn't use Windows Credential Manager: {e}")
        return 2
    print(f"Stored. Run the live tests with: uv run pytest -m live   (entry: {SERVICE_TEST})")
    return 0


def _llm_key(provider: str, delete: bool, store, prompt) -> int:  # type: ignore[no-untyped-def]
    label = "Anthropic" if provider == ANTHROPIC else "OpenAI"
    try:
        if delete:
            store.delete(provider)
            print(f"Removed the {SERVICE_TEST} {label} key (if there was one).")
            return 0
        value = prompt(f"{label} API key for the live test (input is hidden): ").strip()
        if not KEY_SHAPE[provider].match(value) or len(value) > MAX_SECRET_CHARS:
            prefix = "sk-ant-" if provider == ANTHROPIC else "sk-"
            print(f"That doesn't look like an {label} API key (they start with {prefix}). Nothing was stored.")
            return 1
        store.set(provider, value)
    except SecretStoreError as e:
        print(f"Couldn't use Windows Credential Manager: {e}")
        return 2
    print(f"Stored. Run the live tests with: uv run pytest -m live   (entry: {SERVICE_TEST}, {provider})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
