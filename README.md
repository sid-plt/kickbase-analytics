# Kickbase Bundesliga data project

> **Work in progress.** This repository preserves the project's source, curated
> reference data, notebooks, archived material, and generated output snapshots.
> Commit refreshed output files alongside the change that produced them so the
> data history remains reproducible.

This project collects and derives Bundesliga fixture, odds, team, squad, and
player data from SofaScore, FotMob, Transfermarkt, KBStats, and Analyst.

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
  collectors.
- `notebooks/tests`: diagnostic notebooks that are not production pipeline steps.
- `data/reference/kickbase`: curated Kickbase scoring and event-frequency rules.
- `outputs/sofascore`: SofaScore match IDs, odds, team reference, form, team
  statistics, and high-rated-player results.
- `outputs/fotmob`: FotMob match IDs and odds.
- `outputs/transfermarkt`: squad exports and diagnostic HTML.
- `outputs/rotowire`: timestamped Bundesliga predicted-lineup snapshots.
- `outputs/kickbase`: timestamped predicted-lineup snapshots transcribed from
  user-submitted Kickbase screenshots; player names remain source display names
  and are not resolved to canonical identities.
- `outputs/kbstats`: KBStats player snapshots.
- `outputs/derived`: multi-source normalized outputs.
- `archive`: superseded notebooks, historical data, and any unique recovered
  Jupyter checkpoints.
- `project_paths.py`: the authoritative filesystem interface used by notebooks.

Generated JSON, CSV, and debug HTML must be written through `project_paths.py`;
do not write generated files beside a notebook or into the project root.

## Setup

From PowerShell in the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
jupyter lab
```

The existing `.venv` stays at the root because moving a virtual environment can
invalidate absolute paths stored inside it. The scraping notebooks expect a
compatible Chrome installation; their current configuration targets Chrome 150.

## Version-control conventions

All portable project assets are versioned, including `data/`, `archive/`, and
`outputs/`. The local `.venv`, Python caches, and automatic Jupyter checkpoints
are intentionally excluded because they are machine-specific or reproducible.

Do not commit credentials, API tokens, browser profiles, cookies, screenshots,
or other sensitive local material. Keep each code change and its related output
refresh in a small, descriptive commit.

## Recommended pipeline

1. Run `notebooks/01_fixtures_and_teams/01_sofascore_match_ids.ipynb` and/or
   `02_fotmob_match_ids.ipynb` for the desired matchday.
2. Run `03_build_bundesliga_team_reference.ipynb` after selecting its `MATCHDAY`.
3. Run the appropriate notebooks in `notebooks/02_odds`.
4. Run any needed collectors in `notebooks/03_team_data`. Recent form and team
   statistics require `outputs/sofascore/reference/bundesliga_teams.json`.
5. Run the derived notebooks. The high-rated-player notebook automatically uses
   the newest valid timestamped file in `outputs/sofascore/team_form`.
6. Run `notebooks/05_predicted_lineups/01_rotowire_lineups.ipynb` whenever a
   fresh RotoWire Bundesliga lineup snapshot is needed.

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
| KBStats players | Live KBStats API | `outputs/kbstats/players` |
| Bundesliga snapshot | Team reference and live source data | `outputs/derived/bundesliga_snapshots` |
| High-rated players | Latest team-form snapshot | `outputs/sofascore/high_rated_players` |
| KBStats high-average players | Latest KBStats player snapshot | `outputs/derived/kbstats_high_average_players` |
| KBStats last-five high-average players | Latest KBStats player snapshot | `outputs/derived/kbstats_last_5_high_average_players` |

Missing required inputs raise errors that include the exact expected path. Start
Jupyter from the project root for the simplest path discovery; VS Code notebook
execution is also supported.
