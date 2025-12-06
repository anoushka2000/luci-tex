Read the following refactoring plan, then follow it.

# Refactor Plan for luci-tex

This plan breaks the codebase into clearer modules, improves testability, and keeps the CLI stable. Imports may change (breaking imports is acceptable), but CLI commands and flags must remain identical.

- Do not change CLI command names or flags.
- Continuously run tests and linting after each phase.
- Reorganize tests to match the new module layout without changing test content.

## Baseline (Phase 0)
1. Run and record current status:
   - `uv run pytest -q`
   - `uv run ruff check .` and `uv run ruff format --check .`
   - `uv run luci --help`
2. Note any test skips related to external tools (tectonic, bibtex-tidy).

## Target Package Layout
Create structured subpackages. Names below are directories under `src/luci/`:

- `cli.py`: Keep only Typer wiring; delegate to internal APIs.
- `check/`
  - `models.py`: `Severity`, `Location`, `Issue` and JSON serializers.
  - `context.py`: File/page context inference.
  - `detectors.py`: Citation/reference/acronym/missing-file/overfull with a registry.
  - `scanner.py`: `find_logs`, `scan_logs`, composition over registry.
  - `api.py`: `run_check(...)` orchestrator returning issues + status (no Typer).
- `archive/`
  - `flatten.py`: `strip_paths_from_command`, `flatten_latex`.
  - `passes.py`: `replace_citeauthor_commands` and a simple pass pipeline.
  - `pack.py`: `create_archive`, `add_bbl_file`.
  - `validate.py`: `validate_archive` via tectonic, structured result.
  - `api.py`: `build_archive(...)` orchestrator (flatten → passes → pack → validate).
- `bib/`
  - `merge.py`: `merge_bibtex_files`.
  - `dedupe.py`: `run_bibtex_tidy_dedupe` (wrapper + parsing).
  - `rewrite.py`: `update_citation` (pure transform + file IO wrapper).
- `acronym/`
  - `parse.py`: `parse_acrodefs_from_file`.
  - `merge.py`: `merge_acrodef_files`.
  - `format.py`: `format_acrodefs`.
- `utils/`
  - `ext.py`: External tool wrappers (tectonic, bibtex-tidy) with timeouts.
  - `io.py`: Safe read/write helpers.
  - `logging.py`: Shared logger configuration.
  - `config.py` (optional): Read `.luci.toml` for defaults (thresholds, build dir).

CLI must call `check.api.run_check`, `archive.api.build_archive`, `bib.merge/dedupe/rewrite`, and `acronym` APIs, preserving the same CLI flags and help text.

## Phase 1 — Extract Modules (No CLI changes)
Goal: Move code into subpackages and establish clean APIs. Imports may change.

1. Create subpackage directories and `__init__.py` files.
2. Move code:
   - From `check.py` → `check/models.py`, `check/context.py`, `check/detectors.py`, `check/scanner.py`, `check/api.py`.
   - From `archive.py` → `archive/flatten.py`, `archive/passes.py`, `archive/pack.py`, `archive/validate.py`, `archive/api.py`.
   - From `bibparse.py` → keep as-is or under `bib/parse.py` if needed by `archive/passes.py`.
   - From `bibtools.py` → `bib/merge.py`, `bib/dedupe.py`, `bib/rewrite.py`.
   - From `acromerge.py` → `acronym/parse.py`, `acronym/merge.py`, `acronym/format.py`.
3. In `cli.py`, rewire implementations to the new APIs but keep all commands/flags identical.
4. Replace direct subprocess usage with thin wrappers in `utils/ext.py` (tectonic/bibtex-tidy). Keep behavior identical; raise on failure.
5. Keep function signatures internally typed. Avoid `typer.Exit` inside library code; return values for CLI to convert to exit codes.
6. Verification:
   - `uv run ruff check --fix .` and `uv run ruff format .`
   - `uv run pytest -q`
   - `uv run luci --help` (ensure commands/flags unchanged)
   - Run targeted: `uv run pytest tests/test_check.py -q`, `tests/test_archive.py -q`, `tests/test_merge_bibs.py -q`, `tests/test_fix_dups.py -q`, `tests/test_merge_acronyms.py -q`.

