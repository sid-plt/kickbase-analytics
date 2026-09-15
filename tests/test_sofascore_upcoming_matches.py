import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NOTEBOOK = Path(__file__).resolve().parents[1] / 'notebooks/03_team_data/05_sofascore_upcoming_matches.ipynb'

class UpcomingMatchCutoffTests(unittest.TestCase):
    def setUp(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        self.ns = dict(Path=Path, Any=Any, datetime=datetime, timezone=timezone,
                       MAX_PAGES=10, next_matchday=4,
                       BUNDESLIGA_UNIQUE_TOURNAMENT_ID=35,
                       expected_match_ids={20, 30}, analysis_match_ids_by_team={1: 10},
                       analysis_event_cache={}, print=lambda *args: None)
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                tree = ast.parse(''.join(cell['source']))
                compile(tree, str(NOTEBOOK), 'exec')
                definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
                exec(compile(ast.Module(body=definitions, type_ignores=[]), str(NOTEBOOK), 'exec'), self.ns)
        self.ns['fetch_sofascore_payload'] = lambda *args: {'event': self.event(10, 100)}

    def event(self, event_id, timestamp, competition=35):
        return dict(id=event_id, startTimestamp=timestamp,
                    homeTeam={'id': 1, 'name': 'Home'}, awayTeam={'id': 2, 'name': 'Away'},
                    tournament={'uniqueTournament': {'id': competition}})

    def collect(self, pages):
        calls = []
        def fetch(driver, team_id, page):
            calls.append(page)
            return pages[page], page < len(pages)-1
        self.ns['fetch_team_events_page'] = fetch
        return self.ns['collect_team_upcoming_matches'](None, 1, 'Home'), calls

    def test_both_selections_exclude_earlier_and_equal_kickoffs(self):
        result, calls = self.collect([
            [self.event(20, 90), self.event(10, 100)],
            [self.event(30, 200), self.event(40, 150, 7)],
        ])
        self.assertEqual(calls, [0, 1])
        self.assertEqual(result['next_match']['match_id'], 40)
        self.assertEqual(result['next_bundesliga_match']['match_id'], 30)

    def test_final_matchday_searches_later_pages_for_overall(self):
        self.ns['next_matchday'] = None
        result, calls = self.collect([[self.event(10, 100)], [self.event(40, 150, 7)]])
        self.assertEqual(calls, [0, 1])
        self.assertEqual(result['next_match']['match_id'], 40)
        self.assertIsNone(result['next_bundesliga_match'])

    def test_no_later_fixture_returns_none(self):
        result, _ = self.collect([[self.event(20, 90), self.event(10, 100)]])
        self.assertIsNone(result['next_match'])
        self.assertIsNone(result['next_bundesliga_match'])

    def test_missing_cutoff_fails_without_selecting(self):
        self.ns['fetch_sofascore_payload'] = lambda *args: {'event': {}}
        with self.assertRaises(self.ns['SofaScorePageError']):
            self.collect([[self.event(30, 200)]])

if __name__ == '__main__':
    unittest.main()

