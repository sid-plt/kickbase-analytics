import base64
import http.cookiejar
import json
import threading
import urllib.request

import pytest

import kickbase_screenshot_intake as intake


def test_fixture_teams_and_safe_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "SOFASCORE_MATCH_IDS_DIR", tmp_path)
    (tmp_path / "match_ids_3.json").write_text(
        json.dumps([
            {"home_team": "FC Bayern München", "away_team": "VfB Stuttgart"},
            {"home_team": "VfB Stuttgart", "away_team": "1. FC Köln"},
        ]),
        encoding="utf-8",
    )

    assert intake.load_teams(3) == ["FC Bayern München", "VfB Stuttgart", "1. FC Köln"]
    assert intake.team_filename("FC Bayern München", ".png") == "fc-bayern-munchen.png"
    with pytest.raises(intake.IntakeError, match="positive whole number"):
        intake.parse_matchday("0")
    with pytest.raises(intake.IntakeError, match="No fixture file"):
        intake.load_teams(4)


def test_phone_upload_replaces_team_image_and_tracks_coverage(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "match_ids_7.json").write_text(
        json.dumps([{"home_team": "FC Bayern München", "away_team": "VfB Stuttgart"}]),
        encoding="utf-8",
    )
    screenshot_root = tmp_path / "screenshots"
    monkeypatch.setattr(intake, "SOFASCORE_MATCH_IDS_DIR", fixtures)
    monkeypatch.setattr(intake, "SCREENSHOT_ROOT", screenshot_root)

    server = intake.IntakeServer(("127.0.0.1", 0), "123456")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path, payload):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener.open(request) as response:
            return json.loads(response.read())

    try:
        post("/api/login", {"pin": "123456"})
        first = b"\x89PNG\r\n\x1a\nfirst image"
        second = b"\xff\xd8\xffsecond image"
        post("/api/upload", {
            "matchday": "7", "team": "FC Bayern München",
            "image": "data:image/png;base64," + base64.b64encode(first).decode(),
        })
        post("/api/upload", {
            "matchday": "7", "team": "VfB Stuttgart",
            "image": "data:image/jpeg;base64," + base64.b64encode(first).decode(),
        })
        post("/api/upload", {
            "matchday": "7", "team": "FC Bayern München",
            "image": "data:image/jpeg;base64," + base64.b64encode(second).decode(),
        })

        folder = screenshot_root / "md7"
        assert (folder / "fc-bayern-munchen.jpg").read_bytes() == second
        assert not (folder / "fc-bayern-munchen.png").exists()
        assert (folder / "vfb-stuttgart.png").read_bytes() == first
        request = urllib.request.Request(base + "/api/teams?matchday=7")
        with opener.open(request) as response:
            coverage = json.loads(response.read())["teams"]
        assert [team["uploaded"] for team in coverage] == [True, True]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rejects_unlisted_team_and_invalid_image(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "match_ids_1.json").write_text(
        json.dumps([{"home_team": "Home FC", "away_team": "Away FC"}]), encoding="utf-8"
    )
    monkeypatch.setattr(intake, "SOFASCORE_MATCH_IDS_DIR", fixtures)
    with pytest.raises(intake.IntakeError, match="Unsupported or invalid image"):
        intake.image_extension(b"not an image")
    with pytest.raises(intake.IntakeError, match="not in the selected matchday"):
        intake.validate_team("Some Other FC", 1)


def test_pin_attempts_are_rate_limited():
    server = intake.IntakeServer(("127.0.0.1", 0), "123456")
    try:
        for _ in range(4):
            accepted, error = server.check_pin("192.168.1.25", "000000")
            assert not accepted
            assert error == "PIN is incorrect."
        accepted, error = server.check_pin("192.168.1.25", "000000")
        assert not accepted
        assert "Too many" in error
        assert server.check_pin("192.168.1.25", "123456")[0] is False
        assert server.check_pin("192.168.1.26", "123456")[0] is True
    finally:
        server.server_close()
