"""Local, auditable metric reflection; this module never changes prediction scores.

Forecasts use only records strictly before kickoff. The exported player population
is already eligibility-filtered, so these checks are conditional on that population.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math

import numpy as np
import pandas as pd

from goalkeeper_kickbase_calibration import points_for_averages
from sofascore_kickbase_percentile_ratings import derive_ratings, latest_json, rounded
from sofascore_rating_odds_lineup_score import OVERALL_RECENCY_WEIGHTS
from sofascore_kickbase_points import eligibility_metadata, qualifies_for_average, position_code
from project_paths import SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR, SOFASCORE_TEAM_FORM_DIR

POSITIONS = ('GK', 'DEF', 'MID', 'FWD')
LABELS = {1: 'Generally consistent', 2: 'Consistent for in-form players',
          3: 'Volatile — exclude from this prediction approach'}
# Explicit award-producing rules in score_from_match, including synthetic spatial
# families. Catalog-only zone alternatives are not independently scored metrics.
SUPPORTED = set('''penalty_won big_chance_created goal_line_clearance ball_intercepted
punched_ball contest_won tackle_won cross aerial_won accurate_long_ball aerial_lost
foul challenge_lost offside big_chance_missed mistake_before_shot mistake_before_goal
penalty_conceded cross_intercepted shot_assist overrun possession_lost
clearance_zone_estimate interception_zone_estimate pass_zone_estimate foul_won_zone_estimate
shot_blocked starting_eleven subbed_on minutes_bonus own_goal goal assist penalty_scored
penalty_missed penalty_saved shootout_penalty_scored shootout_penalty_missed
shootout_penalty_saved yellow_card second_yellow red_card team_goal goal_conceded
game_won game_lost clean_sheet keeper_sweeper box_shot_saved distance_shot_saved
big_chance_saved shot_on_goal target_shot_blocked narrow_miss far_shot_miss
post_label_crossbar long_range_bonus'''.split())
PROXY_FAMILIES = {
    'clearance_zone_estimate': ('Clearance zone estimate', 'cleared_in_box', 'cleared_outside_box'),
    'interception_zone_estimate': ('Interception zone estimate', 'interception_in_box', 'interception_outside_box'),
    'pass_zone_estimate': ('Pass zone estimate', 'pass_final_third', 'forward_zone_pass'),
    'foul_won_zone_estimate': ('Foul won zone estimate', 'fouled_last_third', 'fouled_opponent_half'),
}


@dataclass(frozen=True)
class Settings:
    bundesliga_matchday: int | None = None
    form_top_percent: float = 20
    minimum_minutes: float = 45
    minimum_history: int = 2
    minimum_players: int = 20
    minimum_evaluations: int = 30
    minimum_nonzero: float = .20
    minimum_recurrence: float = .60
    maximum_wape: float = .75

    def __post_init__(self):
        if self.bundesliga_matchday is not None:
            validate_matchday(self.bundesliga_matchday)
        if not 0 < self.form_top_percent <= 100:
            raise ValueError('form_top_percent must be in (0, 100].')
        if not math.isfinite(self.minimum_minutes) or self.minimum_minutes < 10:
            raise ValueError('minimum_minutes must be finite and at least 10.')
        for key in ('minimum_history', 'minimum_players', 'minimum_evaluations'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{key} must be a positive integer.')
        for key in ('minimum_nonzero', 'minimum_recurrence', 'maximum_wape'):
            if not 0 <= getattr(self, key) <= 1:
                raise ValueError(f'{key} must be in [0, 1].')


def validate_matchday(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 34:
        raise ValueError('Bundesliga matchday must be a whole number from 1 to 34.')
    return value


def qualification_matchday(payload, override=None):
    value = override if override is not None else payload.get('eligibility', {}).get('bundesliga_matchday')
    if value is None:
        raise ValueError('Source has no Bundesliga matchday; set Settings.bundesliga_matchday explicitly.')
    return validate_matchday(value)


def qualification_audit(payload, metadata, matchday=None, cutoff=None):
    """Apply the shared matchday eligibility rules to strictly available appearances.

    Use the selected source/override matchday regime at every cutoff: mixed-
    competition slots cannot reliably identify historical Bundesliga round numbers.
    The source population is already filtered and excluded players cannot be recovered.
    Appearance qualification is independent of the 10/45-minute analysis filters.
    """
    matchday = qualification_matchday(payload, matchday)
    policy = eligibility_metadata(matchday)
    available = metadata if cutoff is None else metadata.loc[metadata.kickoff < cutoff]
    ordered = {team_id: group.sort_values(['kickoff', 'match_id']).match_id.tolist()
               for team_id, group in available.groupby('team_id')}
    rows = []
    for team_id, team in payload['teams'].items():
        slots = ordered.get(str(team_id), [])
        for player in team['overall']['players']:
            known = [m for m in player['match_calculations'] if m['match_id'] in slots]
            ids = {m['match_id'] for m in known}
            latest_minutes = next((m.get('minutes_played') for m in known if slots and m['match_id'] == slots[-1]), None)
            if isinstance(latest_minutes, bool) or not isinstance(latest_minutes, (int, float)) or not math.isfinite(latest_minutes):
                latest_minutes = None
            position = position_code(player.get('position'))
            qualified = qualifies_for_average(ids, slots, matchday, latest_minutes, position)
            if position == 'GK' and ids:
                route = 'Goalkeeper: one recorded appearance'
            elif len(ids) >= policy['minimum_appearances']:
                route = f'Minimum {policy["minimum_appearances"]} recorded appearances'
            elif qualified and policy['latest_match_exception']:
                route = 'Latest team match appearance (MD2–3 exception)'
            elif qualified and len(slots) >= 2 and set(slots[-2:]).issubset(ids):
                route = 'Both latest team matches (MD4+ exception)'
            elif qualified:
                route = 'At least 45 minutes in latest team match (MD4+ exception)'
            else:
                route = 'Does not meet matchday qualification'
            rows.append(dict(team_id=str(team_id), team=team['team'], player_id=player['player_id'],
                player_name=player['player_name'], position=position, bundesliga_matchday=matchday,
                minimum_appearances=policy['minimum_appearances'], recorded_appearances=len(ids),
                latest_match_minutes=latest_minutes, qualified=qualified, qualification_route=route))
    return pd.DataFrame(rows)


def load_inputs(source_path=None):
    path = Path(source_path) if source_path else latest_json(
        SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR,
        'overall_player_kickbase_point_averages_*.json')
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    name = payload['source_file']
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError('source_file must be a plain team-form filename.')
    form_path = SOFASCORE_TEAM_FORM_DIR / name
    snapshot = json.loads(form_path.read_text(encoding='utf-8-sig'))
    if not all(str(k).isdigit() for k in snapshot):
        if len(snapshot) != 1:
            raise ValueError('Expected one timestamp-wrapped team-form snapshot.')
        snapshot = next(iter(snapshot.values()))
    catalog_path = Path(__file__).parent / 'data/reference/kickbase/kickbase_metrics.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8-sig'))
    return payload, snapshot, catalog, dict(points_file=str(path.resolve()),
        team_form_file=str(form_path.resolve()), generated_at=payload['generated_at'],
        failed_matches=payload.get('failed_matches', []), eligibility=payload.get('eligibility', {}),
        scoring_policy=payload.get('scoring_policy', {}))


def match_metadata(snapshot):
    rows = []
    for team_id, team in snapshot.items():
        matches = team['overall_matches']
        if not 1 <= len(matches) <= 5:
            raise ValueError('Expected one to five team matches.')
        ordered = sorted(matches, key=lambda m: (pd.to_datetime(m['date'], utc=True), m['match_id']))
        for slot, match in enumerate(ordered, 1):
            is_home = str(match.get('home_team_id')) == str(team_id)
            rows.append(dict(team_id=str(team_id), team=team['team'], match_id=match['match_id'],
                kickoff=pd.to_datetime(match['date'], utc=True), slot=slot,
                opponent=match.get('away_team' if is_home else 'home_team'),
                competition=match.get('competition', 'Unknown')))
    frame = pd.DataFrame(rows)
    if frame.duplicated(['team_id', 'match_id']).any() or frame.kickoff.isna().any():
        raise ValueError('Duplicate match IDs or invalid kickoff dates in team history.')
    return frame


def metric_registry(catalog):
    registry = {}
    for item in catalog['metrics']:
        positions = item.get('positions', list(POSITIONS))
        scoring = item['scoring']
        if scoring['type'] == 'by_position':
            positions = list(scoring['points'])
        elif scoring['type'] == 'time_and_position':
            positions = list(scoring['points_per_interval'])
        registry[item['id']] = dict(metric_id=item['id'], metric_name=item['name'],
            positions=positions, supported=item['id'] in SUPPORTED,
            implementation='Independent award' if item['id'] in SUPPORTED else 'Not independently emitted by the scorer')
    for identifier, (name, *parts) in PROXY_FAMILIES.items():
        registry[identifier] = dict(metric_id=identifier, metric_name=name,
            positions=list(POSITIONS), supported=True,
            implementation='Proxy family combining ' + ', '.join(parts))
    missing = SUPPORTED - registry.keys()
    if missing:
        raise ValueError(f'Supported metrics missing from registry: {sorted(missing)}')
    return registry


def flatten_appearances(payload, metadata, registry):
    rows, awards, seen = [], [], set()
    counts = dict(source=0, invalid_points_or_minutes=0, below_10_minutes=0)
    failed = {(str(f['team_id']), f['match_id']) for f in payload.get('failed_matches', [])}
    lookup = metadata.set_index(['team_id', 'match_id'])
    for team_id, team in payload['teams'].items():
        for player in team['overall']['players']:
            position = {'G': 'GK', 'D': 'DEF', 'M': 'MID', 'F': 'FWD'}.get(player.get('position'), player.get('position'))
            if position not in POSITIONS:
                raise ValueError(f'Unknown position for player {player["player_id"]}.')
            for match in player['match_calculations']:
                counts['source'] += 1
                key = (str(team_id), player['player_id'], match['match_id'])
                if key in seen:
                    raise ValueError(f'Duplicate appearance: {key}')
                seen.add(key)
                if (str(team_id), match['match_id']) in failed:
                    raise ValueError('An appearance is also listed as a failed match.')
                meta = lookup.loc[(str(team_id), match['match_id'])]
                minutes, raw, rating_points = match.get('minutes_played'), match.get('calculated_kickbase_points'), points_for_averages(match, position)
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (minutes, raw, rating_points)) or minutes < 0:
                    counts['invalid_points_or_minutes'] += 1
                    continue
                award_total = 0
                for award in match['awards']:
                    metric, points = award['metric_id'], award['points']
                    if metric not in registry or not registry[metric]['supported']:
                        raise ValueError(f'Unknown or unsupported emitted metric: {metric}')
                    if position not in registry[metric]['positions']:
                        raise ValueError(f'{metric} emitted for an inapplicable position: {position}')
                    if isinstance(points, bool) or not isinstance(points, (int, float)) or not math.isfinite(points):
                        raise ValueError('Non-finite award points.')
                    award_total += points
                    awards.append(dict(team_id=str(team_id), player_id=player['player_id'],
                        match_id=match['match_id'], metric_id=metric, metric_points=points,
                        position=position, confidence=award.get('confidence', 'unknown'), source=award.get('source', 'unknown')))
                if not math.isclose(award_total, raw, abs_tol=1e-8):
                    raise ValueError(f'Award reconciliation failed: {key}: {award_total} != {raw}')
                rows.append(dict(team_id=str(team_id), team=team['team'], player_id=player['player_id'],
                    player_name=player['player_name'], position=position, match_id=match['match_id'],
                    minutes_played=minutes, raw_points=raw, rating_points=rating_points,
                    award_total=award_total, calibration_adjustment=rating_points-raw,
                    kickoff=meta.kickoff, slot=meta.slot, opponent=meta.opponent, competition=meta.competition))
                if minutes < 10:
                    counts['below_10_minutes'] += 1
    appearances = pd.DataFrame(rows)
    if appearances.empty:
        raise ValueError('No valid recorded appearances.')
    ledger = pd.DataFrame(awards, columns=['team_id', 'player_id', 'match_id', 'metric_id', 'metric_points', 'position', 'confidence', 'source'])
    supported = [k for k, v in registry.items() if v['supported']]
    expanded = appearances.merge(pd.DataFrame({'metric_id': supported}), how='cross')
    expanded = expanded.loc[[p in registry[m]['positions'] for p, m in zip(expanded.position, expanded.metric_id)]].copy()
    keys = ['team_id', 'player_id', 'match_id', 'metric_id']
    sums = ledger.groupby(keys, as_index=False).metric_points.sum()
    expanded = expanded.merge(sums, on=keys, how='left', validate='one_to_one')
    expanded['metric_points'] = expanded.metric_points.fillna(0)
    expanded['points_per_90'] = np.where(expanded.minutes_played > 0,
        90 * expanded.metric_points / expanded.minutes_played.replace(0, np.nan), np.nan)
    return appearances, expanded, ledger, counts


def select_form(players, top_percent):
    """Top ceil(percent * cohort) players per position; include boundary ties."""
    if not 0 < top_percent <= 100:
        raise ValueError('top_percent must be in (0, 100].')
    result = players.copy()
    result['in_form'] = False
    result['form_cutoff'] = np.nan
    for _, group in result.groupby('position'):
        n = max(1, math.ceil(len(group) * top_percent / 100))
        cutoff = group.average_rating.nlargest(n).iloc[-1]
        result.loc[group.index, 'form_cutoff'] = cutoff
        result.loc[group.index, 'in_form'] = group.average_rating >= cutoff
    return result


def form_at_cutoff(payload, metadata, cutoff=None, top_percent=20, minimum_history=1, matchday=None):
    """Rerank only the pre-cutoff population using the project's rating function."""
    available = metadata if cutoff is None else metadata.loc[metadata.kickoff < cutoff]
    known = set(zip(available.team_id, available.match_id))
    qualification = qualification_audit(payload, metadata, matchday, cutoff)
    eligible = set(zip(qualification.loc[qualification.qualified, 'team_id'],
                       qualification.loc[qualification.qualified, 'player_id']))
    teams = {}
    for team_id, team in payload['teams'].items():
        players = []
        for player in team['overall']['players']:
            if (str(team_id), player['player_id']) not in eligible:
                continue
            matches = [m for m in player['match_calculations'] if (str(team_id), m['match_id']) in known]
            if matches:
                players.append({**player, 'position': position_code(player.get('position')),
                                'match_calculations': matches})
        teams[str(team_id)] = dict(team=team['team'], overall=dict(players=players))
    ratings, _, _ = derive_ratings({'teams': teams})
    weights = {}
    for team_id, matches in available.groupby('team_id'):
        for match, weight in zip(matches.sort_values(['kickoff', 'match_id'], ascending=False).itertuples(), OVERALL_RECENCY_WEIGHTS):
            weights[(team_id, match.match_id)] = weight
    rows = []
    for (team_id, player_id), group in ratings.groupby(['team_id', 'player_id']):
        if len(group) < minimum_history:
            continue
        w = np.array([weights[(team_id, m)] for m in group.match_id])
        first = group.iloc[0]
        rows.append(dict(team_id=team_id, team=first.team, player_id=player_id,
            player_name=first.player_name, position=first.position, rating_count=len(group),
            average_rating=rounded(float(np.average(group.rating, weights=w)))))
    players = pd.DataFrame(rows, columns=['team_id', 'team', 'player_id', 'player_name', 'position', 'rating_count', 'average_rating'])
    return select_form(players, top_percent)


