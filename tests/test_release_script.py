"""Tests for scripts/release.py — the release preflight and the major-tag publish flow."""

import json
from pathlib import Path

import pytest
import release


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-09-05\n\nThe notes body.\n\n"
        "## [1.2.2] - 2026-09-01\n\nOlder.\n\n"
        "[Unreleased]: https://github.com/mcp-box/mcpscore-action/compare/v1.2.3...HEAD\n"
        "[1.2.3]: https://github.com/mcp-box/mcpscore-action/compare/v1.2.2...v1.2.3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release, "ROOT", tmp_path)
    return tmp_path


class TestVersion:
    def test_reads_project_version(self, repo: Path):
        assert release.read_version() == "1.2.3"

    @pytest.mark.parametrize(("version", "tag"), [("1.2.3", "v1"), ("2.0.0", "v2"), ("10.4.1", "v10")])
    def test_major_tag(self, version: str, tag: str):
        assert release.major_tag(version) == tag

    @pytest.mark.parametrize("version", ["1.2", "1.2.3b1", "1.2.3-rc.1", "v1.2.3"])
    def test_rejects_anything_but_stable_semver(self, version: str):
        with pytest.raises(SystemExit):
            release.major_tag(version)


class TestChangelog:
    def test_extracts_the_matching_section(self, repo: Path):
        assert release.check_changelog("1.2.3") == "The notes body."

    def test_fails_without_a_section(self, repo: Path):
        with pytest.raises(SystemExit):
            release.check_changelog("9.9.9")

    def test_fails_without_the_compare_link(self, repo: Path):
        path = repo / "CHANGELOG.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("[1.2.3]: https://", "[1.2.3]: nope "), encoding="utf-8"
        )
        with pytest.raises(SystemExit):
            release.check_changelog("1.2.3")

    def test_fails_on_unresolved_conflict_markers(self, repo: Path):
        path = repo / "CHANGELOG.md"
        path.write_text("<<<<<<< HEAD\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        with pytest.raises(SystemExit):
            release.check_changelog("1.2.3")


class TestGitState:
    def _fake_run(self, monkeypatch: pytest.MonkeyPatch, answers: dict[str, str]) -> None:
        def fake_run(*args: str, capture: bool = True) -> str:
            return answers[" ".join(args)]

        monkeypatch.setattr(release, "run", fake_run)

    def test_passes_on_clean_synced_main(self, monkeypatch: pytest.MonkeyPatch):
        self._fake_run(
            monkeypatch,
            {
                "git branch --show-current": "main",
                "git status --porcelain": "",
                "git rev-parse HEAD": "abc123",
                f"gh api repos/{release.REPO}/commits/main --jq .sha": "abc123",
            },
        )
        assert release.check_git_state() == "abc123"

    def test_fails_off_main(self, monkeypatch: pytest.MonkeyPatch):
        self._fake_run(monkeypatch, {"git branch --show-current": "feat/x"})
        with pytest.raises(SystemExit):
            release.check_git_state()

    def test_fails_when_dirty(self, monkeypatch: pytest.MonkeyPatch):
        self._fake_run(monkeypatch, {"git branch --show-current": "main", "git status --porcelain": " M x"})
        with pytest.raises(SystemExit):
            release.check_git_state()

    def test_fails_when_out_of_sync(self, monkeypatch: pytest.MonkeyPatch):
        self._fake_run(
            monkeypatch,
            {
                "git branch --show-current": "main",
                "git status --porcelain": "",
                "git rev-parse HEAD": "abc123",
                f"gh api repos/{release.REPO}/commits/main --jq .sha": "def456",
            },
        )
        with pytest.raises(SystemExit):
            release.check_git_state()


class TestCiGreen:
    def _runs(self, monkeypatch: pytest.MonkeyPatch, runs: list[dict]) -> None:
        monkeypatch.setattr(release, "run", lambda *a, **k: json.dumps(runs))

    def test_green(self, monkeypatch: pytest.MonkeyPatch):
        self._runs(
            monkeypatch,
            [
                {
                    "name": "check",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "1",
                    "completed_at": "2",
                },
                {
                    "name": "run-against-live-server",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "1",
                    "completed_at": "2",
                },
            ],
        )
        release.check_ci_green("abc")

    def test_review_bots_are_not_gates(self, monkeypatch: pytest.MonkeyPatch):
        self._runs(
            monkeypatch,
            [
                {
                    "name": "check",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "1",
                    "completed_at": "2",
                },
                {
                    "name": "copilot-pull-request-reviewer",
                    "status": "in_progress",
                    "conclusion": None,
                    "started_at": "3",
                    "completed_at": None,
                },
            ],
        )
        release.check_ci_green("abc")

    def test_latest_run_per_check_wins(self, monkeypatch: pytest.MonkeyPatch):
        self._runs(
            monkeypatch,
            [
                {
                    "name": "check",
                    "status": "completed",
                    "conclusion": "failure",
                    "started_at": "1",
                    "completed_at": "2",
                },
                {
                    "name": "check",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "3",
                    "completed_at": "4",
                },
            ],
        )
        release.check_ci_green("abc")

    def test_red(self, monkeypatch: pytest.MonkeyPatch):
        self._runs(
            monkeypatch,
            [{"name": "check", "status": "completed", "conclusion": "failure", "started_at": "1", "completed_at": "2"}],
        )
        with pytest.raises(SystemExit):
            release.check_ci_green("abc")

    def test_no_runs(self, monkeypatch: pytest.MonkeyPatch):
        self._runs(monkeypatch, [])
        with pytest.raises(SystemExit):
            release.check_ci_green("abc")


class TestMajorTagWait:
    def test_returns_once_the_tag_points_at_the_release(self, monkeypatch: pytest.MonkeyPatch):
        answers = iter(["old", "old", "abc123"])

        class Result:
            returncode = 0

            def __init__(self) -> None:
                self.stdout = next(answers) + "\n"

        monkeypatch.setattr(release.subprocess, "run", lambda *a, **k: Result())
        monkeypatch.setattr(release.time, "sleep", lambda s: None)

        release.wait_for_major_tag("1.2.3", "abc123")

    def test_fails_after_the_deadline(self, monkeypatch: pytest.MonkeyPatch):
        class Result:
            returncode = 0
            stdout = "old\n"

        clock = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0])
        monkeypatch.setattr(release.subprocess, "run", lambda *a, **k: Result())
        monkeypatch.setattr(release.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(release.time, "sleep", lambda s: None)

        with pytest.raises(SystemExit):
            release.wait_for_major_tag("1.2.3", "abc123")
