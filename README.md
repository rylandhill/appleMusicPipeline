# SoundCloud → Apple Music (local)

Download audio with **yt-dlp**, tag it (optional album, cover art, track numbers), and add it to **Music** on your Mac (AppleScript by default, or the auto-add folder).

## One-time setup

1. **Python 3.10+** (typical on macOS).

2. **FFmpeg** (required for audio extraction):

   ```bash
   brew install ffmpeg
   ```

3. **Venv + dependencies** (from this folder):

   ```bash
   cd /path/to/appleMusicPipeline
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   (`pip install -r requirements.txt` — the `-r` flag is required.)

4. **Tk on Homebrew Python (optional)**  
   Apple’s framework build and **python.org** installers include Tk. **Homebrew `python@3.x` often does not** — you’ll see `ModuleNotFoundError: No module named '_tkinter'` when running `gui.py`.  
   **Easiest fix:** use the browser UI instead (no Tk):

   ```bash
   python gui_web.py
   ```

   **Or** install Tk for your Python version and recreate the venv, for example:

   ```bash
   brew install python-tk@3.14
   /opt/homebrew/opt/python-tk@3.14/bin/python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   (Adjust the version if `brew search python-tk` shows a different `@3.xx`.)

5. **Music.app**

   - Sign in with your Apple ID.
   - For **iPhone / iPad / other Macs**: **Music → Settings → General** → enable **Sync Library** (per Apple’s requirements for your account).

6. **Automation (AppleScript path)**  
   The GUI and default CLI behavior import via AppleScript. The first time, macOS may ask you to allow **Terminal** (or **Python**) to control **Music**.

## Simple UI

**Browser (no Tk — works with Homebrew Python):**

```bash
source .venv/bin/activate
python gui_web.py
```

A tab opens at `http://127.0.0.1:…/`; keep the terminal open and press Enter there when you’re done to stop the server.

**Desktop (needs Tk):**

```bash
python gui.py
```

- Paste one or more URLs (one per line).
- Optional **Album** and **Album artist** so every track in the batch gets the same album metadata and sequential **track numbers** (when there is more than one track, or when Album is filled).
- Optional **Cover art** (JPEG or PNG) embedded in every file in that run.
- **Expand playlists / SoundCloud sets**: one playlist or set URL is turned into many tracks (uses yt-dlp’s flat playlist extraction).
- Leave **Automatically Add to Music** unchecked to keep using AppleScript (matches what worked on your machine).

## Command line

Single track:

```bash
python sc_to_apple.py "https://soundcloud.com/artist/track-name"
```

Paste hygiene: the script fixes zsh-style `\?` / `\&` in URLs and strips SoundCloud `utm_` query params.

| Flag | Meaning |
|------|--------|
| `--playlist` | Expand a playlist / set URL into many downloads. |
| `--album "Name"` | Set album tag; with multiple tracks, sets track `1/n … n/n`. |
| `--album-artist "Name"` | Album artist (`aART` / ID3). |
| `--cover /path/to.jpg` | Embed JPEG/PNG cover on every track in the run. |
| `--applescript` | Import via Music (default if `import_method` is `applescript`). |
| `--auto-add-folder` | Copy into **Automatically Add to Music** instead. |
| `--dry-run` | Download + tag only; no import. |
| `--config /path/to/config.yaml` | Alternate config. |

**[config.yaml](config.yaml)**

- `audio_format`: `m4a` or `mp3`.
- `import_method`: `applescript` (default) or `auto_add_folder` (used when CLI does not force a method).
- `rules`: regex for splitting **Artist** / **Title** from the track title (see file comments).
- `auto_add_folder`: override if your Music media folder is non-standard.

## How files get into your library

There is no personal API to “upload” arbitrary files. This project uses:

1. **AppleScript** — `tell application "Music" to add POSIX file "…"` (default in GUI and in `config.yaml`).
2. **Auto-add folder** — copy to `~/Music/Music/Media/Automatically Add to Music` (optional).

Then **Sync Library** handles the cloud if you use it.

## Legal note

Only download content you’re allowed to use. Respect SoundCloud and rights holders.
