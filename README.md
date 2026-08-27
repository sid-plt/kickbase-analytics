# Kickbase Bundesliga data project

> **Work in progress.** This repository preserves the project's source, curated
> reference data, notebooks, archived material, and generated output snapshots.
> Commit refreshed output files alongside the change that produced them so the
> data history remains reproducible.

This project supports a repeatable Bundesliga-to-Kickbase decision workflow:
collect fixtures, odds, team, squad, player, and predicted-lineup data; derive
comparable signals and expected-points scores; then build and save constrained
Kickbase squads. Its live sources include SofaScore, FotMob, Transfermarkt,
KBStats, RotoWire, LigaInsider, Kicker, and manually transcribed Kickbase
lineups.

## Project layout

- `notebooks/01_fixtures_and_teams`: match-ID collectors and the shared
  Bundesliga team-reference builder.
- `notebooks/02_odds`: SofaScore and FotMob matchday odds collectors.
- `notebooks/03_team_data`: recent form, team statistics, Transfermarkt squads,
  and KBStats player collectors.
- `notebooks/04_derived_analysis`: combined Bundesliga snapshots,
  high-rated-player analysis, KBStats average-points percentile filtering, and
  KBStats last-five-match-slot analysis.
- `notebooks/05_predicted_lineups`: live predicted and confirmed lineup
  collectors from RotoWire, LigaInsider, and Kicker, plus compatible
  source-specific outputs.
- `notebooks/06_score_creation`: score builders that combine source signals
  into expected-points files for the optimizers.
- `notebooks/07_squad_optimisation`: optimizer notebooks for Bundesliga Arena,
  KickbaseKIS Arena, All Limits Arena, and Kickbase.insider Arena, plus
  `manually_create_lineup.ipynb` for manual entry.
- `notebooks/tests`: diagnostic notebooks that are not production pipeline steps.
- `data/reference/kickbase`: curated Kickbase scoring and event-frequency rules.
- `outputs/sofascore`: SofaScore match IDs, odds, team reference, form, team
  statistics, and high-rated-player results.
- `outputs/fotmob`: FotMob match IDs and odds.
- `outputs/transfermarkt`: squad exports and diagnostic HTML.
- `outputs/rotowire`: timestamped Bundesliga predicted-lineup snapshots.
- `outputs/ligainsider`: timestamped Bundesliga predicted-lineup snapshots,
  including formation slots and candidate alternatives where supplied.
- `outputs/kicker`: timestamped Bundesliga predicted-lineup snapshots. Each
  record preserves Kicker’s raw lineup text, formation, coach, bench,
  unavailable players, and explanation alongside the common home/away schema.
- `outputs/kickbase`: timestamped predicted-lineup snapshots transcribed from
  user-submitted Kickbase screenshots; player names remain source display names
  and are not resolved to canonical identities.
- `outputs/kbstats`: KBStats player snapshots.
- `outputs/derived`: multi-source normalized outputs.
- `outputs/optimized_squad`: timestamped optimizer exports.
- `outputs/selected_lineups`: canonical per-arena selected-lineup JSON snapshots.
  A newer confirmed selection replaces only that arena's file.
- `archive`: superseded notebooks, historical data, and any unique recovered
  Jupyter checkpoints.
- `project_paths.py`: the authoritative filesystem interface used by notebooks.
- `selected_lineups.py`: shared selected-lineup persistence and replacement prompts.
- `manual_lineup_helpers.py`: shared non-solver player-pool, rule, and validation
  logic used by the manual lineup notebook.

Generated JSON, CSV, and debug HTML must be written through `project_paths.py`;
do not write generated files beside a notebook or into the project root.

## Timestamped output retention

Timestamped output exporters invoke the shared cleanup in `project_paths.py`. The
cleanup uses the final timestamp in a filename as the output creation time and
retains the 10 newest files in each applicable family. Files without a supported
creation timestamp in their filename are never removed.

Most families are distinguished by output directory, filename pattern with
timestamps removed, and file extension. Meaningful labels such as matchday,
percentile, and datatype remain separate. Two high-volume CSV directories use a
single limit across their methods: `outputs/expected_points` retains its 10 newest
expected-points CSVs, and `outputs/optimized_squad` retains its 10 newest optimizer
CSVs. Run timestamped-output notebooks through their final retention cell to apply
the same cleanup after notebook exports.

## Setup

