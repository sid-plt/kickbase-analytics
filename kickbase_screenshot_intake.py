"""Local phone upload page for Kickbase lineup screenshots.

Run from the project root with ``python kickbase_screenshot_intake.py``.
The server is intended for a trusted local Wi-Fi network only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
import unicodedata
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from project_paths import PROJECT_ROOT, SOFASCORE_MATCH_IDS_DIR


SCREENSHOT_ROOT = PROJECT_ROOT / "data" / "kickbase_lineup_screenshots"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PIN_LIFETIME_SECONDS = 30 * 60
SESSION_COOKIE = "kickbase_upload_session"
SUPPORTED_SIGNATURES = (
    (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    (".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
)

PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#101b2d">
  <title>Kickbase screenshot upload</title>
  <style>
    :root { color-scheme: dark; font: 16px system-ui, sans-serif; background: #101b2d; color: #f1f5f9; }
    body { max-width: 620px; margin: 0 auto; padding: 22px 16px 48px; }
    h1 { font-size: 1.5rem; margin: 8px 0; } p { color: #b9c6d8; line-height: 1.45; }
    .card { background: #1b2a40; border: 1px solid #30435e; border-radius: 16px; padding: 18px; margin: 16px 0; }
    label { display: block; font-weight: 650; margin: 14px 0 7px; }
    input, select, button { width: 100%; box-sizing: border-box; min-height: 48px; border-radius: 10px; font: inherit; }
    input, select { background: #0d1727; color: #f1f5f9; border: 1px solid #526783; padding: 10px 12px; }
    input[type=file] { padding: 9px; }
    button { margin-top: 16px; border: 0; background: #3b82f6; color: white; font-weight: 750; }
    button:disabled { opacity: .55; }
    .muted { color: #aab8ca; font-size: .92rem; }
    .status { min-height: 1.5em; color: #bfdbfe; }
    .team { display: flex; justify-content: space-between; gap: 12px; padding: 9px 2px; border-bottom: 1px solid #30435e; }
    .team:last-child { border: 0; } .done { color: #86efac; } .missing { color: #fcd34d; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <h1>Kickbase lineup screenshots</h1>
  <p>Choose a matchday, team, and screenshot. Images are saved on the project PC.</p>
  <section class="card" id="loginCard">
    <label for="pin">Upload PIN</label><input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6-digit PIN">
    <button id="loginButton">Unlock uploads</button><div class="status" id="loginStatus"></div>
  </section>
  <main id="app" class="hidden">
    <section class="card">
      <label for="matchday">Matchday</label><input id="matchday" type="number" min="1" step="1" value="1">
      <label for="team">Team</label><select id="team"><option value="">Loading fixtures…</option></select>
      <label for="image">Screenshot</label><input id="image" type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp">
      <div class="muted">JPEG, PNG, or WebP · up to 15 MB. Uploading again replaces that team’s screenshot.</div>
      <button id="uploadButton">Save screenshot</button><div class="status" id="status" role="status"></div>
    </section>
    <section class="card"><h2>Matchday coverage</h2><div id="coverage" class="muted">Select a matchday to see teams.</div></section>
  </main>
<script>
const $ = (id) => document.getElementById(id);
async function request(url, options={}) {
  const response = await fetch(url, {credentials:'same-origin', ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}
function showApp() { $('loginCard').classList.add('hidden'); $('app').classList.remove('hidden'); loadTeams(); }
$('loginButton').addEventListener('click', async () => {
  $('loginStatus').textContent = 'Checking PIN…';
  try { await request('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pin:$('pin').value})}); showApp(); }
  catch (e) { $('loginStatus').textContent = e.message; }
});
async function loadTeams() {
  const day = $('matchday').value;
  $('team').innerHTML = '<option value="">Loading…</option>';
  try {
    const data = await request(`/api/teams?matchday=${encodeURIComponent(day)}`);
    $('team').innerHTML = '<option value="">Choose a team</option>' + data.teams.map(t => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`).join('');
    $('coverage').innerHTML = data.teams.map(t => `<div class="team"><span>${escapeHtml(t.name)}</span><span class="${t.uploaded?'done':'missing'}">${t.uploaded?'Saved':'Missing'}</span></div>`).join('');
  } catch (e) {
    $('team').innerHTML = '<option value="">Fixture unavailable</option>';
    $('coverage').textContent = e.message;
  }
}
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
$('matchday').addEventListener('change', loadTeams);
$('uploadButton').addEventListener('click', async () => {
  const file = $('image').files[0];
  if (!file || !$('team').value) { $('status').textContent = 'Choose a team and screenshot first.'; return; }
  if (file.size > 15 * 1024 * 1024) { $('status').textContent = 'Image exceeds the 15 MB limit.'; return; }
  const button = $('uploadButton'); button.disabled = true; $('status').textContent = 'Saving…';
  try {
    const dataUrl = await new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=()=>reject(new Error('Could not read the selected image.')); reader.readAsDataURL(file); });
    const result = await request('/api/upload', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({matchday:$('matchday').value, team:$('team').value, image:dataUrl})});
    $('status').textContent = `Saved ${result.filename}`; $('image').value=''; await loadTeams();
  } catch (e) { $('status').textContent = e.message; }
  finally { button.disabled = false; }
});
fetch('/api/session', {credentials:'same-origin'}).then(r=>r.ok?showApp():null).catch(()=>{});
</script>
</body></html>"""


