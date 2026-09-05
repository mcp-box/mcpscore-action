## Releasing (2026-09-05)

- **`make all` before handing off** — it mirrors CI's check job (ruff, pyright,
  pytest, zizmor on the workflows). The live end-to-end workflow
  (`test-action.yml`) runs in CI only.
- **Releases are Alex's, and they are one command**: bump `version` in
  `pyproject.toml`, add the `## [X.Y.Z]` section and the compare link to
  `CHANGELOG.md`, merge, then on a clean, synced `main`: `make release-dry-run`,
  then `make release`. The script (`scripts/release.py`) creates the GitHub
  Release on tag `vX.Y.Z`; the `Publish` workflow moves the floating major tag
  (`v1`) to it and the script waits for that to happen. Never move `v1` by
  hand: a manual force-push is exactly what the workflow replaces, and the
  workflow refuses to move the tag to anything but the latest stable release.
- The version in `pyproject.toml` is the action's release version, not a
  Python package version; it exists so the release script and the changelog
  have one source.