def evaluate_next_matches(payload, metadata, metrics, settings):
    valid = metrics.loc[metrics.minutes_played >= settings.minimum_minutes]
    targets = valid.loc[valid.slot.isin([4, 5])]
    frames = []
    keys = ['team_id', 'player_id', 'metric_id']
    for kickoff, target in targets.groupby('kickoff'):
        earlier = valid.loc[valid.kickoff < kickoff].copy()
        if earlier.empty:
            continue
        available = metadata.loc[metadata.kickoff < kickoff]
        weights = {}
        for team_id, group in available.groupby('team_id'):
            for match, weight in zip(group.sort_values(['kickoff', 'match_id'], ascending=False).itertuples(), OVERALL_RECENCY_WEIGHTS):
                weights[(team_id, match.match_id)] = weight
        earlier['weight'] = [weights[(t, m)] for t, m in zip(earlier.team_id, earlier.match_id)]
        earlier['weighted_points'] = earlier.points_per_90 * earlier.weight
        earlier['active'] = earlier.metric_points.ne(0)
        history = earlier.groupby(keys).agg(history_count=('match_id', 'size'),
            weighted_points=('weighted_points', 'sum'), weight=('weight', 'sum'),
            previously_active=('active', 'any'), latest_history_kickoff=('kickoff', 'max')).reset_index()
        history = history.loc[history.history_count >= settings.minimum_history].copy()
        history['predicted_per_90'] = history.weighted_points / history.weight
        evaluated = target.merge(history, on=keys, how='inner', validate='many_to_one')
        cohort = form_at_cutoff(payload, metadata, kickoff, settings.form_top_percent,
                                settings.minimum_history, settings.bundesliga_matchday)
        evaluated = evaluated.merge(cohort[['team_id', 'player_id', 'in_form', 'average_rating']],
            on=['team_id', 'player_id'], how='inner', validate='many_to_one')
        evaluated['matchday_qualified'] = True
        evaluated['in_form'] = evaluated.in_form.fillna(False).astype(bool)
        evaluated['absolute_error'] = (evaluated.predicted_per_90 - evaluated.points_per_90).abs()
        frames.append(evaluated)
    columns = list(metrics.columns) + ['history_count', 'previously_active', 'latest_history_kickoff',
        'predicted_per_90', 'in_form', 'average_rating', 'absolute_error', 'matchday_qualified']
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def evidence(group, settings):
    players = len(group[['team_id', 'player_id']].drop_duplicates())
    count = len(group)
    active = group.loc[group.previously_active.astype(bool)]
    denominator = group.points_per_90.abs().sum()
    wape = group.absolute_error.sum() / denominator if denominator else np.nan
    frequency = group.metric_points.ne(0).mean() if count else np.nan
    recurrence = active.metric_points.ne(0).mean() if len(active) else np.nan
    enough = players >= settings.minimum_players and count >= settings.minimum_evaluations
    passed = bool(enough and frequency >= settings.minimum_nonzero
        and recurrence >= settings.minimum_recurrence and wape <= settings.maximum_wape)
    reasons = []
    if not enough:
        reasons.append(f'Insufficient evidence: {players} players / {count} evaluations')
    else:
        if not denominator:
            reasons.append('No observed nonzero target contribution')
        if frequency < settings.minimum_nonzero:
            reasons.append('Nonzero frequency below threshold')
        if not len(active):
            reasons.append('No previously active cases to measure recurrence')
        elif recurrence < settings.minimum_recurrence:
            reasons.append('Recurrence below threshold')
        if denominator and wape > settings.maximum_wape:
            reasons.append('Prediction error above threshold')
    return dict(players=players, evaluations=count, nonzero_frequency=frequency,
        recurrence_cases=len(active), recurrence=recurrence, wape=wape,
        sufficient=enough, passed=passed, reason='; '.join(reasons) or 'All consistency thresholds passed')


