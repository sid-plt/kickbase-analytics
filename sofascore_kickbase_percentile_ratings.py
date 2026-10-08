"""Minute-group percentile ratings and their shared odds/lineup adapter."""
from __future__ import annotations

import json
import math
import warnings
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
from goalkeeper_kickbase_calibration import points_for_averages

from project_paths import (
    DERIVED_KICKBASE_PERCENTILE_RATINGS_DIR, SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR,
    SOFASCORE_TEAM_FORM_DIR, ensure_directory,
)

GROUPS = ['10–25 min', '25–50 min', '50–75 min', '75+ min']
PREFIX = 'sofascore_kickbase_percentile_ratings_'
METRIC_COLUMN = 'kickbase_percentile_rating'
OUTPUT_LABEL = 'sofascore_kickbase_percentile_rating_odds_lineup'


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def latest_json(directory, pattern):
    candidates = []
    for path in Path(directory).glob(pattern):
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        stamp = datetime.fromisoformat(document['generated_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        candidates.append((stamp, path.name, path))
    if not candidates:
        raise FileNotFoundError(f'No {pattern} in {directory}. Run the preceding derived notebook first.')
    return max(candidates)[2]


def report_flags(flags):
    for flag in flags:
        message = (f"RATING FALLBACK: {flag['group']}: {flag['appearance_count']} appearances, "
                   f"common points {flag['points']}; {flag['reason']}; assigned rating 6.8.")
        print(message)
        warnings.warn(message, UserWarning, stacklevel=2)


def derive_ratings(payload):
    rows, seen = [], set()
    counts = {'source': 0, 'invalid_points_or_minutes': 0, 'below_10_minutes': 0, 'included': 0}
    for team_id, team in payload['teams'].items():
        for player in team['overall']['players']:
            for match in player['match_calculations']:
                key = (str(team_id), player['player_id'], match['match_id'])
                if key in seen:
                    raise ValueError(f'Duplicate team/player/match record: {key}')
                seen.add(key)
                counts['source'] += 1
                minutes, points = match.get('minutes_played'), points_for_averages(match, player.get('position'))
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (minutes, points)):
                    counts['invalid_points_or_minutes'] += 1
                    continue
                if minutes < 10:
                    counts['below_10_minutes'] += 1
                    continue
                group = GROUPS[0 if minutes < 25 else 1 if minutes < 50 else 2 if minutes < 75 else 3]
                rows.append(dict(team_id=str(team_id), team=team['team'], player_id=player['player_id'],
                                 player_name=player['player_name'], position=player.get('position'),
                                 match_id=match['match_id'], minutes_played=minutes, points=points, group=group))
    frame = pd.DataFrame(rows, columns=['team_id', 'team', 'player_id', 'player_name', 'position',
                                       'match_id', 'minutes_played', 'points', 'group'])
    frame['percentile'] = pd.Series(index=frame.index, dtype=float)
    frame['rating'] = pd.Series(index=frame.index, dtype=float)
    flags = []
    for group in GROUPS:
        subset = frame.loc[frame.group == group]
        if subset.empty:
            continue
        ranks = subset.points.rank(method='average')
        span = ranks.max() - ranks.min()
        if span == 0:
            flags.append(dict(group=group, appearance_count=len(subset), points=float(subset.points.iloc[0]),
                              reason='singleton' if len(subset) == 1 else 'all_tied', fallback_rating=6.8))
            frame.loc[subset.index, 'percentile'] = 50.0
            frame.loc[subset.index, 'rating'] = 6.8
        else:
            percentiles = 100 * (ranks - ranks.min()) / span
            frame.loc[subset.index, 'percentile'] = percentiles
            # Decimal arithmetic avoids binary rounding at half-tenth boundaries.
            frame.loc[subset.index, 'rating'] = [rounded(Decimal('3.5') + Decimal('6.5') *
                (Decimal(str(rank)) - Decimal(str(ranks.min()))) / Decimal(str(span))) for rank in ranks]
    counts['included'] = len(frame)
    report_flags(flags)
    return frame, counts, flags


def export_ratings(source_path=None, output_dir=DERIVED_KICKBASE_PERCENTILE_RATINGS_DIR,
                   team_form_directory=SOFASCORE_TEAM_FORM_DIR):
    source_path = Path(source_path) if source_path else latest_json(
        SOFASCORE_PLAYER_KICKBASE_POINT_AVERAGES_DIR, 'overall_player_kickbase_point_averages_*.json')
    payload = json.loads(source_path.read_text(encoding='utf-8-sig'))
    frame, counts, flags = derive_ratings(payload)
    if frame.empty:
        raise ValueError('No valid appearances of at least 10 minutes; no rating export created.')
    source_name = payload['source_file']
    if not isinstance(source_name, str) or Path(source_name).name != source_name:
        raise ValueError('source_file must be a team-form filename.')
    snapshot = json.loads((Path(team_form_directory) / source_name).read_text(encoding='utf-8-sig'))
    if not all(str(key).isdigit() for key in snapshot):
        if len(snapshot) != 1:
            raise ValueError('Expected one timestamp-wrapped team-form snapshot.')
        snapshot = next(iter(snapshot.values()))
    opponents = {}
    for team_id, team in snapshot.items():
        for match in team.get('overall_matches', []):
            key = (str(team_id), match['match_id'])
            if key in opponents:
                raise ValueError(f'Duplicate team/match metadata: {key}')
            if str(match.get('home_team_id')) == str(team_id):
                opponents[key] = match.get('away_team')
            elif str(match.get('away_team_id')) == str(team_id):
                opponents[key] = match.get('home_team')
            else:
                opponents[key] = None
    frame['opponent'] = [opponents.get((row.team_id, row.match_id)) for row in frame.itertuples()]
    missing_opponents = int(frame.opponent.isna().sum())
    if missing_opponents:
        warnings.warn(f'Opponent unavailable for {missing_opponents} appearances; exported as null.', UserWarning)
    teams, summaries = {}, []
    for (team_id, player_id), records in frame.groupby(['team_id', 'player_id'], sort=False):
        first = records.iloc[0]
        average = rounded(sum(Decimal(str(v)) for v in records.rating) / len(records))
        player = dict(player_id=int(player_id), player_name=first.player_name, position=first.position,
                      rating_count=len(records), average_rating=average,
                      ratings=records[['match_id', 'opponent', 'minutes_played', 'points', 'group', 'percentile', 'rating']].to_dict('records'))
        teams.setdefault(team_id, dict(team=first.team, overall=dict(players=[])))['overall']['players'].append(player)
        summaries.append(dict(team_id=team_id, team=first.team, category='overall',
                              **{k: v for k, v in player.items() if k != 'ratings'}))
    now = datetime.now().astimezone()
    document = dict(generated_at=now.isoformat(), category='overall', source_file=payload['source_file'],
                    points_source_file=source_path.name, points_generated_at=payload['generated_at'],
                    eligibility=payload.get('eligibility', {}), exclusions=counts, fallback_flags=flags,
                    group_counts={group: int((frame.group == group).sum()) for group in GROUPS},
                    ranking_policy=dict(method='average ranks normalized by observed minimum/maximum ranks',
                        points='GK: valid calibrated total when available, event-derived fallback; outfield: event-derived points',
                        groups=['[10,25)', '[25,50)', '[50,75)', '[75,infinity)'],
                        rating_formula='3.5 + 6.5 * percentile / 100', rounding='half-up, one decimal',
                        degenerate_percentile=50, degenerate_rating=6.8), teams=teams)
    # Use the same team-slot weighting for displayed/exported averages and scores.
    weighted = _weighted_ratings(document, team_form_directory).set_index('player_id')
    for team in teams.values():
        for player in team['overall']['players']:
            player['average_rating'] = float(weighted.loc[player['player_id'], 'average_rating'])
    for summary in summaries:
        summary['average_rating'] = float(weighted.loc[summary['player_id'], 'average_rating'])
    from sofascore_rating_odds_lineup_score import OVERALL_RECENCY_WEIGHTS
    document['averaging_policy'] = dict(
        method='team-match recency weighted mean', newest_first_weights=list(OVERALL_RECENCY_WEIGHTS),
        missing_appearances='omit and renormalize without shifting team match slots',
        rounding='half-up, one decimal')
    stem = PREFIX + now.strftime('%Y-%m-%d_%H-%M-%S_%f%z')
    directory = ensure_directory(Path(output_dir))
    json_path, csv_path = directory / (stem + '.json'), directory / (stem + '.csv')
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    summary = pd.DataFrame(summaries)
    summary.to_csv(csv_path, index=False, encoding='utf-8-sig', float_format='%.1f')
    return dict(json_path=json_path, csv_path=csv_path, document=document, appearances=frame, players=summary)


def load_weighted_ratings(path, team_form_directory=SOFASCORE_TEAM_FORM_DIR):
    document = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    report_flags(document.get('fallback_flags', []))
    return _weighted_ratings(document, team_form_directory)


def _weighted_ratings(document, team_form_directory):
    from sofascore_rating_odds_lineup_score import OVERALL_RECENCY_WEIGHTS, _rating_match_chronology
    name = document['source_file']
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError('source_file must be a team-form filename.')
    snapshot = json.loads((Path(team_form_directory) / name).read_text(encoding='utf-8-sig'))
    if not all(str(key).isdigit() for key in snapshot):
        if len(snapshot) != 1:
            raise ValueError('Expected one timestamp-wrapped team-form snapshot.')
        snapshot = next(iter(snapshot.values()))
    rows, seen_players = [], set()
    for team_id, team in document['teams'].items():
        matches = snapshot[team_id]['overall_matches']
        ids = [m['match_id'] for m in matches]
        if not 1 <= len(matches) <= 5 or len(set(ids)) != len(ids):
            raise ValueError('Expected one to five unique team match slots.')
        ordered = sorted(matches, key=lambda m: (_rating_match_chronology(m), m['match_id']), reverse=True)
        weights = {m['match_id']: Decimal(str(w)) for m, w in zip(ordered, OVERALL_RECENCY_WEIGHTS)}
        for player in team['overall']['players']:
            if player['player_id'] in seen_players:
                raise ValueError('Duplicate player ID in derived ratings.')
            seen_players.add(player['player_id'])
            numerator = denominator = Decimal(0)
            seen = set()
            if not player['ratings'] or len(player['ratings']) != player['rating_count']:
                raise ValueError('Inconsistent rating count.')
            for record in player['ratings']:
                identifier, rating = record['match_id'], record['rating']
                if identifier not in weights or identifier in seen:
                    raise ValueError('Unknown or duplicate rated match ID.')
                if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not math.isfinite(rating) or not 3.5 <= rating <= 10:
                    raise ValueError('Rating must be finite and between 3.5 and 10.')
                seen.add(identifier)
                numerator += weights[identifier] * Decimal(str(rating))
                denominator += weights[identifier]
            rows.append(dict(player_id=player['player_id'], player_name=player['player_name'],
                             position=player.get('position'), average_rating=rounded(numerator / denominator)))
    if not rows:
        raise ValueError('No player ratings in derived export.')
    return pd.DataFrame(rows)


def run_score_creation(questionable_injury_starting_chance_penalty=0.15,
                       alternative_starting_chance_decay=0.45, lineup_source_weights=None,
                       score_multiplier=10.0062, goalkeeper_alternative_starting_chance_decay=0.60):
    from sofascore_rating_odds_lineup_score import ScoreMetricInput, run_score_creation as run_shared
    path = latest_json(DERIVED_KICKBASE_PERCENTILE_RATINGS_DIR, PREFIX + '*.json')
    metric = ScoreMetricInput(path, load_weighted_ratings(path), METRIC_COLUMN,
                              'Kickbase percentile rating', OUTPUT_LABEL)
    return run_shared('overall', metric_input=metric,
        questionable_injury_starting_chance_penalty=questionable_injury_starting_chance_penalty,
        alternative_starting_chance_decay=alternative_starting_chance_decay,
        lineup_source_weights=lineup_source_weights, score_multiplier=score_multiplier,
        goalkeeper_alternative_starting_chance_decay=goalkeeper_alternative_starting_chance_decay)
