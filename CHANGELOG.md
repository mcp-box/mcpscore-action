# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Users reference the action by its floating major tag (`@v1`), which every
release in the 1.x line moves; `@v1.1.0` pins one release.

## [Unreleased]

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

[Unreleased]: https://github.com/mcp-box/mcpscore-action/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/mcp-box/mcpscore-action/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/mcp-box/mcpscore-action/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mcp-box/mcpscore-action/releases/tag/v1.0.0