class IntakeError(ValueError):
    """An expected validation error suitable for showing in the upload page."""


def parse_matchday(value: object) -> int:
    text = str(value).strip()
    if not text.isdigit() or int(text) < 1:
        raise IntakeError("Matchday must be a positive whole number.")
    return int(text)


def load_teams(matchday: int) -> list[str]:
    fixture_path = SOFASCORE_MATCH_IDS_DIR / f"match_ids_{parse_matchday(matchday)}.json"
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise IntakeError(f"No fixture file found for matchday {matchday}.") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeError(f"Could not read matchday {matchday} fixtures: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise IntakeError(f"Fixture file for matchday {matchday} is empty or malformed.")
    teams: list[str] = []
    for number, match in enumerate(payload, start=1):
        if not isinstance(match, dict):
            raise IntakeError(f"Fixture {number} is not an object.")
        for side in ("home_team", "away_team"):
            team = match.get(side)
            if not isinstance(team, str) or not team.strip():
                raise IntakeError(f"Fixture {number} is missing {side}.")
            name = team.strip()
            if name not in teams:
                teams.append(name)
    return teams


def validate_team(team: object, matchday: int) -> str:
    if not isinstance(team, str) or not team.strip():
        raise IntakeError("Choose a team from the list.")
    team = team.strip()
    if team not in load_teams(matchday):
        raise IntakeError("That team is not in the selected matchday fixtures.")
    return team


def team_filename(team: str, extension: str) -> str:
    normalized = unicodedata.normalize("NFKD", team).encode("ascii", "ignore").decode("ascii")
    slug = "-".join("".join(char.lower() if char.isalnum() else " " for char in normalized).split())
    if not slug:
        raise IntakeError("Could not create a safe filename for this team.")
    return f"{slug}{extension}"


def image_extension(data: bytes) -> str:
    for extension, matches in SUPPORTED_SIGNATURES:
        if matches(data):
            return extension
    raise IntakeError("Unsupported or invalid image. Choose a JPEG, PNG, or WebP screenshot.")


def existing_screenshot(folder: Path, team: str) -> Path | None:
    for extension, _ in SUPPORTED_SIGNATURES:
        candidate = folder / team_filename(team, extension)
        if candidate.is_file():
            return candidate
    return None


class IntakeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], pin: str):
        super().__init__(address, IntakeHandler)
        self.pin = pin
        self.started_at = time.monotonic()
        self.session_token = secrets.token_urlsafe(32)
        self.session_hash = hashlib.sha256(self.session_token.encode()).digest()
        self.pin_lock = threading.Lock()
        self.pin_failures: dict[str, tuple[int, float]] = {}

    def check_pin(self, client_ip: str, supplied: str) -> tuple[bool, str | None]:
        now = time.monotonic()
        with self.pin_lock:
            failures, blocked_until = self.pin_failures.get(client_ip, (0, 0.0))
            if now < blocked_until:
                return False, "Too many incorrect PIN attempts. Try again in 10 minutes."
            if now - self.started_at >= PIN_LIFETIME_SECONDS:
                return False, "PIN has expired. Restart the app for a new PIN."
            if hmac.compare_digest(supplied, self.pin):
                self.pin_failures.pop(client_ip, None)
                return True, None
            failures += 1
            if failures >= 5:
                self.pin_failures[client_ip] = (0, now + 10 * 60)
                return False, "Too many incorrect PIN attempts. Try again in 10 minutes."
            self.pin_failures[client_ip] = (failures, 0.0)
            return False, "PIN is incorrect."