From PowerShell in the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
jupyter lab
```

Run the automated checks with:

```powershell
python -m pytest
```

The existing `.venv` stays at the root because moving a virtual environment can
invalidate absolute paths stored inside it. The browser-backed scraping notebooks
expect a compatible Chrome installation; their current configuration targets
Chrome 150. If Kicker presents a browser-verification page, complete it manually
in the Chrome window when prompted; the notebook does not attempt to bypass it.

## Version-control conventions

All portable project assets are versioned, including `data/`, `archive/`, and
`outputs/`. The local `.venv`, Python caches, and automatic Jupyter checkpoints
are intentionally excluded because they are machine-specific or reproducible.

Do not commit credentials, API tokens, browser profiles, cookies, screenshots,
or other sensitive local material. Keep each code change and its related output
refresh in a small, descriptive commit. A selected-lineup file represents the
current canonical choice for one arena; replacing it is intentional rather than
creating a timestamped history.

## Recommended pipeline

1. Run `notebooks/01_fixtures_and_teams/01_sofascore_match_ids.ipynb` and/or
   `02_fotmob_match_ids.ipynb` for the desired matchday.
2. Run `03_build_bundesliga_team_reference.ipynb` after selecting its `MATCHDAY`.
3. Run the appropriate notebooks in `notebooks/02_odds`.
4. Run any needed collectors in `notebooks/03_team_data`. Recent form and team
   statistics require `outputs/sofascore/reference/bundesliga_teams.json`.
5. Run the derived notebooks. The high-rated-player notebook automatically uses
   the newest valid timestamped file in `outputs/sofascore/team_form`.
6. Run the required collectors in `notebooks/05_predicted_lineups`: RotoWire,
   LigaInsider, Kicker, and/or the source-specific manual Kickbase workflow.
   Their snapshots share the match/home/away/player envelope while retaining
   source-specific details.
7. Create the required expected-points score file in
   `notebooks/06_score_creation`.
8. Run an optimizer in `notebooks/07_squad_optimisation`, or run
   `manually_create_lineup.ipynb` to enter a formation, players, and captain
   interactively. A confirmed selection is stored in `outputs/selected_lineups`.

The Transfermarkt, KBStats, and FotMob collectors can run independently of the
SofaScore team-reference pipeline when their own inputs are available.

## Inputs and outputs

| Notebook | Reads | Writes |
|---|---|---|
| SofaScore match IDs | Live SofaScore API | `outputs/sofascore/match_ids` |
| FotMob match IDs | Live FotMob pages/API | `outputs/fotmob/match_ids` |
| Team-reference builder | SofaScore match IDs | `outputs/sofascore/reference` |
| SofaScore odds | SofaScore match IDs | `outputs/sofascore/odds` |
| FotMob odds | FotMob match IDs | `outputs/fotmob/odds` |
| Recent form | Team reference | `outputs/sofascore/team_form` |
| Team statistics | Team reference | `outputs/sofascore/team_stats` |
| Transfermarkt squads | Live Transfermarkt pages | `outputs/transfermarkt/squads` |
| RotoWire predicted lineups | Live RotoWire Bundesliga lineups page | `outputs/rotowire/predicted_lineups` |
| LigaInsider predicted lineups | Live LigaInsider team pages | `outputs/ligainsider/predicted_lineups` |
| Kicker predicted lineups | Live Kicker matchday and fixture pages | `outputs/kicker/predicted_lineups` |
| Kickbase screenshot lineups | User-submitted screenshots and fixture reference | `outputs/kickbase/predicted_lineups` |
| KBStats players | Live KBStats API | `outputs/kbstats/players` |
| Bundesliga snapshot | Team reference and live source data | `outputs/derived/bundesliga_snapshots` |
| High-rated players | Latest team-form snapshot | `outputs/sofascore/high_rated_players` |
| KBStats high-average players | Latest KBStats player snapshot | `outputs/derived/kbstats_high_average_players` |
| KBStats last-five high-average players | Latest KBStats player snapshot | `outputs/derived/kbstats_last_5_high_average_players` |
| Squad optimizers | Latest expected-points CSV and matchday matches | Timestamped optimizer CSV and optional selected-lineup JSON |
| Manual lineup | Latest expected-points CSV, matchday matches, arena, formation, and player choices | Optional canonical JSON in `outputs/selected_lineups` |

Missing required inputs raise errors that include the exact expected path. Start
Jupyter from the project root for the simplest path discovery; VS Code notebook
execution is also supported.