def classify(all_evidence, form_evidence):
    if all_evidence['passed']:
        return 1, 'sufficient', 'All-player next-match evidence passes.'
    if form_evidence['passed']:
        return 2, 'sufficient', 'Only the pre-match in-form cohort passes.'
    if not all_evidence['sufficient'] or not form_evidence['sufficient']:
        return None, 'insufficient evidence', all_evidence['reason'] + '; in form: ' + form_evidence['reason']
    return 3, 'sufficient', all_evidence['reason'] + '; in form: ' + form_evidence['reason']


def summarize(metrics, ledger, evaluations, registry, settings, overrides=None):
    overrides = overrides or {}
    valid_keys = {(m, p) for m, item in registry.items() for p in item['positions']}
    for key, value in overrides.items():
        if key not in valid_keys or value not in LABELS:
            raise ValueError(f'Invalid override: {key}: {value}')
    rows = []
    valid = metrics.loc[metrics.minutes_played >= settings.minimum_minutes]
    for metric, item in registry.items():
        for position in item['positions']:
            observations = valid.loc[(valid.metric_id == metric) & (valid.position == position)]
            tested = evaluations.loc[(evaluations.metric_id == metric) & (evaluations.position == position)]
            full = evidence(tested, settings)
            form = evidence(tested.loc[tested.in_form.astype(bool)], settings)
            if item['supported']:
                category, status, reason = classify(full, form)
            else:
                category, status, reason = None, 'unsupported', item['implementation']
            actual_awards = ledger.loc[(ledger.metric_id == metric) & (ledger.position == position)]
            # Zero-only players must not make within-player variation look stable.
            player_groups = observations.groupby(['team_id', 'player_id']).points_per_90
            variation = []
            for _, values in player_groups:
                if len(values) >= 3 and values.ne(0).sum() >= 2:
                    variation.append(values.std(ddof=0) / values.abs().mean())
            row = dict(metric_id=metric, metric_name=item['metric_name'], position=position,
                supported=item['supported'], automatic_category=category, evidence_status=status,
                category=overrides.get((metric, position), category),
                overridden=(metric, position) in overrides, reason=reason,
                appearances=len(observations), players=len(observations[['team_id', 'player_id']].drop_duplicates()),
                nonzero_frequency=observations.metric_points.ne(0).mean(),
                mean_points=observations.metric_points.mean(), median_points=observations.metric_points.median(),
                std_points=observations.metric_points.std(ddof=0),
                mean_per_90=observations.points_per_90.mean(), median_per_90=observations.points_per_90.median(),
                iqr_per_90=observations.points_per_90.quantile(.75)-observations.points_per_90.quantile(.25),
                median_within_player_cv=np.median(variation) if variation else np.nan,
                within_player_samples=len(variation),
                confidence=', '.join(sorted(actual_awards.confidence.unique())) or 'No observed awards',
                implementation=item['implementation'])
            for prefix, result in (('all', full), ('form', form)):
                row.update({prefix + '_' + k: v for k, v in result.items() if k not in ('reason',)})
            row['classification'] = LABELS.get(row['category'], 'Unclassified')
            rows.append(row)
    by_position = pd.DataFrame(rows)
    overall = []
    for metric, group in by_position.groupby('metric_id', sort=False):
        if not group.supported.all():
            category, status = None, 'unsupported'
        elif (group.category == 1).all():
            category, status = 1, 'sufficient' if not group.overridden.any() else 'manual override'
        elif ((group.category == 1) | (group.category == 2)).all() and (group.form_passed | group.overridden).all():
            category, status = 2, 'sufficient' if not group.overridden.any() else 'manual override'
        elif group.category.isna().any():
            category, status = None, 'insufficient evidence'
        else:
            category, status = 3, 'sufficient' if not group.overridden.any() else 'manual override'
        overall.append(dict(metric_id=metric, metric_name=group.metric_name.iloc[0], category=category,
            classification=LABELS.get(category, 'Unclassified'), evidence_status=status,
            position_details='; '.join(f'{r.position}: {r.classification} ({r.evidence_status})' for r in group.itertuples()),
            reason='All applicable positions must pass for overall category 1; all form cohorts must pass for overall category 2.',
            confidence=', '.join(sorted({c for value in group.confidence if value != 'No observed awards'
                for c in value.split(', ')})) or 'No observed awards'))
    return by_position, pd.DataFrame(overall)


