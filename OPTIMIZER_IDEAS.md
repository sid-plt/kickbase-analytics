# Fantasy Squad Optimizer — Product Notes

## Aim

Recommend the best legal Kickbase fantasy squad for a target matchday, while
showing *why* each player is selected and how confident the recommendation is.

This is a living question bank and product brief, not an implementation plan.

## What influences a player's fantasy rating?

### Team factors

- Current domestic-league form.
- Overall form across competitions, adjusted for opponent quality.
- League-table position and underlying quality.
- Whether results suggest the team is overperforming or underperforming its
  underlying performance.
- Tactical style: possession, pressing, directness, defensive line, chance
  volume, and set-piece strength.
- Whether the team is playing well beyond results (for example chances created
  and conceded).
- Upcoming fixture run, including home/away, rest days, travel, and opponent
  strength.

### Player factors

- Chance of starting, based on multiple independent sources.
- Expected minutes, including likelihood of an early substitution.
- Importance to the squad and reliability of selection.
- In-game position versus real-life role/position.
- General recent performance, using more than one source.
- Fantasy relevance of that performance under the Kickbase scoring rules.
- Involvement in penalties, free kicks, corners, and other set pieces.

### Match factors

- Win/draw/loss probability from match odds.
- Expected tactical approach of both teams and resulting match-up.
- Match importance: title race, European qualification, relegation battle,
  derby, cup tie, or a low-priority fixture.

### Manager factors

- Manager tenure at the club.
- Job-security risk.
- Historical and current tendency to rotate.

### Market and game-rule factors

- Current in-game value.
- Maximum of three players from one club.
- In-game position versus real-life position.
- Market-value movement over the previous 24 hours and over longer periods.
- Total available budget.
- Transfers available between matchdays.
- Transfer mechanics, including whether selling/buying timing and market
  liquidity matter.

## Selection principle

Selection should balance more than the highest predicted points. It should
consider expected score, likelihood of playing, upside, downside, price,
fixture horizon, club concentration, and the user's current squad/transfer
position. Each recommended player should have a human-readable rationale.

## Feature checklist and current status

Status legend: **Done** means relevant source data or a baseline workflow is
already present in this repository. **Partial** means some ingredients exist,
but they are not yet a complete, explicit feature of the recommendation.
**To do** means it has not yet been incorporated.

### Foundation and selection rules

- [x] **Collect core source data — Done.** The project already collects
  fixtures, odds, team form/statistics, player data, market values, and several
  predicted-lineup sources.
- [x] **Baseline expected-points files and squad optimizers — Done.** Existing
  score builders feed constrained optimizer notebooks and write squad outputs.
- [ ] **One documented scoring schema — To do.** Define every feature, its
  direction, weight, confidence, and source so recommendations are comparable
  and explainable.
- [ ] **Target horizon — To do.** Decide whether the objective is next
  matchday points, a rolling fixture horizon, or points plus market growth.
- [ ] **Multi-matchday squad planning — To do.** Optimise a planned sequence of
  squads across several matchdays, not isolated weekly selections. It should
  weigh fixture swings, expected price changes, transfer limits, likely future
  injuries/rotation, and the value of keeping flexible budget or club slots.
- [ ] **Risk profile — To do.** Let the user choose conservative, balanced, or
  upside-seeking recommendations instead of treating all projected points alike.
- [ ] **Explain each selection — To do.** Show the score drivers, warnings,
  uncertainty, and the reason a player beats the closest alternative.

### Team factors

- [x] **Domestic form — Partial.** Recent team-form data is collected; it still
  needs a defined window, opponent-strength adjustment, and score contribution.
- [x] **Overall form — Partial.** Team statistics provide useful ingredients,
  but cross-competition form and weighting are not formalised.
- [x] **Table position — Partial.** Bundesliga-table snapshots exist; translate
  position into a useful signal without double-counting team strength.
- [ ] **Over/underperformance — To do.** Compare results with underlying output
  (for example expected goals, chances, or ratings) to identify teams likely to
  regress or improve.
- [x] **Tactical style — Partial.** Some team-stat inputs can support this, but
  no explicit possession, pressing, directness, defensive-line, or set-piece
  style profile exists yet.
- [x] **Is the team playing well? — Partial.** Ratings/form are available;
  define a robust performance index that distinguishes results from play.
- [x] **Future fixtures — Partial.** Fixture data is collected; calculate a
  forward-looking fixture-difficulty and rest/travel schedule.

