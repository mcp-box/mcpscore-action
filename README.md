# mcpscore-action

Audit an [MCP](https://modelcontextprotocol.io) server in CI with
[mcpscore](https://github.com/mcp-box/mcpscore) — **Lighthouse for MCP**. Score
your server, gate the build on a threshold, and get the report as a pull-request
comment.

```yaml
- uses: mcp-box/mcpscore-action@v1
  with:
    target: https://your-server.example/mcp
    min-score: 80
```

## What it does

- Runs `mcpscore <target> --json` (deterministic, no API keys).
- **Gates the build** when the score — or the next-spec readiness score — is
  below a threshold you set.
- **Comments the report on the PR** (created once, updated in place on re-runs).
- Writes a job summary, saves the JSON report, and exposes every number as a
  step output.

## Usage

### Gate a pull request on quality

```yaml
name: MCP quality
on: [pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write  # for the PR comment
    steps:
      - uses: mcp-box/mcpscore-action@v1
        with:
          target: https://your-server.example/mcp
          min-score: 80
```

### Audit a local server, and use the outputs

```yaml
- uses: actions/checkout@v4
- id: mcp
  uses: mcp-box/mcpscore-action@v1
  with:
    target: ./server.py
    min-score: 85
    min-readiness: 50   # also require readiness for the upcoming spec
- run: echo "Scored ${{ steps.mcp.outputs.percentage }}% (era ${{ steps.mcp.outputs.era }})"
```

### Turn rules off for this repository

A `mcpscore.toml` in the checkout is picked up on its own. Rules set to `"off"`
do not run, rules set to a severity name count at that severity, and a
`[gate] fail_on = "high"` table fails the job on any failed rule at or above
it. `min-score` then gates the configured score, and the comment says which
file applied and what it changed. It never changes the badge or the score on
mcpscore.dev. Details: [configure rules](https://docs.mcpscore.dev/configure-rules).

```toml
[rules]
server_websiteurl_present = "off"

[gate]
fail_on = "high"
```

## Inputs

| Input           | Default                | Description                                             |
|-----------------|------------------------|---------------------------------------------------------|
| `target`        | — (required)           | MCP server URL, or local `.py`/`.js` path               |
| `version`       | latest                 | mcpscore version to run (e.g. `1.12.0`)                 |
| `min-score`     | none                   | Fail if the main score % is below this (0–100)          |
| `min-readiness` | none                   | Fail if the readiness % is below this (0–100)           |
| `comment`       | `true`                 | Post/update a report comment on the PR                  |
| `args`          | —                      | Extra arguments passed to the mcpscore CLI              |
| `report-path`   | `mcpscore-report.json` | Where to write the JSON report                          |
| `github-token`  | `github.token`         | Token for the PR comment (needs `pull-requests: write`) |

## Outputs

| Output                                                       | Description                        |
|--------------------------------------------------------------|------------------------------------|
| `score` / `max-score` / `percentage`                         | Main score                         |
| `readiness-score` / `readiness-max` / `readiness-percentage` | Next-spec readiness score          |
| `era`                                                        | `legacy`, `modern`, or `dual-era`  |
| `negotiated-version`                                         | Spec version the server negotiated |

## How scoring works

See the [mcpscore methodology](https://docs.mcpscore.dev/methodology) — every
rule is deterministic and anchored to the MCP spec. The readiness score is
always reported separately and never mixed into the main score.

## License

MIT
