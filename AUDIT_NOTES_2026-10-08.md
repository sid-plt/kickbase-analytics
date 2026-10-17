# Quick project audit — 8 October 2026

This is a static audit of the current working tree, including existing uncommitted changes. No implementation updates were made. The only additions are this note and the accompanying file inventory.

## Scope and checks

- Inventoried 625 project files: 39 Python files, 56 notebooks (48 active/diagnostic and 8 archived), 264 JSON files, 162 CSV files, 90 images, and 14 other files.
- Parsed all Python files with Python's AST parser and all JSON/notebook files with the JSON parser. Checked CSV row widths against their headers. No errors were found in these checks.
- Scanned notebook code, identified repeated functions, inspected shared modules, CI, requirements, documentation, reference stores, exporters, collectors, and analysis scripts.
- Checked team-form references in all 9 current derived-points JSON files and all 10 percentile-rating JSON files: all 19 referenced files currently exist.
- Excluded `.git`, virtual environments, Python/Jupyter caches, and pytest temporary directories. Images were inventoried, not visually inspected; saved HTML was inventoried, not executed. Notebook JSON validity does not prove every cell executes successfully.
- Did not run collectors, exporters, pruning, calibration, notebook execution, or the full test suite, because these can write files or depend on live services. No runtime performance benchmarks or dependency vulnerability/version checks were performed.

The companion `AUDIT_FILE_INVENTORY_2026-10-08.csv` lists every included file and the check applied. This is a quick audit, not a line-by-line correctness review of every historical data value.

## Prioritized findings

### 1. High — CI skips the pytest-style tests

**Where:** `.github/workflows/ci.yml`, `tests/test_*.py`.

CI runs `python -m unittest discover -s tests`, while README recommends pytest. Static inspection found 68 module-level pytest-style test functions and 46 unittest-style test methods. Unittest discovery does not execute the module-level functions, including parametrized tests and fixture-based checks for points, selected lineups, calibration, and metric consistency.

**Suggested update:** use pytest in CI and make collected test counts visible. Keep the existing unittest tests; pytest supports both styles. The 68 count is function definitions, not the final parametrized case count.

### 2. High — Six optimizer notebooks duplicate substantial shared logic

**Where:** every `optimize_squad_*.ipynb` in `notebooks/07_squad_optimisation`, plus `manual_lineup_helpers.py`.

The six notebooks contain roughly 1,362–1,514 lines of code each. AST comparison found identical implementations of score discovery, column validation, decimal parsing, score integerization, position normalization, fixture parsing, and team mapping across all six. Much of the same preprocessing already exists in the manual helper module. Fixes and rule changes therefore need to be repeated across several independent copies.

**Suggested update:** extract reusable data preparation and solver logic into modules; make arena rules configuration objects and leave notebooks as configuration, display, and selection interfaces. Preserve captain handling, squad size, club/match limits, and the existing two-stage objective.

### 3. Medium — Retention is independent of source dependencies

**Where:** `project_paths.py:116`, `sofascore_kickbase_percentile_ratings.py:99` and `:178`, `sofascore_kickbase_points_per_minute_odds_lineup_score.py:65`, `sofascore_metric_consistency.py:130`.

Pruning deletes old files by family and creation timestamp without checking whether retained derived exports reference them. Rating, points-per-90, and consistency loaders reopen the exact team-form filename stored in `source_file`. All 19 references checked are present today, but different export cadences can leave a retained derived output pointing at a pruned source. A final cleanup cell also scans the whole outputs tree, so one notebook can remove another workflow's history.

**Suggested update:** protect referenced inputs, bundle lineage with runs, or scope retention to complete run sets. Add a dry-run summary and handle invalid calendar timestamps without aborting the whole cleanup. Explicitly decide how the ten-file global limits interact with budgets and score methods.

### 4. Medium — MD3 analysis scripts select current snapshots for historical analysis

**Where:** `outputs/analysis/compare_md3.py:13`, `outputs/analysis/compare_md3_calibrated.py:16`.

Both scripts use the lexicographically greatest current points and KBStats JSON files, but assert that selected Bundesliga fixtures are from 11–13 September 2026. The current folders contain newer October snapshots. This makes historical reproduction fragile and can cause date assertions to fail as data advances. The scripts also execute analysis and write output at import time.

**Suggested update:** move reusable scripts into `scripts/`, add explicit matchday/source arguments and a main guard, and select snapshots by historical cutoff. Import shared identity constants through a stable module instead of extracting them from another module's AST.

### 5. Medium — Phone upload replacement has a concurrent-format race

**Where:** `kickbase_screenshot_intake.py:193`, upload persistence in `IntakeHandler.do_POST` around lines 343–356.

The threaded server atomically replaces each individual image, then deletes alternate formats for the same team. Concurrent JPG and PNG uploads can each delete the other's newly saved file, even though both requests report success. Signature checks also only examine the first few bytes, so a truncated file with a valid prefix is accepted as an image.

