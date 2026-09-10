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

    def test_readiness_line_says_counted_for_a_modern_lifecycle_server(self):
        report = make_report(readiness=3, readiness_max=13)
        report["readiness"]["counted_in_main"] = True
        md = action.build_report_markdown(report)
        assert "3/13 (23%) — counted in the main score." in md

    def test_readiness_line_says_informative_when_not_counted(self):
        report = make_report(readiness=3, readiness_max=13)
        report["readiness"]["counted_in_main"] = False
        assert "informative, not counted in the main score." in action.build_report_markdown(report)
        # An engine older than the key never counted readiness: same wording.
        report["readiness"].pop("counted_in_main")
        assert "informative, not counted in the main score." in action.build_report_markdown(report)

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


def make_configured_report(gate_failed: list[str] | None = None) -> dict:
    report = make_report()
    report["config"] = {
        "source": "mcpscore.toml",
        "sha256": "abc",
        "disabled": ["server_websiteurl_present", "server_icons_present"],
        "reranked": {"server_title_present": {"from": "MEDIUM", "to": "CRITICAL"}},
        "unknown": [],
    }
    if gate_failed is not None:
        report["config"]["gate"] = {"fail_on": "CRITICAL", "failed": gate_failed}
    return report


class TestConfiguredRuns:
    def test_markdown_names_the_config_and_what_it_changed(self):
        body = action.build_report_markdown(make_configured_report())

        assert "**Config:** `mcpscore.toml` — 2 rules off, 1 re-ranked" in body
        assert "Gate failed" not in body

    def test_markdown_lists_the_rules_that_tripped_the_gate(self):
        body = action.build_report_markdown(make_configured_report(gate_failed=["server_title_present"]))

        assert "gate at CRITICAL" in body
        assert "**Gate failed:** 1 rule(s) at or above CRITICAL: `server_title_present`" in body

    def test_markdown_without_config_is_unchanged(self):
        assert "Config:" not in action.build_report_markdown(make_report())

    def test_cli_gate_exit_3_is_explained_from_the_config_block(self):
        report = make_configured_report(gate_failed=["a", "b"])

        assert action.cli_gate_failures(report, 3) == ["mcpscore [gate] fail_on = CRITICAL: failed rule(s) a, b"]

    def test_cli_gate_exit_3_without_a_config_gate_blames_args(self):
        assert action.cli_gate_failures(make_report(), 3) == [
            "mcpscore exited 3: a --fail-under gate passed through `args` was not met"
        ]

    def test_cli_gate_exit_4_lists_failed_smoke_checks(self):
        report = make_report()
        report["smoke"] = {
            "checks": [{"check_id": "smoke_unknown_tool", "verdict": "fail"}, {"check_id": "x", "verdict": "pass"}]
        }

        assert action.cli_gate_failures(report, 4) == ["mcpscore --smoke: failed check(s) smoke_unknown_tool"]

    def test_clean_exit_has_no_cli_gate_failures(self):
        assert action.cli_gate_failures(make_report(), 0) == []


