# Goalkeeper points audit and residual validation

Audited user-supplied lineup and shotmap JSON for match 16434037 (Dortmund–Paderborn). Noll has five saves (four inside, one outside), three punches and two accurateKeeperSweeper actions. Existing save/punch awards reconcile. Mapping the two successful sweeper actions adds 20 points, changing his event-derived score from 75 to 95 against KBStats 158.

The supplied data has no save-technique, challenged/unchallenged collection or accurate-throw labels. Shot location, xG and xGOT do not prove these classifications. No synthetic action counts are added. Future scoring exports retain raw goalkeeper statistics for auditing.

The official [Kickbase points table](https://kickbase.com/en-us/points-table) lists technique and location awards but does not explicitly resolve whether they stack. Only the explicitly described big-chance bonus remains additive. No inferred technique awards are stacked onto saves.

Fit MD1 (17 rows), select features/regularization on MD2 (17 rows), refit MD1+MD2; test MD3 (17 rows). MD3 was previously inspected, but excluded from model fitting and selection. This is preliminary validation, not a pristine prospective test.

The regression predicts KBStats minus the existing event-derived total. It uses nonnegative coefficients and no player/team identities. Separate residual metadata and estimated totals preserve the original award ledger.

| MD3 method | Mean absolute error | Mean signed error | Within 10 |
|---|---:|---:|---:|
| Original | 39.82 | -39.82 | 3/17 |
| Training-only flat +44 | 20.41 | +4.18 | 5/17 |
| Activity-based estimate | 15.59 | +2.53 | 9/17 |

Coefficients: `{"minutes_90": 5.976295828065726, "credited_saves": 9.640960809102404}`.

Status: experimental model saved; the notebook retains raw event scores but uses valid calibrated GK totals for averages and percentile inputs, with event-score fallback.

The table validates the correction against the legacy scoring baseline. New keeper-sweeper points consume this allowance: remaining correction = max(0, allowance - sweeper points). For Noll: event score 95 + remaining estimate 34 = 129, versus KBStats 158. His sweeper points are not added twice. Full validation after adding the sweeper mapping requires raw historical payloads for every keeper.

The estimate is limited to Bundesliga matches after the training cutoff, this season, the declared scoring policy and the training feature range (full-match keepers, 0–10 credited saves). Other policy changes require refitting. Missing estimates remain null, not zero. Disable supplemental estimates with include_goalkeeper_estimates=False in run_notebook_workflow.

## MD3 keepers

| Player | Original | Correction | Estimated | KBStats | New difference |
|---|---:|---:|---:|---:|---:|
| Nahuel Noll | 75 | +54 | 129 | 158 | -29 |
| Fabian Bredlow | 58 | +64 | 122 | 128 | -6 |
| Oliver Baumann | 83 | +45 | 128 | 149 | -21 |
| Nicolas Kristof | 34 | +35 | 69 | 100 | -31 |
| Karl Hein | 173 | +54 | 227 | 234 | -7 |
| Loris Karius | 96 | +83 | 179 | 147 | +32 |
| Moritz Nicolas | -14 | +45 | 31 | 34 | -3 |
| Frederik Rönnow | 52 | +73 | 125 | 97 | +28 |
| Maarten Vandevoordt | 167 | +54 | 221 | 207 | +14 |
| Finn Dahmen | 47 | +35 | 82 | 86 | -4 |
| Mark Flekken | 38 | +35 | 73 | 70 | +3 |
| Daniel Heuer Fernandes | -6 | +16 | 10 | 20 | -10 |
| Robin Zentner | 19 | +25 | 44 | 40 | +4 |
| Marvin Schwäbe | 71 | +45 | 116 | 88 | +28 |
| Noah Atubolu | 182 | +45 | 227 | 189 | +38 |
| Gregor Kobel | 95 | +6 | 101 | 98 | +3 |
| Mio Backhaus | 142 | +6 | 148 | 144 | +4 |

## Missing appearances

- MD3: Jonas Urbig — No calculation in the filtered source snapshot
- MD1: Matheo Raab — No calculation in the filtered source snapshot
- MD2: Alexander Schwolow — No calculation in the filtered source snapshot