def analyze(payload, snapshot, catalog, settings=None, overrides=None):
    settings = settings or Settings()
    metadata = match_metadata(snapshot)
    registry = metric_registry(catalog)
    appearances, metrics, ledger, counts = flatten_appearances(payload, metadata, registry)
    matchday = qualification_matchday(payload, settings.bundesliga_matchday)
    qualification = qualification_audit(payload, metadata, matchday)
    eligible = set(zip(qualification.loc[qualification.qualified, 'team_id'],
                       qualification.loc[qualification.qualified, 'player_id']))
    original_count = len(appearances)
    def eligible_rows(frame):
        return frame.loc[[(t, p) in eligible for t, p in zip(frame.team_id, frame.player_id)]].copy()
    appearances, metrics, ledger = [eligible_rows(frame) for frame in (appearances, metrics, ledger)]
    if appearances.empty:
        raise ValueError('No appearances meet the configured matchday qualification.')
    current = form_at_cutoff(payload, metadata, top_percent=settings.form_top_percent, matchday=matchday)
    evaluations = evaluate_next_matches(payload, metadata, metrics, settings)
    by_position, overall = summarize(metrics, ledger, evaluations, registry, settings, overrides)
    counts.update(valid_appearances=len(appearances), analysis_appearances=int((appearances.minutes_played >= settings.minimum_minutes).sum()),
        qualification_matchday=matchday, minimum_matchday_appearances=eligibility_metadata(matchday)['minimum_appearances'],
        players_excluded_by_matchday_qualification=int((~qualification.qualified).sum()),
        appearances_excluded_by_matchday_qualification=original_count-len(appearances),
        failed_matches=len(payload.get('failed_matches', [])), teams=appearances.team_id.nunique(),
        players=len(appearances[['team_id', 'player_id']].drop_duplicates()),
        below_analysis_minutes=int((appearances.minutes_played < settings.minimum_minutes).sum()))
    return dict(metadata=metadata, registry=registry, appearances=appearances, metrics=metrics,
        ledger=ledger, current_form=current, evaluations=evaluations,
        by_position=by_position, overall=overall, coverage=counts, qualification=qualification,
        qualification_policy=eligibility_metadata(matchday))
