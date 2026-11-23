# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
`autoshorts`: video/channel link -> best moments -> 9:16 clips saved to `ready/<date>/` with a `.txt` (title, description) and `.jpg`. No posting: uploading is manual by design (a Postiz auto-poster was built and dropped at the user's request). Python >=3.10 (FastAPI + uvicorn; Pillow and mlx-whisper for captions via `.[captions]`); external tools: `ffmpeg`, `ffprobe`, `yt-dlp`. User-facing strings are mostly Turkish. The earlier createclip app (web editor, Turkish captions, face layout) lives only in git history (last commit before the rewrite: `88e08c3`); `sources/` and `captions.py` were ported from it.

## Commands
```bash
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest -q                    # tests/ (no network)
./.venv/bin/python -m pytest tests/test_all.py::test_export_saves_video_and_text -q
./.venv/bin/autoshorts doctor
./.venv/bin/autoshorts serve --open      # web UI at http://127.0.0.1:8765 (needs . and `cd web && npm run build`)
./.venv/bin/autoshorts --root /tmp/x run "<url>" --at 0:20:00-0:20:40   # real e2e without chat analysis
```
`--root` selects the working folder holding optional `autoshorts.json` and `data/` (SQLite db, caches, clips) plus the output folder (`ready/`); default is the current directory. Gitignored.

## Architecture (`autoshorts/`)
- `download.py` stage 1 (yt-dlp): `info`, `fetch_range` (stream-copy of a time range, retries, `has_video` check), `fetch_audio`, `list_videos`. **429 / bot-check output raises `BlockedError`**, which pipeline code must propagate (stop, leave video `pending`) instead of retrying.
- `finder.py` stage 2: engines chat / audio / transcript (ClipsAI, optional, untested here) / auto. Chat and peak maths live in `sources/` (`kick.py` resumable chat crawler with rate limiter, `youtube.py` chat replay, `peaks.py` z-score peaks incl. `skip_start`); ported from the earlier app apart from imports, so keep their measured constants (Kick ~1.5 req/s).
- `render.py` stage 3: exact trim + blurred-background 9:16 + loudnorm. `meta.py` rule-based title/description. `export.py` copies the result into the output folder.
- `api.py` (FastAPI, `serve` default) serves `web/dist` + JSON API + SSE job events (`/api/jobs/<id>/events`, replayable via `after`/Last-Event-ID) + range media; `jobs.py` is the single-worker job runner with cancel and a per-job event log. `pipeline.process_video` / `finder.find` emit structured events (`info`, `chat`, `activity` (partial then final), `moments`, `clip`, `done`, `end`) next to the `progress(frac, text)` callback; the React home page draws them. Keep event payloads backward compatible with `web/src/lib/useJob.ts`.
- `web/` React 19 + Vite + TypeScript + Tailwind v4 + motion (`npm run build` type-checks first). Design tokens live in `web/src/index.css` (paper/ink/lime, Inter Variable). Pages: `Home` (paste link -> live timeline scenes), `Panel` (overview, clips, channels, settings).
- `editor.py` + `web/src/pages/Editor.tsx`: clip editor. A clip keeps its padded source footage (`data/clips/source/<id>.mp4`, `src_start/src_end` columns; `source_pad` seconds each side). The edit is one JSON `project` (trim in source-file seconds, layout mode `blur|crop|stack` with window cells `{cx,cy,zoom}`, audio) stored in table `edits`. **Preview and export share geometry**: `editor.cell_rect/build_graph` (ffmpeg) mirror `web/src/lib/layout.ts` (`cellRect/plan`, CSS); change both together and keep `test_layout_geometry_matches_between_modes` green. Export is a `jobs` kind (`export`), progress via ffmpeg `-progress`; `source` jobs fetch footage for clips that predate the editor. Timeline assets (`strip.jpg` sprite, `wave.json`) are cached in `data/clips/editor/<id>/`.
- **Captions** (`captions.py`, `transcribe.py`, `web/src/lib/captions.ts`, `CaptionLayer`, `CaptionPanel`): word times (source seconds) live in `project.captions`; ffmpeg here has no libass/drawtext, so the exporter draws caption states with Pillow and overlays a PNG concat list in the same single ffmpeg pass as the layout (`render_project`). The browser draws the same states on a canvas using the same font files (`/fonts/*.ttf`, `KMontserrat` etc.) and the same chunking/timeline maths; change `captions.py` and `captions.ts` together. Export keeps only words inside the cut on the clip's own timeline, and the preview does the same. Transcription (`mlx-whisper`, job kind `transcribe`) is cached per clip in `data/clips/editor/<id>/words.json`.
- **Text layers** (`texts.py`, `web/src/lib/texts.ts`, `TextLayer`, `TextPanel`): `project.texts[]`, times in seconds from the CLIP's start (not source seconds, unlike caption words). Pillow renders one PNG per layer; `render_project` chains `overlay=...:enable='between(t,a,b)'` after the captions overlay, ending in `[v]`. Wrapping, block geometry, baselines and the emoji advance are mirrored in `texts.ts`; change both together. Emoji use Apple Color Emoji through Pillow (no raqm, so no ZWJ sequences).
- **Source timestamps:** stream-copied sections keep the original stream's timestamps (e.g. start 1.17 s); browsers play from that offset while `ffmpeg -ss` counts from the first frame, so `editor.source_info` remuxes such files to start at 0 (`normalize_source`). Never skip this when adding another way to obtain a source file.
- `store.py` SQLite (sources, videos, clips; clip status `new -> done | failed`); `pipeline.py` ties it together (`process_video`, `make_clip`, `scan_sources`, `watch_once`); `cli.py` is argparse only.
- `proc.run` runs every subprocess in its own process group and kills the group on timeout (a stalled yt-dlp child ffmpeg otherwise hangs the caller).
