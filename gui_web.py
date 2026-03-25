#!/usr/bin/env python3
"""
Browser UI (stdlib only): no Tk required — works with Homebrew Python that lacks _tkinter.
Opens http://127.0.0.1:<port>/ in your default browser.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from gui_batch import project_config_path, run_batch

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SoundCloud → Music</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 44rem; margin: 1.5rem auto; padding: 0 1rem; }
  label { display: block; margin-top: 0.75rem; font-weight: 600; }
  textarea, input[type="text"] { width: 100%; box-sizing: border-box; margin-top: 0.25rem; }
  textarea { min-height: 9rem; font-family: ui-monospace, monospace; font-size: 0.9rem; }
  .row { margin-top: 0.5rem; }
  pre#log { background: #f4f4f5; padding: 0.75rem; overflow: auto; max-height: 16rem; font-size: 0.8rem; }
  button { margin-top: 1rem; padding: 0.5rem 1rem; font-size: 1rem; }
  .hint { color: #555; font-size: 0.85rem; margin-top: 0.25rem; }
</style>
</head>
<body>
<h1>SoundCloud → Music</h1>
<p class="hint">Paste one URL per line. Cover: full path to a JPEG or PNG on this Mac.</p>

<label for="urls">Links</label>
<textarea id="urls" placeholder="https://soundcloud.com/…"></textarea>

<label for="album">Album (optional)</label>
<input type="text" id="album"/>

<label for="albumartist">Album artist (optional)</label>
<input type="text" id="albumartist"/>

<label for="cover">Cover art path (optional)</label>
<input type="text" id="cover" placeholder="/Users/you/Pictures/cover.jpg"/>

<div class="row">
  <label><input type="checkbox" id="expand"/> Expand playlists / SoundCloud sets</label>
</div>
<div class="row">
  <label><input type="checkbox" id="autoadd"/> Use “Automatically Add to Music” folder (not AppleScript)</label>
</div>

<button type="button" id="go" onclick="startAdd()">Add</button>
<span id="busy" style="margin-left:1rem;color:#666;display:none">Working…</span>

<label for="log" style="margin-top:1.5rem">Log</label>
<pre id="log"></pre>

<script>
let pollTimer = null;

function setBusy(b) {
  document.getElementById('go').disabled = b;
  document.getElementById('busy').style.display = b ? 'inline' : 'none';
}

async function startAdd() {
  const body = {
    urls: document.getElementById('urls').value,
    album: document.getElementById('album').value.trim(),
    albumartist: document.getElementById('albumartist').value.trim(),
    cover: document.getElementById('cover').value.trim(),
    expand: document.getElementById('expand').checked,
    use_applescript: !document.getElementById('autoadd').checked
  };
  document.getElementById('log').textContent = '';
  setBusy(true);
  const r = await fetch('/api/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const j = await r.json();
  if (!j.ok) {
    document.getElementById('log').textContent = j.error || 'Failed to start';
    setBusy(false);
    return;
  }
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollStatus, 400);
  pollStatus();
}

async function pollStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  document.getElementById('log').textContent = (s.log || []).join('\\n');
    if (!s.running) {
    clearInterval(pollTimer);
    pollTimer = null;
    setBusy(false);
    if (s.total === 0) {
      alert('Nothing was imported — see the log.');
    } else if (s.errors > 0) {
      alert(s.errors + ' of ' + s.total + ' track(s) failed — see log.');
    } else {
      alert('Finished. Check the Music app if tracks are slow to appear.');
    }
  }
}
</script>
</body>
</html>
"""


class State:
    lock = threading.Lock()
    running = False
    log_lines: list[str] = []
    errors = 0
    total = 0


def _reset_state() -> None:
    with State.lock:
        State.running = False
        State.log_lines = []
        State.errors = 0
        State.total = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path == "/api/status":
            with State.lock:
                payload = {
                    "running": State.running,
                    "log": list(State.log_lines),
                    "errors": State.errors,
                    "total": State.total,
                }
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return
        self._send(404, b"Not found")

    def do_POST(self) -> None:
        if self.path != "/api/start":
            self._send(404, b"Not found")
            return
        ln = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(ln).decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send(200, json.dumps({"ok": False, "error": "Bad JSON"}).encode(), "application/json")
            return

        with State.lock:
            if State.running:
                self._send(
                    200,
                    json.dumps({"ok": False, "error": "Already running"}).encode(),
                    "application/json",
                )
                return

        urls = (data.get("urls") or "").strip()
        album = (data.get("album") or "").strip() or None
        albumartist = (data.get("albumartist") or "").strip() or None
        cover_s = (data.get("cover") or "").strip()
        cover_path = Path(cover_s).expanduser() if cover_s else None
        cover_missing_msg: str | None = None
        if cover_s:
            if not cover_path.is_file():
                cover_missing_msg = f"Cover file not found (skipping): {cover_s}"
                cover_path = None
        expand = bool(data.get("expand"))
        use_applescript = data.get("use_applescript", True) is not False

        cfg = project_config_path()

        def log_line(msg: str) -> None:
            with State.lock:
                State.log_lines.append(msg)

        def work() -> None:
            err, tot = 1, 0
            with State.lock:
                State.running = True
                State.log_lines = []
                State.errors = 0
                State.total = 0
            try:
                if cover_missing_msg:
                    log_line(cover_missing_msg)
                err, tot = run_batch(
                    config_path=cfg,
                    url_blob=urls,
                    album=album,
                    albumartist=albumartist,
                    cover_path=cover_path,
                    expand_playlist=expand,
                    use_applescript=use_applescript,
                    log=log_line,
                )
            except Exception as e:
                log_line(f"Fatal: {e}")
                err, tot = 1, 0
            finally:
                with State.lock:
                    State.errors = err
                    State.total = tot
                    State.running = False

        threading.Thread(target=work, daemon=True).start()
        self._send(200, json.dumps({"ok": True}).encode(), "application/json")


def main() -> None:
    _reset_state()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"Open {url} in your browser (launching now). Ctrl+C to stop.")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(url)
    try:
        input("Server running — press Enter to stop…\n")
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        print("Stopped.")


if __name__ == "__main__":
    main()
