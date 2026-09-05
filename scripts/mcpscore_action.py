#!/usr/bin/env python3
"""Run mcpscore in CI: audit an MCP server, gate on thresholds, comment on the PR.

The action.yml wraps this: it installs uv (so `uvx` is available) and invokes
this script with the action inputs passed through as ``INPUT_*`` environment
variables (GitHub's convention). Everything the action does lives here so the
logic is testable in one place — the pure functions (parsing, gating, comment
rendering) are unit-tested; only ``main`` touches the network and subprocess.

Exit codes:
  0  audit ran and all configured gates passed
  1  a gate failed, or mcpscore could not audit the server
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

COMMENT_MARKER = "<!-- mcpscore-action -->"
"""Hidden marker that lets the action find and update its own PR comment."""


def env(name: str, default: str = "") -> str:
    """Read an action input from its GitHub ``INPUT_*`` environment variable."""
    return os.environ.get(f"INPUT_{name.upper().replace('-', '_')}", default).strip()


def run_audit(target: str, version: str, extra_args: list[str]) -> tuple[int, str, str]:
    """Run ``uvx mcpscore[@version] <target> --json`` and capture its output.

    Returns:
        (exit_code, stdout, stderr). mcpscore writes the JSON report to stdout
        and logs to stderr; a non-zero exit means it could not audit (e.g.
        connection failure, exit code 2).

    """
    spec = f"mcpscore@{version}" if version else "mcpscore"
    cmd = ["uvx", spec, target, "--json", *extra_args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def percentage(score: int, max_score: int) -> int:
    """Score as an integer percentage; 0 when there is nothing to score."""
    if max_score <= 0:
        return 0
    return round(score / max_score * 100)


def evaluate_gate(report: dict, min_score: str, min_readiness: str) -> list[str]:
    """Return the reasons the audit fails the configured thresholds (empty = pass).

    Thresholds are integer percentages passed as strings; an empty string
    disables that gate. The readiness axis is only gated when the server was
    actually assessed for readiness (``readiness.max_score > 0``).
    """
    failures: list[str] = []

    main_pct = percentage(report["score"], report["max_score"])
    if min_score:
        threshold = int(min_score)
        if main_pct < threshold:
            failures.append(
                f"score {report['score']}/{report['max_score']} ({main_pct}%) is below the required {threshold}%"
            )

    if min_readiness:
        readiness = report.get("readiness", {})
        readiness_max = readiness.get("max_score", 0)
        if readiness_max > 0:
            readiness_pct = percentage(readiness.get("score", 0), readiness_max)
            threshold = int(min_readiness)
            if readiness_pct < threshold:
                failures.append(
                    f"readiness {readiness.get('score', 0)}/{readiness_max} ({readiness_pct}%) "
                    f"is below the required {threshold}%"
                )

    return failures


def _severity_table(report: dict) -> str:
    by_severity = report["summary"]["by_severity"]
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    header = "| | " + " | ".join(order) + " |"
    divider = "|---|" + "|".join(["---"] * len(order)) + "|"
    passed = "| ✅ passed | " + " | ".join(str(by_severity.get(s, {}).get("passed", 0)) for s in order) + " |"
    failed = "| ❌ failed | " + " | ".join(str(by_severity.get(s, {}).get("failed", 0)) for s in order) + " |"
    return "\n".join([header, divider, passed, failed])


def _failed_rules_section(report: dict) -> str:
    failed = [r for r in report["results"] if not r["passed"]]
    if not failed:
        return "All checks passed. 🎉"
    items = "\n".join(f"- `{r['rule_id']}` ({r['severity']})" for r in failed)
    return f"<details><summary>{len(failed)} failed check(s)</summary>\n\n{items}\n\n</details>"


def _config_lines(report: dict) -> list[str]:
    """Markdown lines describing an applied ``mcpscore.toml`` (the report's ``config`` block), or none.

    A configured score is the score under the repository's own policy; the
    comment says so, and which rules the gate tripped on, so nobody reads the
    number as the canonical one the badge shows.
    """
    block = report.get("config")
    if not block:
        return []
    off, reranked = len(block.get("disabled", [])), len(block.get("reranked", {}))
    parts = [f"{off} rule{'s' if off != 1 else ''} off"] if off else []
    if reranked:
        parts.append(f"{reranked} re-ranked")
    # The report is another program's output; read the gate defensively so a
    # partial block degrades to a vaguer line rather than a crashed comment.
    gate = block.get("gate") or {}
    fail_on = gate.get("fail_on", "?")
    if gate:
        parts.append(f"gate at {fail_on}")
    lines = [f"**Config:** `{block.get('source', 'mcpscore.toml')}` — {', '.join(parts) if parts else 'no overrides'}"]
    failed_ids = gate.get("failed") or []
    if failed_ids:
        failed = ", ".join(f"`{rule_id}`" for rule_id in failed_ids)
        lines.append(f"**Gate failed:** {len(failed_ids)} rule(s) at or above {fail_on}: {failed}")
    lines.append("")
    return lines


def build_report_markdown(report: dict) -> str:
    """Render the human-readable report body (shared by the PR comment and job summary)."""
    score = report["score"]
    max_score = report["max_score"]
    pct = percentage(score, max_score)
    spec = report.get("spec", {})
    readiness = report.get("readiness", {})

    lines = [
        f"## 🔦 mcpscore — {score}/{max_score} ({pct}%)",
        "",
        f"**Target:** `{report.get('target', '?')}`  ·  "
        f"**Spec:** {spec.get('negotiated_version', 'unknown')} ({spec.get('era', 'unknown')})",
        "",
        *_config_lines(report),
        _severity_table(report),
        "",
    ]

    readiness_max = readiness.get("max_score", 0)
    if readiness_max > 0:
        readiness_pct = percentage(readiness.get("score", 0), readiness_max)
        lines.append(
            f"**Readiness for MCP {spec.get('readiness_target', '')}:** "
            f"{readiness.get('score', 0)}/{readiness_max} ({readiness_pct}%) "
            f"— informative, not part of the main score."
        )
        lines.append("")

    lines.append(_failed_rules_section(report))
    lines.append("")
    lines.append(
        f"<sub>mcpscore {report.get('mcpscore_version', '')} · "
        f"[docs](https://docs.mcpscore.dev) · [methodology](https://docs.mcpscore.dev/methodology)</sub>"
    )
    return "\n".join(lines)


# Exit codes that mean the audit completed and a gate the CLI itself enforces
# failed: 3 for --fail-under / --fail-under-readiness / a configured [gate],
# 4 for a --smoke check. The report is still on stdout and must still be
# published; the job fails afterwards with the reason.
CLI_GATE_EXIT_CODES = (3, 4)


def cli_gate_failures(report: dict, code: int) -> list[str]:
    """Explain a CLI gate exit (3 or 4) from the report, so the job's error names the rules."""
    if code == 3:
        gate = (report.get("config") or {}).get("gate") or {}
        failed_ids = gate.get("failed") or []
        if failed_ids:
            return [f"mcpscore [gate] fail_on = {gate.get('fail_on', '?')}: failed rule(s) {', '.join(failed_ids)}"]
        return ["mcpscore exited 3: a --fail-under gate passed through `args` was not met"]
    if code == 4:
        checks = (report.get("smoke") or {}).get("checks") or []
        failed = [c.get("check_id", "?") for c in checks if c.get("verdict") == "fail"]
        return [f"mcpscore --smoke: failed check(s) {', '.join(failed) if failed else '(see the report)'}"]
    return []


def build_comment(report: dict) -> str:
    """The PR-comment body: the report markdown plus the find-and-update marker."""
    return f"{build_report_markdown(report)}\n{COMMENT_MARKER}"


def set_outputs(report: dict) -> None:
    """Write action outputs to the ``GITHUB_OUTPUT`` file for downstream steps."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    readiness = report.get("readiness", {})
    outputs = {
        "score": report["score"],
        "max-score": report["max_score"],
        "percentage": percentage(report["score"], report["max_score"]),
        "readiness-score": readiness.get("score", 0),
        "readiness-max": readiness.get("max_score", 0),
        "readiness-percentage": percentage(readiness.get("score", 0), readiness.get("max_score", 0)),
        "era": report.get("spec", {}).get("era", ""),
        "negotiated-version": report.get("spec", {}).get("negotiated_version", ""),
    }
    with Path(output_path).open("a", encoding="utf-8") as f:
        for key, value in outputs.items():
            f.write(f"{key}={value}\n")


def write_job_summary(report: dict) -> None:
    """Append the report to the GitHub Actions job summary (always, no token needed)."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as f:
        f.write(build_report_markdown(report) + "\n")


def _pr_number() -> int | None:
    """The pull-request number for the current event, or None if not a PR event."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).is_file():
        return None
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict) and isinstance(pull_request.get("number"), int):
        return pull_request["number"]
    return None


def _api_request(url: str, token: str, method: str = "GET", body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 — fixed api.github.com host
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode())


def post_or_update_comment(report: dict, token: str) -> None:
    """Create the mcpscore PR comment, or update the existing one in place.

    Best-effort: a missing token, insufficient permissions, or a non-PR event
    is logged and skipped — commenting must never fail the gate.
    """
    number = _pr_number()
    if number is None:
        print("Not a pull_request event; skipping comment.")
        return
    if not token:
        print("No github-token provided; skipping comment.")
        return

    repo = os.environ["GITHUB_REPOSITORY"]
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    body = build_comment(report)

    try:
        existing = _api_request(f"{api}/repos/{repo}/issues/{number}/comments?per_page=100", token)
        mine = (
            next((c for c in existing if COMMENT_MARKER in c.get("body", "")), None)
            if isinstance(existing, list)
            else None
        )
        if mine is not None:
            _api_request(f"{api}/repos/{repo}/issues/comments/{mine['id']}", token, method="PATCH", body={"body": body})
            print(f"Updated PR comment #{mine['id']}.")
        else:
            _api_request(f"{api}/repos/{repo}/issues/{number}/comments", token, method="POST", body={"body": body})
            print("Created PR comment.")
    except (urllib.error.URLError, KeyError, ValueError) as e:
        print(f"Could not post PR comment (non-fatal): {e}")


def main() -> int:
    """Run the audit, publish results, and apply the gates. Returns the exit code."""
    target = env("target")
    if not target:
        print("::error::'target' input is required")
        return 1

    version = env("version")
    extra_args = env("args").split()
    code, stdout, stderr = run_audit(target, version, extra_args)

    if not stdout.strip() or (code != 0 and code not in CLI_GATE_EXIT_CODES):
        print(f"::error::mcpscore could not audit {target} (exit {code})")
        sys.stderr.write(stderr)
        return 1

    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        print("::error::mcpscore did not emit a valid JSON report")
        sys.stderr.write(stdout)
        return 1

    report_path = Path(env("report-path", "mcpscore-report.json"))
    report_path.write_text(stdout, encoding="utf-8")
    set_outputs(report)
    write_job_summary(report)

    if env("comment", "true").lower() == "true":
        post_or_update_comment(report, env("github-token"))

    pct = percentage(report["score"], report["max_score"])
    print(f"mcpscore: {report['score']}/{report['max_score']} ({pct}%), era {report.get('spec', {}).get('era')}")

    failures = evaluate_gate(report, env("min-score"), env("min-readiness")) + cli_gate_failures(report, code)
    for reason in failures:
        print(f"::error::{reason}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
