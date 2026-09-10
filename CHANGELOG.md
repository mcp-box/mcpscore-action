# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Users reference the action by its floating major tag (`@v1`), which every
release in the 1.x line moves; `@v1.1.1` pins one release.

## [Unreleased]

### Added

- **`sarif-path` input: the failed rules as SARIF 2.1.0 for GitHub code
  scanning.** Set it to a file and add a `github/codeql-action/upload-sarif`
  step, and every failed rule becomes an alert in the repository's Security
  tab, keyed on the rule and the target so a re-run updates it in place. The
  file is written before any gate runs, so a failing build still carries its
  findings. Needs mcpscore 1.14.0 or later (the default, latest, qualifies);
  an older `version` fails the job with a message naming the requirement.
  The README has the workflow.

## [1.1.1] - 2026-09-06

### Fixed

- **The comment token no longer reaches the audited server.** The audit
  subprocess inherited the step environment, including the `github-token`
  input, so a local target (server code from the pull request under review)
  could read a write-capable token. The action now strips its own token from
  the environment it launches mcpscore with. Secrets you export yourself,
  such as `MCPSCORE_TOKEN`, are still passed through on purpose.
- **The readiness line in the comment no longer claims readiness is never
  part of the main score.** Since mcpscore 1.1.0 a server on the modern
  lifecycle has its readiness points counted in the score, and the report
  says so (`readiness.counted_in_main`). The comment and job summary now
  read "counted in the main score" or "informative, not counted in the main
  score" accordingly.

### Changed

- The audit runs with `PYTHONFAULTHANDLER=1`, so a native crash in the CLI
  prints a traceback in the job log instead of a bare exit code.

## [1.1.0] - 2026-09-05

### Added

- **Picks up a `mcpscore.toml` from the checkout.** Rules turned off or
  re-ranked in the repository's configuration (or `[tool.mcpscore]` in
  `pyproject.toml`) shape the score the action gates on, and the PR comment
  names the file, what it changed, and the rules that tripped a configured
  `[gate]`. Needs mcpscore 1.12.0 or newer; older engines behave as before.
- **A release script and a publish workflow.** `make release` runs the
  preflight (main, clean, in sync, changelog section, tag free, CI green)
  and creates the GitHub Release; the `Publish` workflow then moves the
  floating major tag to it in CI, where the move is auditable. Previously
  the major tag was moved by hand.
- `make all` mirrors CI (ruff, pyright, pytest, zizmor), like the other
  mcpscore repositories.

### Changed

- **A CLI gate exit now publishes the report before failing the job.**
  mcpscore exits 3 for `--fail-under` and a configured `[gate]` and 4 for a
  `--smoke` failure, after writing its JSON report. The action used to treat
  any non-zero exit as "could not audit" and skip the report, outputs, job
  summary, and comment; it now publishes them and then fails the job with
  the named reason.

## [1.0.1] - 2026-08-25

### Changed

- Runtime refresh: dependency and tooling updates; the `version` input
  example follows mcpscore 1.9.0.

## [1.0.0] - 2026-07-12

### Added

- First release: audit an MCP server on every pull request with mcpscore,
  gate on `min-score` and `min-readiness`, post the report as a PR comment
  that updates in place, expose every score as a step output, and write the
  JSON report to the run.

[Unreleased]: https://github.com/mcp-box/mcpscore-action/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/mcp-box/mcpscore-action/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/mcp-box/mcpscore-action/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/mcp-box/mcpscore-action/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mcp-box/mcpscore-action/releases/tag/v1.0.0
