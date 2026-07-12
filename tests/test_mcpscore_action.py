"""Unit tests for the mcpscore-action orchestrator (pure logic; no network)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import mcpscore_action as action


def make_report(score: int = 88, max_score: int = 97, readiness: int = 3, readiness_max: int = 13) -> dict:
    """A report shaped like real `mcpscore --json` output."""
    return {
        "mcpscore_version": "0.8.0",
        "target": "https://server.example/mcp",
        "score": score,
        "max_score": max_score,
        "summary": {
            "total": 31,
            "passed": 19,
            "failed": 12,
            "skipped": 0,
            "by_severity": {
                "CRITICAL": {"total": 9, "passed": 6, "failed": 3},
                "HIGH": {"total": 11, "passed": 5, "failed": 6},
                "MEDIUM": {"total": 8, "passed": 5, "failed": 3},
                "LOW": {"total": 3, "passed": 3, "failed": 0},
            },
        },
        "results": [
            {"rule_id": "server_name_present", "severity": "CRITICAL", "passed": True},
            {"rule_id": "server_title_present", "severity": "MEDIUM", "passed": False},
        ],
        "spec": {
            "negotiated_version": "2025-11-25",
            "latest_version": "2025-11-25",
            "readiness_target": "2026-07-28",
            "era": "legacy",
        },
        "readiness": {"score": readiness, "max_score": readiness_max, "results": []},
    }


class TestPercentage:
    def test_normal(self):
        assert action.percentage(88, 97) == 91

    def test_zero_max_is_zero(self):
        assert action.percentage(0, 0) == 0

    def test_perfect(self):
        assert action.percentage(97, 97) == 100


class TestEvaluateGate:
    def test_no_thresholds_passes(self):
        assert action.evaluate_gate(make_report(), "", "") == []

    def test_score_above_threshold_passes(self):
        assert action.evaluate_gate(make_report(88, 97), "80", "") == []

    def test_score_below_threshold_fails(self):
        failures = action.evaluate_gate(make_report(70, 97), "80", "")
        assert len(failures) == 1
        assert "below the required 80%" in failures[0]

    def test_readiness_below_threshold_fails(self):
        failures = action.evaluate_gate(make_report(readiness=2, readiness_max=13), "", "50")
        assert len(failures) == 1
        assert "readiness" in failures[0]

    def test_readiness_gate_skipped_when_not_assessed(self):
        # A stdio server gets readiness max_score 0 — the gate must not fire.
        assert action.evaluate_gate(make_report(readiness=0, readiness_max=0), "", "50") == []

    def test_both_gates_can_fail_together(self):
        failures = action.evaluate_gate(make_report(50, 97, readiness=1, readiness_max=13), "80", "50")
        assert len(failures) == 2


class TestMarkdown:
    def test_report_markdown_has_score_and_table(self):
        md = action.build_report_markdown(make_report())
        assert "88/97 (91%)" in md
        assert "CRITICAL" in md
        assert "2025-11-25 (legacy)" in md

    def test_readiness_line_present_when_assessed(self):
        md = action.build_report_markdown(make_report(readiness=3, readiness_max=13))
        assert "Readiness for MCP 2026-07-28" in md
        assert "3/13" in md

    def test_readiness_line_absent_when_not_assessed(self):
        md = action.build_report_markdown(make_report(readiness=0, readiness_max=0))
        assert "Readiness for MCP" not in md

    def test_failed_rules_listed(self):
        md = action.build_report_markdown(make_report())
        assert "server_title_present" in md
        assert "1 failed check" in md

    def test_all_passed_message(self):
        report = make_report()
        for r in report["results"]:
            r["passed"] = True
        assert "All checks passed" in action.build_report_markdown(report)

    def test_comment_carries_the_marker(self):
        assert action.COMMENT_MARKER in action.build_comment(make_report())


class TestOutputs:
    def test_set_outputs_writes_all_keys(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        out = tmp_path / "out.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        action.set_outputs(make_report())
        written = out.read_text(encoding="utf-8")
        assert "score=88" in written
        assert "percentage=91" in written
        assert "readiness-percentage=23" in written
        assert "era=legacy" in written

    def test_set_outputs_noop_without_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        action.set_outputs(make_report())  # must not raise

    def test_job_summary_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        action.write_job_summary(make_report())
        assert "🔦 mcpscore" in summary.read_text(encoding="utf-8")


class TestPrNumber:
    def test_reads_pr_number_from_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 42}}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        assert action._pr_number() == 42

    def test_none_for_non_pr_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        assert action._pr_number() is None

    def test_none_without_event_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        assert action._pr_number() is None


class TestEnv:
    def test_reads_and_strips_input(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("INPUT_MIN_SCORE", "  80  ")
        assert action.env("min-score") == "80"

    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("INPUT_COMMENT", raising=False)
        assert action.env("comment", "true") == "true"