**Suggested update:** serialize replacement/alternate-format cleanup by matchday and team. Decode and validate the image before accepting it. Add bounded request read timeouts so incomplete uploads cannot indefinitely occupy handler threads. Retain the existing PIN expiry, rate limit, team whitelist, and safe filenames.

### 6. Medium — Reference CSV persistence should be more robust

**Where:** `player_name_cross_references.py:55`, `kickbase_player_name_cross_references.py:73`.

The provider-ID mapping writes directly to the final CSV, allowing an interrupted write to leave a partial store. The name-only store uses atomic replacement, but a fixed `.csv.tmp` filename can collide between notebooks. Validation in the provider-ID store also converts numeric IDs to integers without first rejecting fractional values.

**Suggested update:** use unique temporary files with atomic replacement, share validation between load and save, reject non-integral IDs, and add a lock or conflict check for concurrent read-modify-write operations. `selected_lineups.py` already demonstrates unique temporary-file replacement.

### 7. Medium — Latest score discovery can silently change the scoring method

**Where:** `manual_lineup_helpers.py:221`, duplicated `discover_latest_score` functions in optimizer notebooks.

Selection searches every `expected_points_*.csv` and picks the newest metric creation timestamp across all score methods. Running an experimental or randomized score notebook can make it the next optimizer input. The metadata includes the method, but discovery does not constrain it.

**Suggested update:** support an explicit method/source selection and show method, source date, and matchday together before optimization. Keep a deliberate latest-any-method option if that behavior is useful.

### 8. Medium — Optimizer tests check source text rather than solver behavior

**Where:** `tests/test_all_limits_arena_notebook.py`, `tests/test_insider_arena_notebook.py`.

These tests assert that configuration strings and constraint names exist in notebook source. They do not establish that returned squads satisfy the rules or that captain scoring and tie-breaking are correct. They also require empty notebook outputs, coupling rule checks to notebook presentation state.

**Suggested update:** after extracting the solver, use a small synthetic player pool with a known optimum and check returned squad constraints, captain choice, infeasibility, and the secondary objective. Keep source checks only where they verify notebook wiring.

### 9. Medium — Notebook payloads and stored snapshots make the repository heavy

**Where:** `notebooks/09_reflection/05_sofascore_kickbase_metric_consistency.ipynb`, `outputs/sofascore/player_kickbase_point_averages`, `tests/outputs`.

The consistency notebook is approximately 15 MB; individual derived-points JSON files reach about 9.7 MB. There are 250 files under tests, many historical snapshots rather than small fixtures. Saved rich plots and repeated full data increase checkout size, review noise, and loading costs.

**Suggested update:** preserve the requested inline reflection plots, but reduce repeated embedded payloads or export detailed views separately. Identify which historical snapshots are required for reproducibility and calibration before changing storage; replace unnecessary test data with compact fixtures. Consider compressed artifacts or a deliberate large-file policy rather than deleting history wholesale.

### 10. Medium — Ignore rules do not match documented local-file policy

**Where:** `.gitignore`, README version-control conventions, `data/kickbase_lineup_screenshots`.

README says not to commit screenshots, but `.gitignore` does not exclude them and the current MD5 image directory is untracked. `.venv-tf`, pytest caches, and pytest temporary directories are also absent from the ignore rules. Git status reports permission warnings on some pytest directories.

**Suggested update:** distinguish curated fixtures from private screenshot intake, ignore local intake images and temporary/environment directories, and resolve inaccessible temporary directories separately. Keep intentionally versioned reference images only through an explicit policy.

### 11. Medium — Matchday screenshot generator is a one-off workflow bypass

**Where:** `generate_kickbase_md5.ps1`.

Teams, fixtures, matchday 5, and counts are hardcoded. The output path is relative to the working directory, export does not use `project_paths.py`, and the shared retention policy is not invoked. A broad `^ONY` name rewrite also embeds a transcription correction in export code.

**Suggested update:** treat this as an explicitly archived MD5 transcription tool, or replace it with a parameterized validated exporter using canonical fixtures, explicit corrections, shared paths, and consistent retention. Preserve the displayed-name-only identity policy.

### 12. Lower — Profile and simplify repeated scoring lookups

**Where:** `sofascore_rating_odds_lineup_score.py:1083` onward; `sofascore_average_rating_score.py:277`; `kbstats_points_odds_lineup_score.py:213`; both Transfermarkt scoring modules.

Scoring uses several `iterrows()` passes and per-row lookups. Matching, override handling, normalization, and CSV validation have similar implementations across workflows. These are optimization candidates, not demonstrated bottlenecks for a Bundesliga-sized pool.

**Suggested update:** profile a representative offline run first. Precompute normalized keys and candidate indexes, use validated merges where matching is unambiguous, and retain interactive resolution for ambiguous players. Consolidate shared normalization and mapping interfaces before pursuing broad vectorization.

### 13. Lower — Collector lifecycle and retry handling could be shared

