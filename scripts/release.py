#!/usr/bin/env python3
"""Cut a release of the action: create the GitHub Release that moves the floating major tag.

Usage:
    uv run python scripts/release.py [--dry-run] [--yes]
    make release          # same, with confirmation prompt
    make release-dry-run  # checks only, creates nothing

The version to release is read from pyproject.toml. A GitHub Action has no
registry: users reference `mcp-box/mcpscore-action@v1`, and the Marketplace
lists whatever the repository's GitHub Releases say. So "publishing" means two
things, and this script does the first while CI does the second:

  1. create the GitHub Release on tag v<version> (this script);
  2. move the floating major tag (v1 for 1.x) to that commit, so every `@v1`
     user picks the release up (.github/workflows/publish.yml, triggered by
     the release).

Checks performed before anything is created:
  1. on `main`, clean working tree, local HEAD in sync with origin/main
  2. the version is a stable X.Y.Z (an action has no pre-release channel:
     `@v1` cannot float to a beta)
  3. CHANGELOG.md has a `## [<version>]` section AND the `[<version>]:` compare
     link at the bottom
  4. tag v<version> does not already exist on the remote
  5. CI is green for HEAD (both the checks and the live end-to-end workflow)

After creating the release it waits for publish.yml to move the major tag,
then prints the `uses:` lines to try.

Requires: git, gh (authenticated). No third-party Python dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import NoReturn

REPO = "mcp-box/mcpscore-action"
ROOT = Path(__file__).resolve().parent.parent
MAJOR_TAG_WAIT_SECONDS = 300
STABLE_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def run(*args: str, capture: bool = True) -> str:
    try:
        result = subprocess.run(args, capture_output=capture, text=True, check=True, cwd=ROOT)
    except FileNotFoundError:
        fail(f"required tool not found: {args[0]} — install it and retry")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        fail(f"command failed: {' '.join(args)}\n  {stderr or e}")
    return (result.stdout or "").strip()


def fail(message: str) -> NoReturn:
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(1)


def ok(message: str) -> None:
    print(f"✓ {message}")


def read_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def major_tag(version: str) -> str:
    """The floating tag users reference, e.g. ``v1`` for ``1.4.2``."""
    match = STABLE_VERSION.match(version)
    if match is None:
        fail(f"version {version!r} is not a stable X.Y.Z release — an action has no pre-release channel")
    return f"v{match.group(1)}"


def check_git_state() -> str:
    """Verify the repo is releasable from main; return HEAD's sha."""
    branch = run("git", "branch", "--show-current")
    if not branch:
        fail("detached HEAD — check out main to release")
    if branch != "main":
        fail(f"must release from main (currently on '{branch}')")
    if run("git", "status", "--porcelain"):
        fail("working tree is not clean")
    head = run("git", "rev-parse", "HEAD")
    remote_head = run("gh", "api", f"repos/{REPO}/commits/main", "--jq", ".sha")
    if head != remote_head:
        fail(f"local main ({head[:9]}) != origin/main ({remote_head[:9]}) — push or pull first")
    ok(f"on main, clean, in sync with origin ({head[:9]})")
    return head


