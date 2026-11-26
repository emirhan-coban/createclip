"""Upload a finished clip to YouTube (Data API v3), only when the user asks for that clip.

Credentials live in <root>/data/youtube/ (gitignored): client_secret.json is the "Desktop app" OAuth client the user
downloads from Google Cloud, token.json is written after consent. Standard library only."""
import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from . import config, proc, store

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = 8 * 1024 * 1024        # must be a multiple of 256 KiB
RETRIES = 3
LEAD = 15 * 60                 # a queue slot must be at least this far ahead (upload + YouTube processing)
CATEGORY = "24"                # Entertainment

_pending: dict[str, tuple[str, str]] = {}          # OAuth state -> (PKCE verifier, redirect uri)


class PublishError(RuntimeError):
    pass


# ---------------------------------------------------------------- credentials
def folder() -> Path:
    d = config.data_dir() / "youtube"
    d.mkdir(parents=True, exist_ok=True)
    return d


def client_secret_path() -> Path:
    return folder() / "client_secret.json"


def _token_path() -> Path:
    return folder() / "token.json"


def _client() -> dict:
    try:
        d = json.loads(client_secret_path().read_text())
        c = d.get("installed") or d["web"]
        return {"id": c["client_id"], "secret": c["client_secret"]}
    except (OSError, ValueError, KeyError, TypeError):
        raise PublishError(f"Google istemci dosyası yok ya da bozuk: {client_secret_path()}") from None


def _read_token() -> dict | None:
    try:
        return json.loads(_token_path().read_text())
    except (OSError, ValueError):
        return None


def _write_token(t: dict):
    p = _token_path()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(t, fh)


def status() -> dict:
    try:
        _client()
        configured = True
    except PublishError:
        configured = False
    t = _read_token()
    return {"configured": configured, "connected": bool(configured and t and t.get("refresh_token")),
            "channel": (t or {}).get("channel", ""), "client_secret": str(client_secret_path())}


def disconnect():
    _token_path().unlink(missing_ok=True)


# ---------------------------------------------------------------- HTTP
def _http(method: str, url: str, headers: dict | None = None, body: bytes | None = None, timeout: float = 120):
    """(status, headers, body). HTTP error statuses (and 308 "resume incomplete") are returned, not raised."""
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _error_text(body: bytes) -> str:
    try:
        e = json.loads(body)["error"]
        if isinstance(e, str):
            return e
        reason = (e.get("errors") or [{}])[0].get("reason", "")
        return f"{e.get('message', '')} ({reason})".strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        return body[:200].decode("utf-8", "replace")


def _token_request(fields: dict) -> dict:
    code, _, body = _http("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, urlencode(fields).encode())
    if code != 200:
        if b"invalid_grant" in body:
            raise PublishError("YouTube izni geçersiz ya da süresi dolmuş. Ayarlar > YouTube'dan yeniden bağlan.")
        raise PublishError(f"Google izin hatası: {_error_text(body)}")
    return json.loads(body)


# ---------------------------------------------------------------- OAuth (loopback redirect + PKCE)
def auth_url(redirect_uri: str) -> str:
    c = _client()
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    _pending.clear()                                   # only the latest attempt can finish
    _pending[state] = (verifier, redirect_uri)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTH_URL + "?" + urlencode({
        "client_id": c["id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES, "state": state,
        "access_type": "offline", "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256"})


def finish_auth(state: str, code: str):
    if state not in _pending:
        raise PublishError("Bağlantı isteği tanınmadı; Ayarlar'dan yeniden başlat.")
    verifier, redirect_uri = _pending.pop(state)
    c = _client()
    t = _token_request({"grant_type": "authorization_code", "code": code, "client_id": c["id"], "client_secret": c["secret"],
                        "redirect_uri": redirect_uri, "code_verifier": verifier})
    if not t.get("refresh_token"):
        raise PublishError("Google kalıcı izin vermedi; yeniden dene.")
    token = {"refresh_token": t["refresh_token"], "access_token": t["access_token"],
             "expires": time.time() + t.get("expires_in", 3600), "channel": ""}
    try:
        code_, _, body = _http("GET", f"{API}/channels?part=snippet&mine=true", {"Authorization": f"Bearer {token['access_token']}"})
        if code_ == 200:
            token["channel"] = json.loads(body)["items"][0]["snippet"]["title"]
    except (OSError, ValueError, KeyError, IndexError):
        pass                                           # the name is only for display
    _write_token(token)


def access_token() -> str:
    t = _read_token()
    if not t or not t.get("refresh_token"):
        raise PublishError("YouTube bağlı değil. Ayarlar > YouTube'dan bağlan.")
    if t.get("access_token") and t.get("expires", 0) > time.time() + 60:
        return t["access_token"]
    c = _client()
    new = _token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                          "client_id": c["id"], "client_secret": c["secret"]})
    t.update(access_token=new["access_token"], expires=time.time() + new.get("expires_in", 3600))
    _write_token(t)
    return t["access_token"]


# ---------------------------------------------------------------- queue slots
def parse_times(values) -> list[str]:
    """['13:00', '20:00'] cleaned and sorted; raises ValueError on anything else."""
    out = set()
    for v in values:
        m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(v))
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError(f"saat 'SS:DD' olmalı: {v}")
        out.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    if not out or len(out) > 12:
        raise ValueError("1–12 saat yaz")
    return sorted(out)