**Where:** `notebooks/01_fixtures_and_teams`, `02_odds`, `03_team_data`, `05_predicted_lineups`; `sofascore_kickbase_points.py:665–733`; `chrome_runtime.py`.

Collectors repeat browser startup, fetch helpers, cleanup, and broad exception handling. KBStats makes a single HTTP request with a proper timeout and status check but no retry. Derived match payloads are cached within a run, so reruns still refetch them.

**Suggested update:** share browser lifecycle and source-specific fetch interfaces, add bounded retries for transient failures, and optionally cache immutable completed-match payloads on disk. Keep manual handling of browser verification and explicit partial-coverage diagnostics. Current Chrome version detection already exists; README's fixed Chrome 150 wording should be reconciled with it.

### 14. Lower — Reflection work can reuse precomputed historical indexes

**Where:** `sofascore_metric_consistency.py:269–340`, `sofascore_score_reflection.py`, reflection notebooks.

`evaluate_next_matches` repeatedly filters earlier metrics, builds weights, and calls `form_at_cutoff`, which reconstructs player histories and ratings at each kickoff. Repeated group work is a plausible scaling cost as the history grows.

**Suggested update:** cache metadata/weights and form cohorts by cutoff, and pre-index histories by team/player/match. Preserve strict pre-kickoff filtering and the existing future-data invariance checks. Extend calibration evaluation to later matchdays before changing model coefficients or validity windows.

### 15. Lower — Reproducible tooling and documentation can be tightened

**Where:** `requirements.txt`, `.github/workflows/ci.yml`, README, `scripts/build_metric_consistency_notebook.py`, `scripts/calibrate_goalkeeper_points.py`.

Requirements pin direct packages but mix notebook/UI, scraping, solver, and test dependencies. Scripts import NumPy, nbformat, and optional notebook execution packages via transitive dependencies. Setup activates `.venv` without showing how to create it or specifying the Python version used by CI. The notebook builder performs writes at module scope.

**Suggested update:** document Python/environment creation, declare directly used tooling dependencies, separate runtime and development dependency groups if helpful, add main guards to writing scripts, and optionally lock transitive dependencies. Review package and action versions through a separate verified update check; this audit does not claim any pinned version is outdated.

## Coverage map

| Area | Files reviewed / next focus |
|---|---|
| Filesystem/browser utilities | `project_paths.py` → findings 3, 11; `chrome_runtime.py` → 13, 15 |
| Identity stores | `player_name_cross_references.py`, `kickbase_player_name_cross_references.py`, reference CSVs → 6, 12 |
| Lineup workflows | `kickbase_screenshot_intake.py`, `generate_kickbase_md5.ps1`, `manual_lineup_helpers.py`, `selected_lineups.py` → 2, 5–7, 11; preserve selected-lineup validation and atomic writes |
| Scoring | `sofascore_rating_odds_lineup_score.py`, `sofascore_average_rating_score.py`, `kbstats_points_odds_lineup_score.py`, `transfermarkt_market_value_score.py`, `transfermarkt_team_market_value_percentile.py` → 7, 12 |
| Derived points/ratings | `sofascore_kickbase_points.py`, `sofascore_kickbase_percentile_ratings.py`, `sofascore_kickbase_points_per_minute_odds_lineup_score.py` → 3, 9, 13 |
| Reflection/calibration | `sofascore_metric_consistency.py`, `sofascore_score_reflection.py`, `goalkeeper_kickbase_calibration.py`, both `scripts/*.py`, `outputs/analysis/*.py` → 4, 9, 14, 15 |
| Fixtures/odds/team collectors | All 10 notebooks in stages 01–03 → 13, 15 |
| Derived-analysis notebooks | All 10 notebooks in stage 04 → 3, 12, 13; several already use thin module wrappers |
| Predicted-lineup notebooks | All 3 notebooks in stage 05 → 13; keep provider-specific parsing behind shared interfaces |
| Score-creation notebooks | All 11 notebooks in stage 06 → 7, 12; preserve existing thin module wrappers |
| Squad notebooks | All 7 notebooks in stage 07 → 2, 7, 8 |
| Visualization/reflection | Stage 08 report, all 5 stage 09 notebooks, diagnostic odds notebook → 3, 9, 14 |
| Tests/CI | All 17 test modules, test snapshots, workflow → 1, 8, 9 |
| Data/outputs/archive | All included JSON/CSV parsed; media and HTML inventoried; archived notebooks parsed → 3, 9–11; no broad history deletion recommended |
| Documentation/configuration | README, `OPTIMIZER_IDEAS.md`, requirements, ignore file → 10, 15; optimizer ideas remain a backlog, not validated requirements |

## Suggested order

1. Fix CI discovery and add behavioral optimizer checks.
2. Consolidate optimizer preprocessing and solver logic.
3. Make retention preserve lineage and historical analysis select explicit inputs.
4. Harden upload/reference persistence and score-method selection.
5. Measure performance, then address storage, repeated lookups, collector reuse, and tooling.

No suggested update above has been implemented.