### Player factors

- [x] **Chance of starting from multiple sources — Partial.** Multiple lineup
  providers are collected and a blended starting chance is used in score
  builders; add source quality, agreement, recency, and late-news handling.
- [ ] **Expected minutes — To do.** Move beyond start/not-start by estimating
  starts, substitute appearances, and early-substitution risk.
- [ ] **Squad importance — To do.** Quantify how indispensable a player is
  through selection history, minute share, role, and available replacements.
- [ ] **Real-life role and position — To do.** Model the actual role (for
  example attacking fullback, inverted winger, target striker) and compare it
  with the Kickbase-listed position.
- [x] **General recent player performance — Partial.** Player ratings and
  KBStats point averages exist; agree the windows, quality controls, and blend.
- [ ] **Multi-source player-form consensus — To do.** Combine player form from
  SofaScore, Flashscore, FotMob, and other suitable providers rather than
  trusting one rating system. Normalise differing scales and definitions, track
  recency and source agreement, and retain the source-level values so an
  outlying rating can be explained.
- [ ] **Kickbase scoring fit — To do.** Map on-pitch actions to the actual
  Kickbase scoring rules so a good real-life player is not automatically treated
  as a good fantasy pick.
- [ ] **Raw-points floor versus odds-driven upside — To do.** Split a projected
  fantasy score into (1) a repeatable action-based floor, such as duels, passes,
  tackles, interceptions, saves, and volume of involvement, and (2) an
  event-driven upside component informed by match odds, team scoring/clean-sheet
  expectations, and a player's goal/assist/set-piece role. Show both components
  separately, so users can choose dependable all-action players or higher-variance
  attacking upside according to their strategy.
- [ ] **Set-piece involvement — To do.** Track first/second-choice penalties,
  direct free kicks, corners, aerial targets, and the reliability of this role.
- [ ] **Injury, suspension, and team news — To do.** Add confirmed absences,
  fitness uncertainty, press-conference news, and freshness timestamps.
- [ ] **Fatigue and availability — To do.** Incorporate recent minutes,
  international duty, travel, rest days, fixture congestion, and recovery from
  injury. This should reduce both expected minutes and confidence where
  appropriate.
- [ ] **Role changes — To do.** Detect effects from transfers, formation shifts,
  teammate injuries, new set-piece duties, and manager changes.
- [ ] **New-signing impact — To do.** Measure how an incoming player is likely
  to affect the squad before sufficient new-club data exists. Estimate the new
  signing's probable minutes, role, position, and adaptation risk using their
  prior club/league performance, transfer context, manager fit, and competition
  for places. Also project the knock-on effect on incumbents: displaced starters,
  reduced minutes, changed set-piece duties, altered tactical shape, and changes
  to team attacking or defensive output. Mark these forecasts as low-confidence
  until confirmed lineups and new-club performances validate them.

### Match factors

- [x] **Win/draw/loss probability — Partial.** Match odds are already
  collected and used in baseline score builders; improve calibration and handle
  market changes close to kick-off.
- [ ] **Likely tactical approach — To do.** Predict whether each team will
  dominate possession, press, sit deep, counter, or protect a result, then map
  that to relevant player roles.
- [ ] **Match importance — To do.** Include title, European, relegation, derby,
  cup, and low-priority contexts only where historical evidence shows a useful
  effect.
- [ ] **Opponent-specific match-up — To do.** Model how an opponent's strengths
  and weaknesses affect a player's role: weak set-piece defence for aerial
  threats, vulnerable flanks for wide players, or high possession against a
  defensive midfielder likely to collect actions.
- [ ] **Weather and referee effects — To do.** Assess only if reliable data and
  backtesting show these signals improve forecasts. Relevant candidates include
  wind/rain affecting passing and set pieces, extreme heat affecting intensity,
  and referee tendencies for fouls, cards, and penalties.

### Manager factors

- [ ] **Manager tenure — To do.** Capture how long the coach has been in post;
  it may contextualise tactical stability and selection certainty.
- [ ] **Job-security risk — To do.** Track instability carefully, because a
  likely change can invalidate historical tactical and lineup assumptions.
- [ ] **Rotation tendency — To do.** Measure rotation by manager, team context,
  player position, fixture congestion, and competition rather than a single
  season-wide percentage.

### Market, squad, and transfer factors