def check_changelog(version: str) -> str:
    """Verify the CHANGELOG section and link block, and return the section body."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if re.search(r"^(<{7} |={7}$|>{7} )", changelog, flags=re.MULTILINE):
        fail("CHANGELOG.md contains unresolved merge conflict markers")
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        fail(f"CHANGELOG.md has no '## [{version}]' section")
    if f"[{version}]: https://" not in changelog:
        fail(f"CHANGELOG.md is missing the '[{version}]: ...' compare link at the bottom")
    ok(f"CHANGELOG has the [{version}] section and compare link")
    return match.group(1).strip()


def check_tag_absent(version: str) -> None:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/git/ref/tags/v{version}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        fail(f"tag v{version} already exists on the remote")
    stderr = (result.stderr or "") + (result.stdout or "")
    if "404" not in stderr and "Not Found" not in stderr:
        fail(f"could not verify tag v{version} (gh api error, not a 404):\n  {stderr.strip()}")
    ok(f"tag v{version} is unused")


REVIEW_BOT_CHECKS = frozenset({"copilot-pull-request-reviewer", "Cursor Bugbot"})
"""Check runs registered by code-review bots: reviews, not CI gates."""


def check_ci_green(sha: str) -> None:
    raw = run(
        "gh",
        "api",
        f"repos/{REPO}/commits/{sha}/check-runs",
        "--jq",
        "[.check_runs[] | {name, status, conclusion, started_at, completed_at}]",
    )
    runs = [r for r in json.loads(raw) if r["name"] not in REVIEW_BOT_CHECKS]
    if not runs:
        fail("no CI check runs found for HEAD — has CI finished?")
    latest_runs: dict[str, dict] = {}
    for check in runs:
        timestamp = check["completed_at"] or check["started_at"] or ""
        latest = latest_runs.get(check["name"])
        latest_timestamp = (latest["completed_at"] or latest["started_at"] or "") if latest else ""
        if latest is None or timestamp > latest_timestamp:
            latest_runs[check["name"]] = check
    runs = list(latest_runs.values())
    bad = [r for r in runs if r["status"] != "completed" or r["conclusion"] not in ("success", "skipped", "neutral")]
    if bad:
        details = ", ".join(f"{r['name']}: {r['conclusion'] or r['status']}" for r in bad)
        fail(f"CI is not green for HEAD — {details}")
    ok(f"CI green for HEAD ({len(runs)} checks)")


def create_release(version: str, notes: str, target: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(notes + "\n")
        notes_file = f.name
    try:
        run(
            "gh",
            "release",
            "create",
            f"v{version}",
            "--repo",
            REPO,
            "--target",
            target,
            "--title",
            f"v{version}",
            "--notes-file",
            notes_file,
            "--latest",
        )
    finally:
        Path(notes_file).unlink(missing_ok=True)
    ok(f"GitHub Release v{version} created — publish workflow triggered")


def wait_for_major_tag(version: str, sha: str) -> None:
    """Poll until publish.yml has moved the major tag to the release commit."""
    tag = major_tag(version)
    print(f"… waiting for publish.yml to move {tag} to {sha[:9]} (up to {MAJOR_TAG_WAIT_SECONDS}s)")
    deadline = time.monotonic() + MAJOR_TAG_WAIT_SECONDS
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/git/ref/tags/{tag}", "--jq", ".object.sha"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == sha:
            ok(f"{tag} now points at v{version}")
            return
        time.sleep(min(10, max(0, deadline - time.monotonic())))
    fail(
        f"{tag} did not move to v{version} within {MAJOR_TAG_WAIT_SECONDS}s — "
        f"check the workflow: https://github.com/{REPO}/actions/workflows/publish.yml"
    )


def _run_preflight(version: str) -> tuple[str, str]:
    """Run every releasable-state check; return (head sha, release notes)."""
    tag = major_tag(version)
    head = check_git_state()
    notes = check_changelog(version)
    check_tag_absent(version)
    check_ci_green(head)
    ok(f"a release will move {tag} to {head[:9]}")
    return head, notes


def _confirm(version: str) -> bool:
    """Prompt for release confirmation; a closed stdin (EOF) counts as 'no'."""
    try:
        answer = input(f"Create GitHub Release v{version} and move {major_tag(version)} to it? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print("\naborted (no confirmation)")
        return False
    return answer.strip().lower() == "y"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="run all checks, create nothing")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt (for non-interactive use)")
    args = parser.parse_args()

    version = read_version()
    print(f"Releasing mcpscore-action {version}\n")

    head, notes = _run_preflight(version)

    print(f"\n--- release notes (from CHANGELOG) ---\n{notes}\n--------------------------------------\n")

    if args.dry_run:
        ok(f"dry run: all checks passed — would create release v{version}")
        return

    if not args.yes and not _confirm(version):
        sys.exit(1)

    # Re-check the fast-moving state in case main advanced during the prompt.
    head, notes = _run_preflight(version)

    create_release(version, notes, head)
    wait_for_major_tag(version, head)
    tag = major_tag(version)
    print(
        f"\nTry it:\n"
        f"  - uses: {REPO}@{tag}          # floats to this and later {tag[1:]}.x releases\n"
        f"  - uses: {REPO}@v{version}   # pinned to exactly this release"
    )


if __name__ == "__main__":
    main()
