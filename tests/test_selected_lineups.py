from selected_lineups import (
    load_selected_lineup,
    make_selected_lineup,
    select_lineup_interactively,
    selected_lineup_path,
)


def _players():
    return [
        {
            "id": str(index),
            "name": f"Player {index}",
            "position": "GK" if index == 1 else "MID",
            "market_value": 1_000_000,
        }
        for index in range(1, 12)
    ]


def _lineup(value=100):
    return make_selected_lineup(
        "Bundesliga Arena", _players(), {"value": value}, "manual"
    )


def test_save_and_load_selected_lineup(tmp_path):
    path = select_lineup_interactively(_lineup(), tmp_path, input_func=lambda _: "yes")

    assert path == selected_lineup_path("Bundesliga Arena", tmp_path).resolve()
    assert load_selected_lineup("Bundesliga Arena", tmp_path)["expected_points"]["value"] == 100


def test_declining_selection_does_not_write(tmp_path):
    assert select_lineup_interactively(_lineup(), tmp_path, input_func=lambda _: "no") is None
    assert load_selected_lineup("Bundesliga Arena", tmp_path) is None


def test_existing_selection_requires_replacement_confirmation(tmp_path):
    select_lineup_interactively(_lineup(100), tmp_path, input_func=lambda _: "yes")
    answers = iter(("yes", "no"))

    assert select_lineup_interactively(_lineup(200), tmp_path, input_func=lambda _: next(answers)) is None
    assert load_selected_lineup("Bundesliga Arena", tmp_path)["expected_points"]["value"] == 100
