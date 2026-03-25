#!/usr/bin/env python3
"""
Download SoundCloud (and other yt-dlp) audio, tag it, add to macOS Music.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import yaml
import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3NoHeaderError, PictureType
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

DEFAULT_AUTO_ADD = (
    Path.home() / "Music" / "Music" / "Media" / "Automatically Add to Music"
)


def normalize_track_url(url: str) -> str:
    """
    Fix pasted URLs from zsh/bash: inside double quotes, \\?, \\&, \\= stay literal
    and break the path so yt-dlp falls back to [generic] and often 404s.
    For SoundCloud, drop query/fragment — only /user/slug is needed.
    """
    u = url.strip()
    u = u.replace("\\?", "?").replace("\\&", "&").replace("\\=", "=")
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    if "soundcloud.com" in host:
        path = parsed.path or ""
        if path.endswith("/"):
            path = path.rstrip("/") or "/"
        return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))
    return u


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def default_auto_add_folder(config: dict) -> Path:
    raw = config.get("auto_add_folder")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_AUTO_ADD


def apply_rules(title: str, rules: list) -> tuple[str, str]:
    """Return (artist, track_title) for tagging."""
    if not rules:
        return "", title.strip()
    for rule in rules:
        pattern = rule.get("pattern")
        if not pattern:
            continue
        m = re.match(pattern, title.strip())
        if not m:
            continue
        ag = int(rule.get("artist_group", 0))
        tg = int(rule.get("title_group", 0))
        max_g = m.lastindex or 0
        artist = m.group(ag).strip() if ag and max_g and ag <= max_g else ""
        t = m.group(tg).strip() if tg and max_g and tg <= max_g else title.strip()
        return artist, t
    return "", title.strip()


def fetch_info_json(url: str) -> dict:
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--no-download",
            "--no-warnings",
            url,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"yt-dlp failed to read URL:\n{err}")
    return json.loads(r.stdout)


def resolve_download_targets(page_url: str, expand_playlist: bool) -> list[dict]:
    """
    Return [{"url", "title_hint", "index"}] with 1-based index within this page_url.
    title_hint may be None; index is for display / local ordering.
    """
    url = normalize_track_url(page_url.strip())
    if not url:
        return []

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
    }
    if expand_playlist:
        opts["extract_flat"] = True
    else:
        opts["noplaylist"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return []

    entries = info.get("entries")
    if entries:
        out: list[dict] = []
        for ent in entries:
            if not ent:
                continue
            eu = ent.get("webpage_url") or ent.get("url")
            if not eu or not str(eu).startswith("http"):
                continue
            eu = normalize_track_url(str(eu))
            tit = (ent.get("title") or "").strip() or None
            out.append(
                {
                    "url": eu,
                    "title_hint": tit,
                    "index": len(out) + 1,
                }
            )
        return out

    u = info.get("webpage_url") or info.get("url") or url
    tit = (info.get("title") or "").strip() or None
    return [
        {
            "url": normalize_track_url(str(u)),
            "title_hint": tit,
            "index": 1,
        }
    ]


def collect_all_targets(
    lines: list[str], expand_playlist: bool
) -> list[dict]:
    """Flatten multiple pasted lines into one ordered list of download targets."""
    all_targets: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        chunk = resolve_download_targets(line, expand_playlist)
        for t in chunk:
            t = dict(t)
            t["global_index"] = len(all_targets) + 1
            all_targets.append(t)
    return all_targets


def download_audio(url: str, out_dir: Path, audio_format: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpl = str(out_dir / "%(id)s.%(ext)s")
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-x",
        "--audio-format",
        audio_format,
        "--no-playlist",
        "-o",
        tmpl,
        "--no-warnings",
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"yt-dlp download failed:\n{err}")
    exts = {".mp3", ".m4a", ".aac", ".opus", ".webm", ".ogg"}
    files = sorted(
        p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() in exts
    )
    if not files:
        raise RuntimeError("No audio file produced; is ffmpeg installed?")
    return files[0]


def _cover_bytes_and_mime(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    if len(data) < 8:
        raise ValueError("Cover image is empty or too small")
    if data[:2] == b"\xff\xd8":
        return data, "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data, "image/png"
    raise ValueError("Cover must be JPEG or PNG")


def embed_cover_mp3(path: Path, image_data: bytes, mime: str) -> None:
    audio = MP3(path)
    if audio.tags is None:
        audio.add_tags()
    # Drop existing APIC frames
    audio.tags.delall("APIC")
    audio.tags.add(
        APIC(
            encoding=3,
            mime=mime,
            type=PictureType.COVER_FRONT,
            desc="Cover",
            data=image_data,
        )
    )
    audio.save()


def embed_cover_m4a(path: Path, image_data: bytes, mime: str) -> None:
    fmt = MP4Cover.FORMAT_JPEG if mime == "image/jpeg" else MP4Cover.FORMAT_PNG
    audio = MP4(path)
    audio["covr"] = [MP4Cover(image_data, imageformat=fmt)]
    audio.save()


def tag_file(
    path: Path,
    artist: str,
    title: str,
    *,
    album: str | None = None,
    albumartist: str | None = None,
    track: int | None = None,
    track_total: int | None = None,
    cover_path: Path | None = None,
) -> None:
    ext = path.suffix.lower()

    if ext == ".mp3":
        try:
            audio = EasyID3(path)
        except ID3NoHeaderError:
            mp3 = MP3(path)
            mp3.add_tags()
            audio = EasyID3(path)
        if artist:
            audio["artist"] = artist
        audio["title"] = title
        if album:
            audio["album"] = album
        if albumartist:
            audio["albumartist"] = albumartist
        if track is not None:
            if track_total is not None:
                audio["tracknumber"] = f"{track}/{track_total}"
            else:
                audio["tracknumber"] = str(track)
        audio.save()
    elif ext == ".m4a":
        audio = MP4(path)
        if artist:
            audio["\xa9ART"] = [artist]
        audio["\xa9nam"] = [title]
        if album:
            audio["\xa9alb"] = [album]
        if albumartist:
            audio["aART"] = [albumartist]
        if track is not None:
            total = track_total if track_total is not None else 0
            audio["trkn"] = [(track, total)]
        audio.save()
    else:
        pass

    if cover_path and cover_path.is_file():
        img, mime = _cover_bytes_and_mime(cover_path)
        if ext == ".mp3":
            embed_cover_mp3(path, img, mime)
        elif ext == ".m4a":
            embed_cover_m4a(path, img, mime)


def import_via_applescript(path: Path) -> None:
    p = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Music" to add POSIX file "{p}"'
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"AppleScript import failed:\n{err}")


def copy_to_auto_add(audio_path: Path, config: dict) -> Path:
    dest_root = default_auto_add_folder(config)
    dest_root.mkdir(parents=True, exist_ok=True)
    final = dest_root / audio_path.name
    if final.exists():
        stem, suf = final.stem, final.suffix
        n = 2
        while final.exists():
            final = dest_root / f"{stem} ({n}){suf}"
            n += 1
    shutil.copy2(audio_path, final)
    return final


def import_audio(path: Path, config: dict, *, force_applescript: bool | None = None) -> None:
    if force_applescript is True:
        import_via_applescript(path)
        return
    if force_applescript is False:
        copy_to_auto_add(path, config)
        return
    method = (config.get("import_method") or "applescript").strip().lower()
    if method == "auto_add_folder":
        copy_to_auto_add(path, config)
    else:
        import_via_applescript(path)


def process_target(
    target: dict,
    *,
    config: dict,
    rules: list,
    audio_format: str,
    album: str | None,
    albumartist: str | None,
    cover_path: Path | None,
    track: int | None,
    track_total: int | None,
    import_dry_run: bool,
    force_applescript: bool | None = None,
) -> tuple[str, str, str]:
    """
    Download one target, tag, import. Returns (artist, title, status_message).
    """
    url = target["url"]
    title_hint = target.get("title_hint")

    info = fetch_info_json(url)
    raw_title = (title_hint or info.get("title") or "Unknown").strip()
    uploader = (info.get("uploader") or info.get("artist") or "").strip()
    artist, title = apply_rules(raw_title, rules)
    if not artist and uploader:
        artist = uploader

    tmp = tempfile.mkdtemp(prefix="sc_to_apple_")
    tmp_path = Path(tmp)
    try:
        audio_path = download_audio(url, tmp_path, audio_format)
        tag_file(
            audio_path,
            artist,
            title,
            album=album,
            albumartist=albumartist,
            track=track,
            track_total=track_total,
            cover_path=cover_path,
        )
        if import_dry_run:
            return artist, title, f"dry-run: {audio_path}"

        import_audio(audio_path, config, force_applescript=force_applescript)
        return artist, title, "ok"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_url_lines(blob: str) -> list[str]:
    return [ln.strip() for ln in blob.splitlines() if ln.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download SoundCloud audio and add to Apple Music (macOS)."
    )
    parser.add_argument("url", nargs="?", help="Track or playlist URL")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent / "config.yaml",
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and tag only; do not import",
    )
    parser.add_argument(
        "--applescript",
        action="store_true",
        help="Import via Music app AppleScript",
    )
    parser.add_argument(
        "--auto-add-folder",
        action="store_true",
        help="Copy to Automatically Add to Music folder instead of AppleScript",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Expand playlists / SoundCloud sets (one URL → many tracks)",
    )
    parser.add_argument("--album", help="Album name for all tracks in this run")
    parser.add_argument("--album-artist", dest="album_artist", help="Album artist")
    parser.add_argument("--cover", type=Path, help="JPEG/PNG cover art file")
    args = parser.parse_args()

    if not args.url:
        parser.error("url is required")

    config_path = args.config
    if not config_path.is_file():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1

    config = load_config(config_path)
    audio_format = (config.get("audio_format") or "m4a").lower()
    rules = config.get("rules") or []

    force_script: bool | None = None
    if args.applescript:
        force_script = True
    elif args.auto_add_folder:
        force_script = False

    lines = [args.url]
    targets = collect_all_targets(lines, args.playlist)
    if not targets:
        print("No tracks resolved from URL.", file=sys.stderr)
        return 1

    total = len(targets)
    cover_path = args.cover if args.cover and args.cover.is_file() else None

    for t in targets:
        tr = t.get("global_index", t.get("index", 1))
        try:
            artist, title, msg = process_target(
                t,
                config=config,
                rules=rules,
                audio_format=audio_format,
                album=args.album,
                albumartist=args.album_artist,
                cover_path=cover_path,
                track=tr if total > 1 or args.album else None,
                track_total=total if total > 1 or args.album else None,
                import_dry_run=args.dry_run,
                force_applescript=force_script,
            )
            print(f"{msg}: {title}" + (f" — {artist}" if artist else ""))
        except Exception as e:
            print(f"Error ({t.get('url')}): {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
