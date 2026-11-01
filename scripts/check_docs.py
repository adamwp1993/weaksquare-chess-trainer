"""Check that the changelog and docs keep up with the code.

Usage (from the repo root):
    python scripts/check_docs.py                 # everyday check
    python scripts/check_docs.py --strict        # before a handoff: overdue TODO markers fail
    python scripts/check_docs.py --base main --version v0.3

Checks:
  1. CHANGELOG.md structure (Keep a Changelog), and every FR-/SR-/NFR- ID it cites exists in REQUIREMENTS.md.
  2. Docs changed with the code since the branch left --base (default: main):
       - src/ or web/src/ changed        -> CHANGELOG.md changed and [Unreleased] has an entry   (error)
       - web/src/views|components changed -> docs/USER_GUIDE.md changed                         (error)
       - commands, config, deps, scripts or migrations changed -> docs/DEVELOPER_GUIDE.md changed (warning)
       - pyproject.toml or web/package.json changed -> ARCHITECTURE.md decision log changed       (warning)
  3. Relative links and images in the top-level and docs/ Markdown files resolve.
  4. TODO(v0.x) markers in docs/ and CLAUDE.md: a marker for the current or an earlier version is a
     warning, or an error with --strict. The current version comes from --version or a branch named v0.x.

Exit code 1 if there are errors. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ_ID = re.compile(r"\b(?:FR|SR|NFR)-\d+(?:\.\d+)?[a-z]?\b")
VERSION_HEADING = re.compile(r"^## \[(Unreleased|v\d+\.\d+)\](?: - (\d{4}-\d{2}-\d{2}))?\s*$")
GROUPS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
TODO = re.compile(r"TODO\((v\d+\.\d+)\)")
FENCE = re.compile(r"^(```|~~~)")

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout


def vtuple(v: str) -> tuple[int, int]:
    major, minor = v.lstrip("v").split(".")
    return int(major), int(minor)


def strip_fences(text: str) -> list[tuple[int, str]]:
    """Return (line number, line) pairs outside fenced code blocks."""
    kept, in_fence = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append((n, line))
    return kept


def read(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


# 1. Changelog -----------------------------------------------------------------------------
def unreleased_entries(changelog: str) -> list[str]:
    lines, inside = [], False
    for _, line in strip_fences(changelog):
        m = VERSION_HEADING.match(line)
        if m:
            inside = m.group(1) == "Unreleased"
            continue
        if line.startswith("## "):
            inside = False
        if inside and line.lstrip().startswith(("- ", "* ")) and "Candidates:" not in line:
            lines.append(line)
    return lines


def check_changelog() -> None:
    text = read("CHANGELOG.md")
    if text is None:
        err("CHANGELOG.md is missing")
        return
    requirements = read("REQUIREMENTS.md") or ""
    known_ids = set(REQ_ID.findall(requirements))

    versions: list[str] = []
    current: str | None = None
    for n, line in strip_fences(text):
        if line.startswith("## ["):
            m = VERSION_HEADING.match(line)
            if not m:
                err(f"CHANGELOG.md:{n}: heading must be '## [Unreleased]' or '## [v0.x] - YYYY-MM-DD'")
                continue
            name, date = m.groups()
            if name != "Unreleased" and not date:
                err(f"CHANGELOG.md:{n}: released version {name} needs a date")
            if name == "Unreleased" and date:
                err(f"CHANGELOG.md:{n}: [Unreleased] takes no date")
            versions.append(name)
            current = name
        elif line.startswith("### ") and current is not None:
            group = line[4:].strip()
            if group not in GROUPS:
                err(f"CHANGELOG.md:{n}: '{group}' is not a Keep a Changelog group ({', '.join(sorted(GROUPS))})")
        if current is not None:
            for rid in REQ_ID.findall(line):
                if rid not in known_ids:
                    err(f"CHANGELOG.md:{n}: {rid} does not exist in REQUIREMENTS.md")

    if versions.count("Unreleased") != 1:
        err("CHANGELOG.md must have exactly one '## [Unreleased]' section")
    elif versions[0] != "Unreleased":
        err("CHANGELOG.md: '## [Unreleased]' must be the first version section")
    released = [v for v in versions if v != "Unreleased"]
    if released != sorted(released, key=vtuple, reverse=True):
        err("CHANGELOG.md: versions must be newest first")
    if len(set(released)) != len(released):
        err("CHANGELOG.md: a version appears twice")


# 2. Docs changed with the code ---------------------------------------------------------------
def changed_files(base: str) -> set[str] | None:
    merge_base = git("merge-base", "HEAD", base)
    if merge_base is None:
        return None
    diff = git("diff", "--name-only", merge_base.strip()) or ""
    untracked = git("ls-files", "--others", "--exclude-standard") or ""
    return {p.strip() for p in (diff + untracked).splitlines() if p.strip()}


def check_diff(base: str) -> None:
    changed = changed_files(base)
    if changed is None:
        warn(f"skipped the code-vs-docs check: no merge base with '{base}' (no commits yet, or no such branch)")
        return

    def any_under(*prefixes: str) -> list[str]:
        return sorted(p for p in changed if p.startswith(prefixes))

    code = any_under("src/", "web/src/")
    if code:
        if "CHANGELOG.md" not in changed:
            err(f"code changed ({code[0]} and {len(code) - 1} more) but CHANGELOG.md did not")
        elif not unreleased_entries(read("CHANGELOG.md") or ""):
            err("code changed but CHANGELOG.md [Unreleased] has no entries")

    ui = any_under("web/src/views/", "web/src/components/")
    if ui and "docs/USER_GUIDE.md" not in changed:
        err(f"UI changed ({ui[0]} and {len(ui) - 1} more) but docs/USER_GUIDE.md did not")

    dev = any_under(
        "pyproject.toml", "web/package.json", "web/vite.config.ts", "src/weaksquare/config.py",
        "src/weaksquare/adapters/db/migrations/",
    ) + sorted(p for p in changed if p.startswith("scripts/") and p != "scripts/check_docs.py")
    if dev and "docs/DEVELOPER_GUIDE.md" not in changed:
        warn(f"{dev[0]} changed: check whether docs/DEVELOPER_GUIDE.md needs updating")

    deps = any_under("pyproject.toml", "web/package.json")
    if deps and "ARCHITECTURE.md" not in changed:
        warn(f"{deps[0]} changed: a new or changed dependency usually needs an ARCHITECTURE.md §7 decision-log entry")


# 3. Links ----------------------------------------------------------------------------------
def doc_files() -> list[Path]:
    files = sorted(ROOT.glob("*.md"))
    docs = ROOT / "docs"
    if docs.is_dir():
        files += sorted(docs.rglob("*.md"))
    return files


def check_links() -> None:
    for f in doc_files():
        rel = f.relative_to(ROOT).as_posix()
        for n, line in strip_fences(f.read_text(encoding="utf-8")):
            line = re.sub(r"`[^`]*`", "", line)  # ignore inline code
            for target in LINK.findall(line):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                    continue
                path = target.split("#", 1)[0]
                if path and not (f.parent / path).resolve().exists():
                    err(f"{rel}:{n}: broken link '{target}'")


# 4. TODO markers ---------------------------------------------------------------------------
def current_version(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    branch = (git("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    m = re.fullmatch(r"v\d+\.\d+", branch)
    return m.group(0) if m else None


def check_todos(version: str | None, strict: bool) -> None:
    if version is None:
        return
    targets = [p for p in doc_files() if p.parent.name == "docs" or p.name == "CLAUDE.md"]
    for f in targets:
        rel = f.relative_to(ROOT).as_posix()
        due: dict[str, list[int]] = {}
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for v in TODO.findall(line):
                if vtuple(v) <= vtuple(version):
                    due.setdefault(v, []).append(n)
        for v, lines in sorted(due.items()):
            msg = f"{rel}: {len(lines)} TODO({v}) marker(s) due by {version}, lines {', '.join(map(str, lines))}"
            (err if strict else warn)(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="main", help="branch the version started from (default: main)")
    ap.add_argument("--version", help="version being built, e.g. v0.1 (default: from the branch name)")
    ap.add_argument("--strict", action="store_true", help="overdue TODO markers are errors (use before handoff)")
    args = ap.parse_args()
    if args.version and not re.fullmatch(r"v\d+\.\d+", args.version):
        ap.error("--version must look like v0.1")

    version = current_version(args.version)
    check_changelog()
    check_diff(args.base)
    check_links()
    check_todos(version, args.strict)

    for w in warnings:
        print(f"WARN:  {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"check_docs: {len(errors)} error(s), {len(warnings)} warning(s)"
          + (f" [version {version}]" if version else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
