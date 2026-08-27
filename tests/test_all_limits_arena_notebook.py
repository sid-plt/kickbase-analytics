import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = (
    PROJECT_ROOT / "notebooks" / "07_squad_optimisation" / "optimize_squad_all_limits_arena.ipynb"
)


def test_all_limits_arena_notebook_has_the_required_rules_and_selection_path():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8-sig"))
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])

    assert "SQUAD_SIZE = 11" in source
    assert "BUDGET_EUR = 150_000_000" in source
    assert "MAX_PLAYERS_PER_CLUB = 1" in source
    assert "MAX_PLAYERS_PER_MATCH = 2" in source
    assert "'4-4-2': {'DEF': 4, 'MID': 4, 'FOR': 2}" in source
    assert "'5-2-3': {'DEF': 5, 'MID': 2, 'FOR': 3}" in source
    assert "'CaptainCardinality'" in source
    assert "CaptainMustBeSelected_" in source
    assert "player_count=SQUAD_SIZE" in source
    assert "filename='all-limits-arena.json'" in source
    assert all(not cell.get("outputs") for cell in notebook["cells"] if cell["cell_type"] == "code")
