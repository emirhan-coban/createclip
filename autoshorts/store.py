"""SQLite state: sources being watched, videos seen and clips. One file: data/autoshorts.db.

Clip life cycle:  new -> done (rendered and saved to the output folder), or failed."""
import json
import sqlite3
import time
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, url TEXT UNIQUE, name TEXT, added REAL, backfill INTEGER);
CREATE TABLE IF NOT EXISTS videos (url TEXT PRIMARY KEY, source_id INTEGER, title TEXT, duration REAL,
  status TEXT, error TEXT, added REAL);
CREATE TABLE IF NOT EXISTS edits (clip_id INTEGER PRIMARY KEY, project TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, url TEXT, status TEXT, error TEXT,
  started REAL, run_started REAL, ended REAL);
CREATE TABLE IF NOT EXISTS clips (id INTEGER PRIMARY KEY, video_url TEXT, start REAL, end REAL, score REAL,
  engine TEXT, file TEXT, title TEXT, description TEXT, tags TEXT, status TEXT, error TEXT, created REAL,
  UNIQUE(video_url, start));
"""


def connect(db: Path | None = None) -> sqlite3.Connection:
    db = db or (config.data_dir() / "autoshorts.db")
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(clips)")}
    for col, typ in (("src_file", "TEXT"), ("src_start", "REAL"), ("src_end", "REAL"),      # editor source footage
                     ("key_start", "REAL"),           # the finder's original start: the dedupe key (`start` may be snapped to a sentence)
                     ("yt_id", "TEXT"), ("yt_publish_at", "REAL"),                   # YouTube upload, publish time (epoch)
                     ("yt_streamer", "TEXT")):                                       # for the per-streamer comparison
        if col not in have:
            con.execute(f"ALTER TABLE clips ADD COLUMN {col} {typ}")
    vhave = {r[1] for r in con.execute("PRAGMA table_info(videos)")}
    if "live_until" not in vhave:                         # seconds of the broadcast already available when it was processed live
        con.execute("ALTER TABLE videos ADD COLUMN live_until REAL")
    if "fp" not in vhave:                                 # platform|channel|title: links with the same value are one broadcast
        con.execute("ALTER TABLE videos ADD COLUMN fp TEXT")
    con.commit()
    return con


def rows(con, sql: str, *a) -> list[dict]:
    return [dict(r) for r in con.execute(sql, a).fetchall()]


# ---- sources / videos
def add_source(con, url: str, name: str = "", backfill: int = 3) -> bool:
    cur = con.execute("INSERT OR IGNORE INTO sources(url, name, added, backfill) VALUES (?,?,?,?)",
                      (url, name, time.time(), backfill))
    con.commit()
    return cur.rowcount == 1


def remove_source(con, url: str):
    con.execute("DELETE FROM sources WHERE url=?", (url,))
    con.commit()


def sources(con) -> list[dict]:
    return rows(con, "SELECT * FROM sources ORDER BY id")


def known_video(con, url: str) -> bool:
    return con.execute("SELECT 1 FROM videos WHERE url=?", (url,)).fetchone() is not None


def upsert_video(con, url: str, **f):
    if not known_video(con, url):
        con.execute("INSERT INTO videos(url, status, added) VALUES (?,?,?)", (url, f.pop("status", "pending"), time.time()))
    for k, v in f.items():
        con.execute(f"UPDATE videos SET {k}=? WHERE url=?", (v, url))
    con.commit()


def pending_videos(con) -> list[dict]:
    return rows(con, "SELECT * FROM videos WHERE status='pending' ORDER BY added")


# ---- clips
NEAR = 15.0     # a new candidate this close to an existing clip's start is the same moment (peaks shift as chat data grows)


def fingerprint(platform: str, channel: str, title: str) -> str:
    """Identity of a broadcast across links (a live URL and its finished VOD, a re-link of the same video). Empty = unknown."""
    if not (platform and channel and title):
        return ""
    return f"{platform}|{channel}|{' '.join(title.lower().split())}"


def twins(con, video_url: str) -> list[str]:
    """This URL plus every other URL of the same broadcast (same fingerprint): their clips count as one pool."""
    r = rows(con, "SELECT fp FROM videos WHERE url=?", video_url)
    fp = r[0]["fp"] if r else None
    if not fp:
        return [video_url]
    return [video_url] + [x["url"] for x in rows(con, "SELECT url FROM videos WHERE fp=? AND url!=?", fp, video_url)]


def _marks(urls: list[str]) -> str:
    return ",".join("?" * len(urls))


def add_clip(con, video_url: str, start: float, end: float, score: float, engine: str) -> int | None:
    if find_clip(con, video_url, start) or find_near_clip(con, video_url, start):
        return None
    cur = con.execute("INSERT OR IGNORE INTO clips(video_url, start, end, score, engine, status, created, key_start) "
                      "VALUES (?,?,?,?,?,'new',?,?)", (video_url, round(start, 2), round(end, 2), score, engine, time.time(), round(start, 2)))
    con.commit()
    return cur.lastrowid if cur.rowcount else None


def count_clips(con, video_url: str) -> int:
    """Clips of this broadcast (any of its links) that exist, failed ones excluded: the moments a new run has to skip."""
    u = twins(con, video_url)
    return int(rows(con, f"SELECT COUNT(*) AS c FROM clips WHERE video_url IN ({_marks(u)}) AND status!='failed'", *u)[0]["c"])


def find_clip(con, video_url: str, start: float) -> dict | None:
    u = twins(con, video_url)
    r = rows(con, f"SELECT * FROM clips WHERE video_url IN ({_marks(u)}) AND COALESCE(key_start, start)=?", *u, round(start, 2))
    return r[0] if r else None


def find_near_clip(con, video_url: str, start: float, tol: float = NEAR) -> dict | None:
    u = twins(con, video_url)
    r = rows(con, f"SELECT * FROM clips WHERE video_url IN ({_marks(u)}) AND status!='failed' "
                  "AND ABS(COALESCE(key_start, start)-?)<=? ORDER BY ABS(COALESCE(key_start, start)-?) LIMIT 1",
             *u, start, tol, start)
    return r[0] if r else None


def resume_point(con, video_url: str) -> float:
    """Where a video processed while it was live left off: the end of its last clip (0 = no such history)."""
    v = rows(con, "SELECT live_until FROM videos WHERE url=?", video_url)
    if not v or not v[0]["live_until"]:
        return 0.0
    r = rows(con, "SELECT MAX(end) AS e FROM clips WHERE video_url=? AND status!='failed'", video_url)
    return float(r[0]["e"] or 0.0)


def update_clip(con, clip_id: int, **f):
    if "tags" in f and not isinstance(f["tags"], str):
        f["tags"] = json.dumps(f["tags"], ensure_ascii=False)
    for k, v in f.items():
        con.execute(f"UPDATE clips SET {k}=? WHERE id=?", (v, clip_id))
    con.commit()


def clips(con, status: str | None = None) -> list[dict]:
    q = "SELECT c.*, v.title AS video_title, v.fp AS video_fp FROM clips c LEFT JOIN videos v ON v.url=c.video_url"
    if status:
        return rows(con, q + " WHERE c.status=? ORDER BY c.score DESC", status)
    return rows(con, q + " ORDER BY c.id")


def get_clip(con, clip_id: int) -> dict | None:
    r = rows(con, "SELECT c.*, v.title AS video_title, v.fp AS video_fp FROM clips c LEFT JOIN videos v ON v.url=c.video_url "
                  "WHERE c.id=?", clip_id)
    return r[0] if r else None


# ---- job history (the live job objects are in memory; this keeps the list across restarts)
def add_job(con, kind: str, url: str | None, started: float) -> int:
    cur = con.execute("INSERT INTO jobs(kind, url, status, started) VALUES (?,?,'queued',?)", (kind, url, started))
    con.commit()
    return cur.lastrowid


def update_job(con, job_id: int, **f):
    for k, v in f.items():
        con.execute(f"UPDATE jobs SET {k}=? WHERE id=?", (v, job_id))
    con.commit()


def recent_jobs(con, limit: int = 20) -> list[dict]:
    return rows(con, "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", limit)


# ---- editor: source footage and the saved edit project of a clip
def set_source(con, clip_id: int, file: str | None, start: float | None, end: float | None):
    update_clip(con, clip_id, src_file=file, src_start=start, src_end=end)


def get_project(con, clip_id: int) -> dict | None:
    r = rows(con, "SELECT project FROM edits WHERE clip_id=?", clip_id)
    return json.loads(r[0]["project"]) if r else None


def delete_project(con, clip_id: int):
    con.execute("DELETE FROM edits WHERE clip_id=?", (clip_id,))
    con.commit()


def save_project(con, clip_id: int, project: dict):
    con.execute("INSERT OR REPLACE INTO edits(clip_id, project, updated) VALUES (?,?,?)",
                (clip_id, json.dumps(project, ensure_ascii=False), time.time()))
    con.commit()