## Phase 2 — Detector Registry and Scan Composition
Goal: Make `check` detectors pluggable while preserving output.

1. Define detector protocol in `check/detectors.py`: `DetectorFn(lines, i, line, ctx) -> Issue | None`.
2. Register built-in detectors: citation, reference, acronym, missing-file, overfull.
3. Update `check/scanner.py` to iterate the registry; behavior unchanged.
4. Keep JSON output schema exactly as today.
5. Verification:
   - `uv run pytest tests/test_check.py -q`
   - `uv run pytest tests/test_check_e2e.py -q` (skips OK)

## Phase 3 — Archive Pipeline and Validation Isolation
Goal: Split flattening/packing/validation and introduce text passes.

1. Ensure `archive/passes.py` exposes a pipeline list; include `replace_citeauthor_commands` (uses `bibparse` helpers).
2. `archive/validate.py` runs tectonic using `utils/ext.py`; return struct with `returncode`, `stdout`, `stderr`, and attach emitted logs to error messages.
3. Keep `archive.api.build_archive` accepting same CLI parameters; preserve defaults and flag names.
4. Verification:
   - `uv run pytest tests/test_archive.py -q`
   - `uv run pytest tests/test_citeauthor_replace.py -q`

## Phase 4 — Logging and Error Handling
Goal: Centralize logging and improve errors without changing CLI surface.

1. Add `utils/logging.py` to set a sensible default logger for library code.
2. Replace stray `print` with logging in libraries; `cli.py` uses `typer.echo` for UI output.
3. Ensure exceptions are informative; CLI translates to exit codes exactly as before.
4. Verification:
   - `uv run pytest -q`

## Phase 5 — Optional Config Support (Non-breaking)
Goal: Allow `.luci.toml` for defaults; CLI flags override config.

1. Add `utils/config.py` to read optional defaults: `overflow_threshold_pt`, default `build_dir`, detector toggles.
2. Wire config reads in `check.api.run_check` and `archive.api.build_archive` only for defaulting. Do not alter flag names/semantics.
3. Verification:
   - Add a temporary `.luci.toml` in a throwaway test directory and manually verify defaults; do not modify existing tests.
   - `uv run pytest -q` (should remain unaffected).

## Phase 6 — Test Reorganization (No Content Changes)
Goal: Align tests with new package structure; keep content identical.

1. Create subfolders under `tests/`:
   - `tests/check/` → move `test_check.py`, `test_check_e2e.py`, `test_acronym_validate.py`.
   - `tests/archive/` → move `test_archive.py`, `test_citeauthor_replace.py`.
   - `tests/bib/` → move `test_merge_bibs.py`, `test_fix_dups.py`.
   - `tests/acronym/` → move `test_merge_acronyms.py`.
2. Keep `tests/conftest.py` at `tests/` root; ensure imports still resolve.
3. Do not modify test bodies. Only move files.
4. Verification:
   - `uv run pytest -q`
   - Spot-run per folder: `uv run pytest tests/check -q`, etc.

## Phase 7 — Cleanup and Docs
Goal: Remove dead code and update docs.

1. Remove now-empty legacy modules if any remain (breaking imports is acceptable per constraints).
2. Ensure `src/luci/__init__.py` exposes the CLI entry points unchanged.
3. Update Sphinx docs:
   - Add architecture overview and extension points (detector registry, archive passes).
   - Update CLI docs to confirm flags unchanged.
4. Verification:
   - `uv run --group docs sphinx-autobuild docs build/html` (manual inspection)
   - `uv run pytest -q`

## Continuous Verification Checklist (Run Often)
- `uv run pytest -q`
- `uv run ruff check --fix .` and `uv run ruff format .`
- `uv run luci --help`
- Focused tests for touched area (e.g., `uv run pytest tests/check/test_check.py -q`).

## Acceptance Criteria
- All tests pass (skips respected for missing external tools).
- CLI commands and flags exactly match current behavior (`check`, `archive`, `merge-bibs`, `fix-dups`, `merge-acronyms`).
- `check --json` output schema unchanged.
- Code organized per target layout; no functional regressions.
