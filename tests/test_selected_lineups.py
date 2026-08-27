import json


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


def _six_player_lineup(value=100):
    return make_selected_lineup(
        "Kickbase.insider Arena",
        _players()[:6],
        {"value": value},
        "optimizer_insider_arena",
        player_count=6,
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


def test_legacy_eleven_player_snapshot_without_player_count_remains_valid(tmp_path):
    legacy = _lineup()
    legacy.pop("player_count")
    selected_lineup_path("Bundesliga Arena", tmp_path).write_text(
        json.dumps(legacy), encoding="utf-8"
    )

    loaded = load_selected_lineup("Bundesliga Arena", tmp_path)

    assert loaded is not None
    assert len(loaded["players"]) == 11


def test_eleven_player_lineup_uses_custom_filename_and_requires_replacement_confirmation(tmp_path):
    filename = "all-limits-arena.json"
    first = make_selected_lineup("All Limits Arena", _players(), {"value": 100}, "manual")
    first_path = select_lineup_interactively(
        first, tmp_path, input_func=lambda _: "yes", filename=filename
    )

    assert first_path == (tmp_path / filename).resolve()

    replacement = make_selected_lineup("All Limits Arena", _players(), {"value": 200}, "manual")
    answers = iter(("yes", "no"))
    assert (
        select_lineup_interactively(
            replacement,
            tmp_path,
            input_func=lambda _: next(answers),
            filename=filename,
        )
        is None
    )
    assert load_selected_lineup("All Limits Arena", tmp_path, filename)["expected_points"]["value"] == 100

    answers = iter(("yes", "yes"))
    assert select_lineup_interactively(
        replacement,
        tmp_path,
        input_func=lambda _: next(answers),
        filename=filename,
    ) == (tmp_path / filename).resolve()
    assert load_selected_lineup("All Limits Arena", tmp_path, filename)["expected_points"]["value"] == 200


def test_six_player_lineup_uses_explicit_filename_and_requires_replacement_confirmation(tmp_path):
    filename = "kickbase.insider-arena.json"
    first_path = select_lineup_interactively(
        _six_player_lineup(100), tmp_path, input_func=lambda _: "yes", filename=filename
    )

    assert first_path == (tmp_path / filename).resolve()
    assert load_selected_lineup("Kickbase.insider Arena", tmp_path, filename)["player_count"] == 6

    answers = iter(("yes", "no"))
    assert (
        select_lineup_interactively(
            _six_player_lineup(200),
            tmp_path,
            input_func=lambda _: next(answers),
            filename=filename,
        )
        is None
    )
    assert load_selected_lineup("Kickbase.insider Arena", tmp_path, filename)["expected_points"]["value"] == 100

    answers = iter(("yes", "yes"))
    assert select_lineup_interactively(
        _six_player_lineup(200),
        tmp_path,
        input_func=lambda _: next(answers),
        filename=filename,
    ) == (tmp_path / filename).resolve()
    assert load_selected_lineup("Kickbase.insider Arena", tmp_path, filename)["expected_points"]["value"] == 200