class IntakeHandler(BaseHTTPRequestHandler):
    server: IntakeServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # Do not log cookies, PINs, or upload payloads.
        super().log_message(format, *args)

    def _send(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict[str, object], headers: dict[str, str] | None = None) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", headers)

    def _read_json(self, maximum: int = MAX_UPLOAD_BYTES * 2) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit():
            raise IntakeError("A valid Content-Length header is required.")
        length = int(raw_length)
        if length > maximum:
            raise IntakeError("Request is too large.")
        try:
            body = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntakeError("Request body must be valid JSON.") from exc
        if not isinstance(body, dict):
            raise IntakeError("Request body must be a JSON object.")
        return body

    def _authenticated(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            supplied = cookie[SESSION_COOKIE].value.encode() if SESSION_COOKIE in cookie else b""
        except (KeyError, TypeError, ValueError):
            return False
        supplied_hash = hashlib.sha256(supplied).digest()
        return time.monotonic() - self.server.started_at < PIN_LIFETIME_SECONDS and hmac.compare_digest(supplied_hash, self.server.session_hash)

    def _is_local_client(self) -> bool:
        try:
            address = ipaddress.ip_address(self.client_address[0].split("%", 1)[0])
            return address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            return False

    def do_GET(self) -> None:
        if not self._is_local_client():
            self._json(HTTPStatus.FORBIDDEN, {"error": "This upload page is available only from a local network."})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(HTTPStatus.OK, PAGE.encode(), "text/html; charset=utf-8")
        elif parsed.path == "/api/session":
            self._json(HTTPStatus.OK if self._authenticated() else HTTPStatus.UNAUTHORIZED, {"authenticated": self._authenticated()})
        elif parsed.path == "/api/teams":
            if not self._authenticated():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Enter the upload PIN first."})
                return
            try:
                query = parse_qs(parsed.query)
                if len(query.get("matchday", [])) != 1:
                    raise IntakeError("Provide one valid matchday.")
                matchday = parse_matchday(query["matchday"][0])
                teams = load_teams(matchday)
                folder = SCREENSHOT_ROOT / f"md{matchday}"
                self._json(HTTPStatus.OK, {"teams": [{"name": name, "uploaded": existing_screenshot(folder, name) is not None} for name in teams]})
            except IntakeError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._is_local_client():
            self._json(HTTPStatus.FORBIDDEN, {"error": "This upload page is available only from a local network."})
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/login":
                payload = self._read_json(4096)
                pin = str(payload.get("pin", ""))
                accepted, error = self.server.check_pin(self.client_address[0], pin)
                if not accepted:
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": error or "PIN rejected."})
                    return
                self._json(HTTPStatus.OK, {"authenticated": True}, {"Set-Cookie": f"{SESSION_COOKIE}={self.server.session_token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={PIN_LIFETIME_SECONDS}"})
                return
            if parsed.path != "/api/upload":
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
                return
            if not self._authenticated():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Upload PIN expired. Restart the app and unlock again."})
                return
            payload = self._read_json()
            matchday = parse_matchday(payload.get("matchday", ""))
            team = validate_team(payload.get("team"), matchday)
            data_url = payload.get("image")
            if not isinstance(data_url, str) or "," not in data_url:
                raise IntakeError("Select an image file to upload.")
            header, encoded = data_url.split(",", 1)
            if not header.startswith("data:image/"):
                raise IntakeError("The selected file is not an image.")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise IntakeError("Could not decode the uploaded image.") from exc
            if not data or len(data) > MAX_UPLOAD_BYTES:
                raise IntakeError("Image must be non-empty and no larger than 15 MB.")
            extension = image_extension(data)
            folder = SCREENSHOT_ROOT / f"md{matchday}"
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / team_filename(team, extension)
            temporary = destination.with_name(destination.name + f".{secrets.token_hex(6)}.tmp")
            try:
                temporary.write_bytes(data)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            # Remove the previous canonical image if its format changed.
            for other_extension, _ in SUPPORTED_SIGNATURES:
                previous = folder / team_filename(team, other_extension)
                if previous != destination and previous.exists():
                    previous.unlink()
            self._json(HTTPStatus.OK, {"saved": True, "filename": destination.name, "matchday": matchday, "team": team})
        except IntakeError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (OSError, ValueError) as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Could not save screenshot: {exc}"})


def local_ipv4() -> str | None:
    """Ask Windows which local IPv4 address it would use for outbound traffic."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
        return address if not address.startswith("127.") else None
    except OSError:
        return None
    finally:
        probe.close()


def main() -> None:
    pin = f"{secrets.randbelow(1_000_000):06d}"
    server = IntakeServer(("0.0.0.0", 8765), pin)
    lan_ip = local_ipv4()
    print("Kickbase screenshot intake is running on your local network.")
    print(f"On this PC: http://127.0.0.1:8765")
    if lan_ip:
        print(f"On your phone: http://{lan_ip}:8765")
    else:
        print("On your phone: use this PC's Wi-Fi IPv4 address with port 8765.")
    print(f"Upload PIN: {pin} (valid for 30 minutes)")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping screenshot intake.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