- [x] **Current in-game value — Partial.** Market-value data is present and
  used in squad constraints; define value-for-money measures alongside raw
  projected points.
- [x] **Three-players-per-club rule — Done.** Existing optimizer variants
  implement per-team limits; confirm the exact rule for the arena being played.
- [x] **In-game position — Partial.** Player positions are available to the
  optimizer; enrich them with real-life role data as noted above.
- [ ] **24-hour market-value movement — To do.** Save comparable snapshots,
  calculate the movement, and distinguish genuine demand from noise.
- [x] **Total budget — Done.** Existing optimizer workflows use budget caps;
  make the entered budget a standard user setting.
- [ ] **Transfer limit — To do.** Encode the number of permitted transfers for
  the selected matchday and preserve the user's current squad.
- [ ] **Transfer mechanics — To do.** Model buying/selling timing, liquidity,
  price-change risk, and the opportunity cost of using a transfer now.
- [ ] **Rolling transfer plan — To do.** For a multi-matchday horizon, recommend
  not only this week's transfers but a route for the next few matchdays, with
  contingency options for late injuries, lineup surprises, and changing prices.
- [ ] **Ownership and league strategy — To do.** Use popularity and the user's
  league position to distinguish protecting a lead from chasing upside.

### Multiple fantasy games and league rules

- [ ] **Game-agnostic player model — To do.** Keep real-world inputs (minutes,
  role, form, fixtures, match-up, and availability) independent from any one
  fantasy platform, so the same underlying forecast can serve multiple games.
- [ ] **Per-game rules engine — To do.** Support Kickbase, Fantasy Premier
  League (FPL), Bundesliga Fantasy, SofaScore Fantasy, and local/custom fantasy
  rules. Each profile should specify scoring events, positions, squad size,
  formations, budget, club caps, transfers, captaincy/multipliers, bench rules,
  and any game-specific restrictions.
- [ ] **League and competition profiles — To do.** Allow separate leagues with
  their own schedule, teams, data availability, match rules, currency, and
  player identifiers, rather than assuming the Bundesliga.
- [ ] **Scoring translation — To do.** Translate the same projected on-pitch
  events into the expected score for the selected fantasy game. A player can be
  excellent in one ruleset yet only average in another, so rankings must be
  calculated per rules profile.
- [ ] **Custom/local rules editor — To do.** Let a user define or modify a
  local league's scoring and roster rules without changing the underlying model.
- [ ] **Cross-game data matching — To do.** Maintain reliable player and team
  identity mappings across providers, leagues, and fantasy apps; flag uncertain
  matches for review instead of silently joining the wrong player.

### Uncertainty, upside, and squad construction

- [ ] **Expected-points variance — To do.** Forecast not only a player's mean
  expected points but a range/distribution. This separates steady high-minute
  picks from volatile goal-dependent picks and enables risk-aware squads.
- [ ] **Confidence score — To do.** Explain uncertainty from missing data,
  conflicting lineup sources, injury doubt, unstable roles, and small samples.
- [ ] **Player correlation — To do.** Account for shared outcomes: attackers
  from the same team can rise together, while multiple defenders from a fragile
  team create concentrated downside.
- [ ] **Alternative squad styles — To do.** Present at least best expected
  score, safest, highest-upside, and best-value legal squads.
- [ ] **Captaincy and multiplier rules — To do.** Add the arena's captain,
  vice-captain, multiplier, and any eligibility rules. Optimise the player and
  multiplier choice jointly; factor in expected points, variance, start chance,
  and a replacement/vice-captain fallback.

### Evaluation and improvement

- [ ] **Backtesting — To do.** Compare historical forecasts, recommendations,
  and alternate squads with actual Kickbase returns across matchdays.
- [ ] **Calibration — To do.** Check whether predicted start probabilities,
  expected minutes, expected points, and variance match reality, then adjust.
- [ ] **Data-source review — To do.** Record coverage, latency, reliability,
  legal/terms considerations, and past accuracy for each source.
- [ ] **Change log — To do.** Track feature and weighting changes so later
  results can be traced to the exact model version.

## Open questions

- Which arena/game mode and exact squad/formation rules apply?
- Is the objective one matchday, the next several matchdays, or season-long
  value growth as well as points?
- Should the optimiser be conservative, balanced, or high-risk/high-upside?
- Which data sources are reliable enough to treat as primary inputs?
- How should uncertain or unavailable data affect confidence?
