#!/usr/bin/env python3
"""
Minimal UI: paste URL(s), optional album + cover, Add → download and import into Music.

Requires Tk (often missing on Homebrew Python). If import fails, use gui_web.py instead.
"""

from __future__ import annotations

import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ModuleNotFoundError as e:
    if e.name == "_tkinter" or "_tkinter" in str(e):
        sys.stderr.write(
            "Tk is not available in this Python (Homebrew python@3.x often omits _tkinter).\n\n"
            "Options:\n"
            "  1) Run the browser UI (no Tk):  python gui_web.py\n"
            "  2) Install Tk for your Python, e.g.:  brew install python-tk@3.14\n"
            "     then recreate the venv with: /opt/homebrew/opt/python-tk@3.14/bin/python3 -m venv .venv\n"
            "  3) Use the system / python.org installer that includes Tk\n\n"
        )
        sys.exit(1)
    raise

from pathlib import Path

from gui_batch import project_config_path, run_batch


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SoundCloud → Music")
        self.minsize(520, 420)
        self._cover_path: Path | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(7, weight=1)

        ttk.Label(self, text="Links (one per line)").grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 0)
        )
        self.urls = scrolledtext.ScrolledText(self, height=8, wrap="word", font=("Menlo", 11))
        self.urls.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        meta = ttk.Frame(self)
        meta.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        meta.columnconfigure(1, weight=1)

        ttk.Label(meta, text="Album").grid(row=0, column=0, sticky="w", pady=2)
        self.album = ttk.Entry(meta)
        self.album.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(meta, text="Album artist").grid(row=1, column=0, sticky="w", pady=2)
        self.album_artist = ttk.Entry(meta)
        self.album_artist.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=2)

        cov = ttk.Frame(self)
        cov.grid(row=3, column=0, sticky="ew", padx=8, pady=2)
        cov.columnconfigure(1, weight=1)
        ttk.Label(cov, text="Cover art").grid(row=0, column=0, sticky="w")
        self.cover_label = ttk.Label(cov, text="(none)", foreground="gray")
        self.cover_label.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(cov, text="Browse…", command=self._browse_cover).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(cov, text="Clear", command=self._clear_cover).grid(row=0, column=3)

        opts = ttk.Frame(self)
        opts.grid(row=4, column=0, sticky="w", padx=8, pady=4)
        self.expand_playlist = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts,
            text="Expand playlists / SoundCloud sets (one link → many tracks)",
            variable=self.expand_playlist,
        ).pack(anchor="w")

        self.use_auto_add = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts,
            text="Use “Automatically Add to Music” folder instead of AppleScript",
            variable=self.use_auto_add,
        ).pack(anchor="w")

        self.add_btn = ttk.Button(self, text="Add", command=self._on_add)
        self.add_btn.grid(row=5, column=0, sticky="ew", padx=8, pady=8)

        ttk.Label(self, text="Log").grid(row=6, column=0, sticky="w", padx=8)
        self.log = scrolledtext.ScrolledText(self, height=10, state="disabled", font=("Menlo", 10))
        self.log.grid(row=7, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.status = ttk.Label(self, text="Ready.")
        self.status.grid(row=8, column=0, sticky="ew", padx=8, pady=(0, 8))

    def _browse_cover(self) -> None:
        p = filedialog.askopenfilename(
            title="Cover image",
            filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All", "*.*")],
        )
        if p:
            self._cover_path = Path(p)
            self.cover_label.config(text=str(self._cover_path.name), foreground="")

    def _clear_cover(self) -> None:
        self._cover_path = None
        self.cover_label.config(text="(none)", foreground="gray")

    def _append_log(self, line: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.add_btn.config(state="disabled" if busy else "normal")
        self.status.config(text="Working…" if busy else "Ready.")

    def _on_add(self) -> None:
        blob = self.urls.get("1.0", "end")
        cfg_path = project_config_path()
        if not cfg_path.is_file():
            messagebox.showerror("Add", f"Missing config: {cfg_path}")
            return

        album = self.album.get().strip() or None
        albumartist = self.album_artist.get().strip() or None
        cover = self._cover_path if self._cover_path and self._cover_path.is_file() else None
        expand = self.expand_playlist.get()
        use_applescript = not self.use_auto_add.get()

        self._set_busy(True)
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

        def work() -> None:
            try:
                errors, total = run_batch(
                    config_path=cfg_path,
                    url_blob=blob,
                    album=album,
                    albumartist=albumartist,
                    cover_path=cover,
                    expand_playlist=expand,
                    use_applescript=use_applescript,
                    log=lambda m: self.after(0, lambda x=m: self._append_log(x)),
                )
                self.after(0, lambda: self._finish_ok(errors, total))
            except Exception as e:
                self.after(0, lambda: self._done_error(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _finish_ok(self, errors: int = 0, total: int = 0) -> None:
        self._set_busy(False)
        if total == 0:
            self.status.config(text="Ready.")
            messagebox.showwarning("Add", "Nothing was imported — see the log.")
            return
        if errors:
            self.status.config(text=f"Done with {errors} error(s).")
            messagebox.showwarning(
                "Add",
                f"{errors} of {total} track(s) failed. See the log for details.",
            )
        else:
            self.status.config(text="Done.")
            messagebox.showinfo(
                "Add",
                "Finished. Check the Music app if tracks are slow to appear.",
            )

    def _done_error(self, msg: str) -> None:
        self._set_busy(False)
        self.status.config(text="Error.")
        self._append_log(msg)
        messagebox.showerror("Add", msg)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
