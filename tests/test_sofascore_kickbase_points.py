import json
from pathlib import Path

from sofascore_kickbase_points import MetricCatalog, score_from_match, scoring_policy, team_block_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_team_block_locations_sides_and_missing_data():
    shots = [dict(shotType='block', isHome=False, blockCoordinates=dict(x=x, y=y))
             for x, y in [(4, 50), (10, 50), (20, 50), (4, 90)]]
    shots += [dict(shotType='block', isHome=True, blockCoordinates=dict(x=4, y=50)),
              dict(shotType='block', isHome=False),
              dict(shotType='block', isHome=False, blockCoordinates=dict(x=float('nan'), y=50)),
              dict(shotType='save', isHome=False, blockCoordinates=dict(x=4, y=50))]
    result = team_block_values(shots, catalog())
    assert result['home']['points_per_action'] == 8.75
    assert result['home']['sample_count'] == 4
    assert result['away']['points_per_action'] == 15
    assert team_block_values([], catalog())['home']['points_per_action'] == 5
    assert team_block_values([], catalog())['home']['fallback'] is True


def test_block_subtotal_uses_fractional_mean_and_half_up_rounding():
    lineups = {'home': {'players': [dict(player=dict(id=1, name='Defender'), teamId=10,
               position='D', substitute=False, statistics=dict(minutesPlayed=90, outfielderBlock=2))]},
               'away': {'players': []}}
    shots = [dict(shotType='block', isHome=False, blockCoordinates=dict(x=x, y=50))
             for x in (4, 10, 20, 20)]
    def run(shotmap):
        return score_from_match(dict(match_id=1, home_team_id=10, away_team_id=20),
                                lineups, {'incidents': []}, {'shotmap': shotmap}, catalog())['players'][0]
    player = run(shots)
    block = next(a for a in player['awards'] if a['metric_id'] == 'shot_blocked')
    assert block['points_per_action'] == 8.75
    assert block['points'] == 18  # 2 * 8.75 = 17.5, half-up
    assert block['confidence'] == 'proxy'
    assert award_points(run([]), 'shot_blocked') == 10


def catalog() -> MetricCatalog:
    return MetricCatalog.from_document(json.loads((PROJECT_ROOT / "data" / "reference" / "kickbase" / "kickbase_metrics.json").read_text(encoding="utf-8")))


def award_points(player, metric_id):
    return sum(award["points"] for award in player["awards"] if award["metric_id"] == metric_id)


def test_match_score_covers_confirmed_penalties_errors_and_woodwork() -> None:
    lineups = {
        "confirmed": True,
        "home": {"players": [{"player": {"id": 1, "name": "Home Forward"}, "teamId": 10, "position": "F", "substitute": False, "statistics": {"minutesPlayed": 90, "bigChanceCreated": 1, "clearanceOffLine": 1, "errorLeadToAShot": 1}}]},
        "away": {"players": [{"player": {"id": 2, "name": "Away Goalkeeper"}, "teamId": 20, "position": "G", "substitute": False, "statistics": {"minutesPlayed": 90}}]},
    }
    incidents = {
        "incidents": [
            {"incidentType": "goal", "incidentClass": "penalty", "from": "penalty", "player": {"id": 1}, "isHome": True, "timeSeconds": 1200},
            {"incidentType": "inGamePenalty", "incidentClass": "missed", "reason": "goalkeeperSave", "player": {"id": 1}, "isHome": True, "timeSeconds": 2400},
            {"incidentType": "period", "text": "FT", "homeScore": 1, "awayScore": 0},
        ]
    }
    shotmap = {"shotmap": [
        {"player": {"id": 1}, "shotType": "goal", "playerCoordinates": {"x": 11.5, "y": 50}},
        {"player": {"id": 1}, "shotType": "post", "playerCoordinates": {"x": 20, "y": 50}},
    ]}
    result = score_from_match({"match_id": 99, "home_team_id": 10, "away_team_id": 20, "home_score": 1, "away_score": 0}, lineups, incidents, shotmap, catalog())
    players = {player["player_id"]: player for player in result["players"]}
    assert award_points(players[1], "penalty_scored") == 80
    assert award_points(players[1], "penalty_missed") == -60
    assert award_points(players[2], "penalty_saved") == 100
    assert award_points(players[1], "big_chance_created") == 15
    assert award_points(players[1], "goal_line_clearance") == 15
    assert award_points(players[1], "mistake_before_shot") == -15
    assert award_points(players[1], "post_label_crossbar") == 10
    assert award_points(players[1], "clean_sheet") == 10
    assert award_points(players[2], "clean_sheet") == 0


def test_scoring_policy_keeps_the_selected_big_chance_rule_and_grouped_woodwork() -> None:
    policy = scoring_policy()
    assert policy["big_chance_created_points"] == 15
    assert policy["woodwork_group"]["points"] == 10
    assert policy["woodwork_group"]["metric_ids"] == ["post_label_crossbar", "left_post", "right_post"]


def test_team_goals_follow_starter_and_substitute_on_pitch_intervals() -> None:
    lineups = {
        "home": {"players": [
            {"player": {"id": 1, "name": "Starter"}, "teamId": 10, "position": "M", "substitute": False, "statistics": {"minutesPlayed": 45}},
            {"player": {"id": 3, "name": "Substitute"}, "teamId": 10, "position": "M", "substitute": True, "statistics": {"minutesPlayed": 45}},
        ]},
        "away": {"players": [{"player": {"id": 2, "name": "Away"}, "teamId": 20, "position": "D", "substitute": False, "statistics": {"minutesPlayed": 90}}]},
    }
    incidents = {"incidents": [
        {"incidentType": "goal", "player": {"id": 1}, "isHome": True, "timeSeconds": 1800},
        {"incidentType": "substitution", "playerIn": {"id": 3}, "playerOut": {"id": 1}, "timeSeconds": 2700},
        {"incidentType": "goal", "player": {"id": 3}, "isHome": True, "timeSeconds": 3600},
        {"incidentType": "period", "text": "FT", "homeScore": 2, "awayScore": 0},
    ]}
    result = score_from_match({"match_id": 100, "home_team_id": 10, "away_team_id": 20, "home_score": 2, "away_score": 0}, lineups, incidents, {"shotmap": []}, catalog())
    players = {player["player_id"]: player for player in result["players"]}
    assert award_points(players[1], "team_goal") == 5
    assert award_points(players[3], "team_goal") == 5
    assert award_points(players[1], "starting_eleven") == 5
    assert award_points(players[3], "subbed_on") == 2