class TestMainWithCliGates:
    """A CLI gate exit still publishes the report, then fails the job with the reason."""

    FAKE_TOKEN = "not-a-real-token"  # noqa: S105 — a test fixture value, not a credential

    def _run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, stdout: str
    ) -> tuple[int, list[str], bool]:
        printed: list[str] = []
        commented = {"called": False}
        # The environment a real pull_request run has: the event payload with the
        # PR number, and the token action.yml defaults to github.token.
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps({"pull_request": {"number": 7}}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        monkeypatch.setenv("GITHUB_REPOSITORY", "mcp-box/example")
        monkeypatch.setenv("INPUT_GITHUB_TOKEN", self.FAKE_TOKEN)
        monkeypatch.setenv("INPUT_TARGET", "https://server.example/mcp")
        monkeypatch.setenv("INPUT_REPORT_PATH", str(tmp_path / "report.json"))
        monkeypatch.setenv("INPUT_COMMENT", "true")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setattr(action, "run_audit", lambda *a: (code, stdout, ""))

        def fake_comment(report: dict, token: str) -> None:
            # Only the network call is stubbed; the arguments are the real ones.
            assert token == self.FAKE_TOKEN
            assert action._pr_number() == 7
            commented["called"] = True

        monkeypatch.setattr(action, "post_or_update_comment", fake_comment)
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
        return action.main(), printed, commented["called"]

    def test_config_gate_failure_publishes_the_report_and_fails_with_the_rules(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        report = make_configured_report(gate_failed=["server_title_present"])

        code, printed, commented = self._run(monkeypatch, tmp_path, 3, json.dumps(report))

        assert code == 1
        assert (tmp_path / "report.json").exists()
        assert commented is True
        assert any(
            "::error::mcpscore [gate] fail_on = CRITICAL: failed rule(s) server_title_present" in p for p in printed
        )

    def test_a_real_failure_still_reports_could_not_audit(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        code, printed, commented = self._run(monkeypatch, tmp_path, 2, "")

        assert code == 1
        assert commented is False
        assert any("could not audit" in p for p in printed)


class TestSarifPath:
    """`sarif-path` passes `--sarif <path>` to the CLI, which writes the file itself."""

    def _cmd(self, monkeypatch: pytest.MonkeyPatch, **kwargs) -> list[str]:
        seen: dict[str, list[str]] = {}

        def fake_run(cmd, **_):
            seen["cmd"] = cmd

            class Result:
                returncode, stdout, stderr = 0, "{}", ""

            return Result()

        monkeypatch.setattr(action.subprocess, "run", fake_run)
        action.run_audit("https://server.example/mcp", "", ["--smoke"], **kwargs)
        return seen["cmd"]

    def test_sarif_flag_precedes_the_extra_args(self, monkeypatch: pytest.MonkeyPatch):
        assert self._cmd(monkeypatch, sarif_path="out.sarif") == [
            "uvx",
            "mcpscore",
            "https://server.example/mcp",
            "--json",
            "--sarif",
            "out.sarif",
            "--smoke",
        ]

    def test_no_sarif_flag_by_default(self, monkeypatch: pytest.MonkeyPatch):
        assert "--sarif" not in self._cmd(monkeypatch)

    def test_main_passes_the_input_through(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        calls: list[tuple] = []
        monkeypatch.setenv("INPUT_TARGET", "https://server.example/mcp")
        monkeypatch.setenv("INPUT_SARIF_PATH", "findings.sarif")
        monkeypatch.setenv("INPUT_REPORT_PATH", str(tmp_path / "report.json"))
        monkeypatch.setenv("INPUT_COMMENT", "false")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        def fake_run_audit(*args):
            calls.append(args)
            return 0, json.dumps(make_report()), ""

        monkeypatch.setattr(action, "run_audit", fake_run_audit)
        assert action.main() == 0
        assert calls == [("https://server.example/mcp", "", [], "findings.sarif")]

    def test_stdout_is_refused_as_a_sarif_path(self, monkeypatch: pytest.MonkeyPatch):
        printed: list[str] = []
        monkeypatch.setenv("INPUT_TARGET", "https://server.example/mcp")
        monkeypatch.setenv("INPUT_SARIF_PATH", "-")
        monkeypatch.setattr(action, "run_audit", lambda *a: pytest.fail("the CLI must not run"))
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
        assert action.main() == 1
        assert any("'sarif-path' must be a file path" in p for p in printed)

    def test_an_engine_without_the_flag_names_the_version_needed(self, monkeypatch: pytest.MonkeyPatch):
        printed: list[str] = []
        monkeypatch.setenv("INPUT_TARGET", "https://server.example/mcp")
        monkeypatch.setenv("INPUT_SARIF_PATH", "findings.sarif")
        monkeypatch.setenv("INPUT_VERSION", "1.13.0")
        stderr = "usage: mcpscore [-h] ...\nUsage error: unrecognized arguments: --sarif findings.sarif\n"
        monkeypatch.setattr(action, "run_audit", lambda *a: (1, "", stderr))
        monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
        assert action.main() == 1
        assert any("could not audit" in p for p in printed)
        assert any(f"needs mcpscore {action.SARIF_MIN_VERSION} or later" in p for p in printed)


class TestPartialConfigBlocks:
    """The report is another program's output: a thin gate block must not crash the comment."""

    def test_gate_without_fail_on_still_renders(self):
        report = make_configured_report()
        report["config"]["gate"] = {"failed": ["a"]}

        body = action.build_report_markdown(report)

        assert "gate at ?" in body
        assert "**Gate failed:** 1 rule(s) at or above ?: `a`" in body
        assert action.cli_gate_failures(report, 3) == ["mcpscore [gate] fail_on = ?: failed rule(s) a"]

    def test_gate_without_failed_renders_no_gate_failure(self):
        report = make_configured_report()
        report["config"]["gate"] = {"fail_on": "HIGH"}

        assert "Gate failed" not in action.build_report_markdown(report)


class TestAuditEnvironment:
    FAKE_TOKEN = "ghs_not_a_real_token"  # noqa: S105
    USER_CREDENTIAL = "user-supplied-credential"

    def test_the_comment_token_is_stripped_from_the_audit_subprocess(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("INPUT_GITHUB_TOKEN", self.FAKE_TOKEN)
        monkeypatch.setenv("MCPSCORE_TOKEN", self.USER_CREDENTIAL)
        monkeypatch.setenv("INPUT_TARGET", "./server.py")
        seen: dict = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["env"] = kwargs["env"]

            class Result:
                returncode = 0
                stdout = "{}"
                stderr = ""

            return Result()

        monkeypatch.setattr(action.subprocess, "run", fake_run)

        action.run_audit("./server.py", "", [])

        assert "INPUT_GITHUB_TOKEN" not in seen["env"]
        assert self.FAKE_TOKEN not in seen["env"].values()
        # Everything else the step had is still there: the user's own secrets are
        # theirs to pass, and PATH is what finds uvx.
        assert seen["env"]["MCPSCORE_TOKEN"] == self.USER_CREDENTIAL
        assert seen["env"]["INPUT_TARGET"] == "./server.py"
        assert "PATH" in seen["env"]
        assert seen["cmd"][:2] == ["uvx", "mcpscore"]
