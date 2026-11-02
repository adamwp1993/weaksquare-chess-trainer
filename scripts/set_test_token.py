"""Store (or remove) the Lichess token for the live tests (REQUIREMENTS.md SR-13).

Run it yourself in a normal PowerShell window, never inside Claude Code:

    uv run python scripts/set_test_token.py            # prompts for the token (hidden input)
    uv run python scripts/set_test_token.py --delete   # removes it

Create the token at https://lichess.org/account/oauth/token with only the `puzzle:read` and
`puzzle:write` scopes. It's stored in Windows Credential Manager under `weaksquare-test`, separate
from the app's own sign-in, and is read only by `uv run pytest -m live`. The token is never printed.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys

from weaksquare.adapters.secret_store import (
    LICHESS,
    MAX_SECRET_CHARS,
    SERVICE_TEST,
    KeyringSecretStore,
    SecretStoreError,
)

# Lichess personal access tokens start with "lip_"; the length check is loose on purpose (FR-6.7).
TOKEN_SHAPE = re.compile(r"^lip_[A-Za-z0-9_\-]{8,}$")


def looks_like_a_token(value: str) -> bool:
    return bool(TOKEN_SHAPE.match(value)) and len(value) <= MAX_SECRET_CHARS


def main(argv: list[str] | None = None, prompt=getpass.getpass, store_factory=KeyringSecretStore) -> int:  # type: ignore[no-untyped-def]
    ap = argparse.ArgumentParser(description="Store the live-test Lichess token in Windows Credential Manager.")
    ap.add_argument("--delete", action="store_true", help="remove the stored test token")
    args = ap.parse_args(argv)
    store = store_factory(SERVICE_TEST)
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


if __name__ == "__main__":
    sys.exit(main())
