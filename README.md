# mcpscore-action

[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-mcpscore-059669?logo=github)](https://github.com/marketplace/actions/mcpscore-mcp-server-audit)
[![CI](https://github.com/mcp-box/mcpscore-action/actions/workflows/ci.yml/badge.svg)](https://github.com/mcp-box/mcpscore-action/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A refactor that drops a tool description or breaks a schema should fail the
pull request, not surface later inside someone's agent. This action audits
your [MCP](https://modelcontextprotocol.io) server with
[mcpscore](https://github.com/mcp-box/mcpscore), the Lighthouse for MCP:
it scores the server 0–100, fails the job below your threshold, and posts the
report as a comment that updates in place on every push.

```yaml
name: MCP quality
on: [pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write   # lets the action post its comment
    steps:
      - uses: mcp-box/mcpscore-action@v1
        with:
          target: https://your-server.example/mcp
          min-score: 80
```

Under the threshold, the job fails and the log says why:

```text
mcpscore: 70/91 (77%), era modern
::error::score 70/91 (77%) is below the required 80%
```

No API key, no setup step: the action installs the mcpscore CLI itself and
the audit is deterministic, so the same server scores the same on every run.

## What you get on every run

- **A comment on the pull request** with the score, the negotiated spec
  version and era, a pass/fail breakdown by severity, the readiness score,
  and a collapsible list of every failed check by `rule_id`, so a fix is one
  lookup in the [rules reference](https://docs.mcpscore.dev/rules) away.
  Created once, then updated in place.
- **The same report in the job summary**, which needs no token at all.
- **The JSON report** written to `report-path`, ready to upload as an
  artifact or diff between runs.
- **Every number as a step output**: score, maximum, percentage, the
  readiness trio, era, and negotiated version.

## Variations

### A server that lives in the repo

Check out the code and point `target` at the entry file. Its runtime must be
on the runner, so set up Python or Node first when the runner image lacks it.
This job runs the server code from the pull request, so give it no write
scope: checkout needs `contents: read` and nothing else, and the report is in
the job summary. Keep the commenting job, if you want one, on a remote
target that the pull request cannot change.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read         # for actions/checkout; no write scope in a job that runs PR code
    steps:
      - uses: actions/checkout@v7
      - uses: mcp-box/mcpscore-action@v1
        with:
          target: ./server.py
          min-score: 85
          comment: false     # read the job summary instead
```

### An auth-gated server

Store the credential as an Actions secret and export it as `MCPSCORE_TOKEN`.
The CLI reads it, and the value never reaches the log or the report.

```yaml
- uses: mcp-box/mcpscore-action@v1
  with:
    target: https://your-server.example/mcp
    min-score: 80
  env:
    MCPSCORE_TOKEN: ${{ secrets.MCPSCORE_TOKEN }}
```

API-key servers pass a header through `args`. The action splits `args` on
whitespace, so write the header as one token with no space after the colon:

```yaml
- uses: mcp-box/mcpscore-action@v1
  with:
    target: https://your-server.example/mcp
    args: --header=X-Api-Key:${{ secrets.MCP_API_KEY }}
```

Without a credential an auth-gated server gets a partial audit, and
`min-score` is judged on that partial score, which covers only the auth, TLS,
and transport surface. Pass a credential before trusting the gate. See
[authenticated servers](https://docs.mcpscore.dev/authenticated-servers).

### Turn rules off for this repository

A `mcpscore.toml` in the checkout is picked up on its own. Rules set to
`"off"` do not run, rules set to a severity name count at that severity, and
a `[gate] fail_on` table fails the job on any failed rule at or above it.
`min-score` then gates the configured score, and the comment says which file
applied and what it changed. The badge and the score on mcpscore.dev never
read this file. See [configure rules](https://docs.mcpscore.dev/configure-rules).

```toml
# mcpscore.toml, next to your server
[rules]
server_websiteurl_present = "off"

[gate]
fail_on = "high"
```

```text
::error::mcpscore [gate] fail_on = HIGH: failed rule(s) tools_description_present_in_all
```

### Smoke-test the tools

The audit never calls tools. For a server you own, add `--smoke` through
`args` and mcpscore calls the tools annotated read-only after the audit,
checking that structured output matches its schema and that invalid and
unknown calls are rejected. A failed check fails the job with exit code 4,
after the report and comment are published. Use it on your own development
and CI servers only. See [smoke mode](https://docs.mcpscore.dev/smoke-mode).

```yaml
- uses: actions/checkout@v7   # same job shape as the local server above
- uses: mcp-box/mcpscore-action@v1
  with:
    target: ./server.py
    min-score: 80
    args: --smoke
    comment: false
```

```text
::error::mcpscore --smoke: failed check(s) smoke_structured_content
```

### Also require readiness for MCP 2026-07-28

```yaml
- uses: mcp-box/mcpscore-action@v1
  with:
    target: https://your-server.example/mcp
    min-score: 85
    min-readiness: 50   # fail below 50% ready for MCP 2026-07-28
```

The gate is skipped only when no readiness check could be assessed at all,
which the report shows as a zero `readiness.max_score`. A legacy server still
has its gateway checks assessed, so it is gated on the few points those carry.
Check the readiness line of a run before choosing the threshold.

### Use the numbers in later steps

```yaml
- id: mcp
  uses: mcp-box/mcpscore-action@v1
  with:
    target: https://your-server.example/mcp
- run: echo "Scored ${{ steps.mcp.outputs.percentage }}% (era ${{ steps.mcp.outputs.era }})"
```

### Pin everything

`@v1` follows the latest v1 release. For reproducible runs, pin the action to
a commit and `version` to a mcpscore release:

```yaml
- uses: mcp-box/mcpscore-action@<commit-sha>  # v1.1.1
  with:
    target: https://your-server.example/mcp
    version: "1.12.0"
    min-score: 80
```

## Inputs

| Input           | Default                | What it does                                                                                                                        |
|-----------------|------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| `target`        | required               | Server URL (Streamable HTTP or SSE), or a local `.py` or `.js` path                                                                 |
| `min-score`     | no gate                | Fail the job when the main score percentage (0–100) is below this. With a `mcpscore.toml` in the repo, that is the configured score |
| `min-readiness` | no gate                | Fail the job when the readiness percentage (0–100) is below this. Skipped when readiness was not assessed                           |
| `comment`       | `true`                 | Post or update the report comment on the pull request                                                                               |
| `args`          | —                      | Extra arguments passed to the mcpscore CLI, split on whitespace. Write each as one token, for example `--header=X-Api-Key:$KEY`     |
| `version`       | latest                 | mcpscore release to run, for example `1.12.0`                                                                                       |
| `report-path`   | `mcpscore-report.json` | Where the JSON report is written                                                                                                    |
| `github-token`  | `github.token`         | Token for the comment. Needs `pull-requests: write`                                                                                 |

## Outputs

| Output                                                     | Meaning                                                         |
|------------------------------------------------------------|-----------------------------------------------------------------|
| `score`, `max-score`, `percentage`                         | Main score: points earned, points available, integer percentage |
| `readiness-score`, `readiness-max`, `readiness-percentage` | The same three for the readiness axis                           |
| `era`                                                      | `legacy`, `modern`, or `dual-era`                               |
| `negotiated-version`                                       | Spec revision the server negotiated                             |

## How the job fails

| Outcome                                                   | Log line                                                                              | Report published? |
|-----------------------------------------------------------|---------------------------------------------------------------------------------------|-------------------|
| Score under `min-score` or `min-readiness`                | `::error::score 70/91 (77%) is below the required 80%`                                | Yes               |
| A configured `[gate]` tripped (CLI exit 3)                | `::error::mcpscore [gate] fail_on = HIGH: failed rule(s) …`                           | Yes               |
| `--fail-under` passed through `args` not met (CLI exit 3) | ``::error::mcpscore exited 3: a --fail-under gate passed through `args` was not met`` | Yes               |
| A `--smoke` check failed (CLI exit 4)                     | `::error::mcpscore --smoke: failed check(s) …`                                        | Yes               |
| The server could not be audited (any other non-zero exit) | `::error::mcpscore could not audit <target> (exit N)`                                 | No                |

Every gate writes the JSON report, the step outputs, and the job summary
first, then fails the job with the reason above. The comment is posted as
well when the run is for a pull request, `comment` is on, and the token can
write; it is best-effort and never changes the outcome. Only an audit that
produced no report skips all of them.

## When it fails

**The job fails with `::error::score 70/91 (77%) is below the required 80%`**

- Cause: the server scored under the threshold. This is the action doing its
  job.
- Fix: open the comment or job summary, take the failed `rule_id`s to the
  [rules reference](https://docs.mcpscore.dev/rules), and fix the server.

**The job passes but no comment appears on the PR**

- Cause: the workflow token is read-only. GitHub does this on pull requests
  from forks, and it happens when the job lacks `permissions: pull-requests: write`.
  Commenting is best-effort and never fails the gate.
- Fix: add the permission. For fork PRs, read the report in the job
  summary instead. Do not switch the workflow to `pull_request_target` to get
  the comment: that event runs with a write token in the base repository's
  context, and checking out and running the fork's server there hands the
  token to untrusted code, while leaving the default checkout audits the base
  branch rather than the proposed change. The
  [GitHub Security Lab write-up](https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/)
  explains the trap.

**The job passes, but the comment says the audit was partial**

- Cause: the server needs a credential and the workflow passed none, so
  `min-score` was judged on the observable surface only. A clean auth
  posture scores high on a handful of checks.
- Fix: export `MCPSCORE_TOKEN` from a secret, as above, so the gate judges the
  full audit.

**A local target fails with `Server script not found`**

- Cause: no `actions/checkout` step, or the path is relative to the wrong
  directory.
- Fix: check out the repo first and use a path relative to its root.

## How scoring works

Every rule is deterministic and cites the MCP spec section it enforces; the
[methodology](https://docs.mcpscore.dev/methodology) explains the four
categories, Protocol · Primitives · Security & Auth · Readiness, and their
weights. Readiness for the next spec revision is always reported on its own
axis. Whether it also counts toward the main score depends on the server: a
server already on the new lifecycle has those points counted, a legacy server
keeps them informative.

## Releases

`@v1` moves to every 1.x release; `@v1.1.1` pins one. What changed in each
is in the [changelog](CHANGELOG.md), and the full guide with the same
examples lives at [docs.mcpscore.dev/github-action](https://docs.mcpscore.dev/github-action).

## License

MIT
