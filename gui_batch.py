"""Shared batch logic for tk and web GUIs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sc_to_apple import collect_all_targets, load_config, parse_url_lines, process_target


def project_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.yaml"


def run_batch(
    *,
    config_path: Path,
    url_blob: str,
    album: str | None,
    albumartist: str | None,
    cover_path: Path | None,
    expand_playlist: bool,
    use_applescript: bool,
    log: Callable[[str], None],
) -> tuple[int, int]:
    """
    Process pasted URLs. log() is called from the worker thread.
    Returns (error_count, total_tracks).
    """
    lines = parse_url_lines(url_blob)
    if not lines:
        log("No URLs pasted.")
        return (1, 0)

    if not config_path.is_file():
        log(f"Missing config: {config_path}")
        return (1, 0)

    config = load_config(config_path)
    rules = config.get("rules") or []
    audio_format = (config.get("audio_format") or "m4a").lower()
    force_applescript = True if use_applescript else False

    targets = collect_all_targets(lines, expand_playlist)
    if not targets:
        log('No tracks resolved — check URLs or enable “Expand playlists”.')
        return (1, 0)

    total = len(targets)
    errors = 0
    log(f"Resolved {total} track(s).")

    for t in targets:
        tr = t.get("global_index", t.get("index", 1))
        try:
            artist, title, _msg = process_target(
                t,
                config=config,
                rules=rules,
                audio_format=audio_format,
                album=album,
                albumartist=albumartist,
                cover_path=cover_path,
                track=tr if total > 1 or album else None,
                track_total=total if total > 1 or album else None,
                import_dry_run=False,
                force_applescript=force_applescript,
            )
            line = f"OK: {title}"
            if artist:
                line += f" — {artist}"
            log(line)
        except Exception as e:
            errors += 1
            u = t.get("url", "")
            log(f"Error: {u}\n  {e}")

    return (errors, total)