def next_slot(times: list[str], taken: list[float], now: float | None = None) -> float:
    """The first free daily slot (local time) at least LEAD seconds from now. `taken` are already scheduled epochs."""
    now = time.time() if now is None else now
    used = {int(t // 60) for t in taken}
    day = datetime.fromtimestamp(now).date()
    for i in range(len(used) + 3):
        for hm in times:
            h, m = map(int, hm.split(":"))
            d = day + timedelta(days=i)
            t = datetime(d.year, d.month, d.day, h, m).timestamp()
            if t >= now + LEAD and int(t // 60) not in used:
                return t
    raise PublishError("Boş yayın saati bulunamadı.")


def scheduled(con) -> list[float]:
    return [r["yt_publish_at"] for r in store.rows(con, "SELECT yt_publish_at FROM clips WHERE yt_publish_at IS NOT NULL")]


# ---------------------------------------------------------------- upload
def metadata(title: str, description: str, tags: list[str], publish_at: float | None) -> dict:
    clean = lambda s: s.replace("<", "").replace(">", "")          # noqa: E731 - YouTube rejects angle brackets
    title = clean(title).strip()[:100]
    if not title:
        raise PublishError("Başlık boş olamaz.")
    kept, size = [], 0
    for t in (clean(str(x)).lstrip("#").strip() for x in tags):
        size += len(t) + 3
        if t and size <= 450:                                      # API limit is 500 characters in total
            kept.append(t)
    desc = clean(description).encode("utf-8")[:5000].decode("utf-8", "ignore")
    st = {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    if publish_at:                                                  # scheduling needs a private video + publishAt
        st["privacyStatus"] = "private"
        st["publishAt"] = datetime.fromtimestamp(publish_at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"snippet": {"title": title, "description": desc, "tags": kept, "categoryId": CATEGORY}, "status": st}


def _received(headers) -> int:
    """Bytes the server already has, from the 308 response's `Range: bytes=0-N` header."""
    m = re.search(r"-(\d+)$", headers.get("Range") or "")
    return int(m.group(1)) + 1 if m else 0


def upload_video(file: Path, meta: dict, progress=lambda f, t="": None) -> str:
    """Resumable upload; returns the new video id. A dropped chunk is resumed from what the server confirms, so a
    lost final response does not create a second video."""
    size = file.stat().st_size
    auth = {"Authorization": f"Bearer {access_token()}"}
    code, headers, body = _http("POST", UPLOAD_URL, auth | {
        "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4"}, json.dumps(meta).encode())
    session = headers.get("Location") if code == 200 else None
    if not session:
        raise PublishError(f"YouTube yüklemeyi başlatmadı: {_error_text(body)}")
    sent, failures, ask = 0, 0, False
    with open(file, "rb") as fh:
        while True:
            proc.check_cancel()
            progress(sent / size, "YouTube'a yükleniyor")
            if ask:                                        # after a failure: how much arrived?
                chunk, rng = b"", f"bytes */{size}"
            else:
                fh.seek(sent)
                chunk = fh.read(CHUNK)
                rng = f"bytes {sent}-{sent + len(chunk) - 1}/{size}"
            try:
                auth = {"Authorization": f"Bearer {access_token()}"}
                code, headers, body = _http("PUT", session, auth | {"Content-Range": rng, "Content-Type": "video/mp4"}, chunk, 600)
            except OSError as e:
                code, headers, body = 0, {}, str(e).encode()
            if code in (200, 201):
                return json.loads(body)["id"]
            if code == 308:
                got = _received(headers)
                failures = 0 if got > sent else failures + (not ask)
                sent, ask = got, False
            elif code == 0 or code >= 500:
                failures, ask = failures + 1, True
            else:
                raise PublishError(f"YouTube yüklemesi reddedildi: {_error_text(body)}")
            if failures > RETRIES:
                raise PublishError(f"Yükleme tamamlanamadı: {_error_text(body)}")
            if ask:
                time.sleep(2 * failures)


def publish_clip(con, cfg: dict, clip_id: int, when: str = "slot", progress=lambda f, t="": None) -> dict:
    """Upload one clip. when: 'slot' (next free daily slot), 'now', or an epoch in seconds."""
    c = store.get_clip(con, clip_id)
    if not c or c["status"] != "done" or not c["file"] or not Path(c["file"]).exists():
        raise PublishError("Klip dosyası yok.")
    if c["yt_id"]:
        raise PublishError("Bu klip zaten YouTube'a yüklendi.")
    if when == "now":
        publish_at = None
    elif when == "slot":
        publish_at = next_slot(parse_times(cfg["upload_times"]), scheduled(con))
    else:
        publish_at = float(when)
        if publish_at < time.time() + 60:
            raise PublishError("Seçilen yayın zamanı geçmiş; yeni bir zaman seç.")
    tags = json.loads(c["tags"]) if c["tags"] else []
    meta = metadata(c["title"] or "", c["description"] or "", tags, publish_at)
    video_id = upload_video(Path(c["file"]), meta, progress)
    store.update_clip(con, clip_id, yt_id=video_id, yt_publish_at=publish_at or time.time())
    return {"id": video_id, "publish_at": publish_at}
