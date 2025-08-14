# karaoke_lyrics_sync_tool.py
# Single-file Karaoke Lyrics Sync Tool
# Fitur:
# - Load Audio (.mp3/.wav)
# - Load Lirik (.txt) baris-per-baris
# - Play / Pause / Stop
# - Next Line / Back Line / Undo Timestamp
# - Simpan .lrc
# - Hotkeys: Space=Play/Pause, Enter=Next, Backspace=Back, Ctrl+S=Save

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import timedelta

# --- Audio via pygame ---
try:
    import pygame
except ImportError:
    raise SystemExit("Module 'pygame' belum terpasang. Install dengan: pip install pygame")

APP_TITLE = "Karaoke Lyrics Sync Tool (Single File)"
SUPPORTED_AUDIO = (".mp3", ".wav")

def ms_to_lrc(ms: int) -> str:
    if ms < 0:
        ms = 0
    td = timedelta(milliseconds=ms)
    total_seconds = int(td.total_seconds())
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    hundredths = int((ms % 1000) / 10)  # .xx untuk LRC
    return f"[{minutes:02}:{seconds:02}.{hundredths:02}]"

class AudioPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.loaded_path = None
        self._is_paused = False

    def load(self, path: str):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_AUDIO:
            raise ValueError(f"Format tidak didukung: {ext}")
        pygame.mixer.music.load(path)
        self.loaded_path = path
        self._is_paused = False

    def play(self):
        if not self.loaded_path:
            return
        # Jika sudah stop/selesai, mulai ulang dari awal
        pygame.mixer.music.play()
        self._is_paused = False

    def pause_toggle(self):
        if not self.loaded_path:
            return
        if self._is_paused:
            pygame.mixer.music.unpause()
            self._is_paused = False
        else:
            pygame.mixer.music.pause()
            self._is_paused = True

    def stop(self):
        pygame.mixer.music.stop()
        self._is_paused = False

    def is_playing(self) -> bool:
        # get_busy True saat play atau pause; gunakan flag internal untuk info pause
        return pygame.mixer.music.get_busy()

    def is_paused(self) -> bool:
        return self._is_paused

    def get_pos_ms(self) -> int:
        pos = pygame.mixer.music.get_pos()  # ms sejak music.play() terakhir, berhenti saat pause
        if pos is None or pos < 0:
            return 0
        return int(pos)

class KaraokeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(760, 420)
        try:
            # nicer scaling for high DPI
            self.tk.call('tk', 'scaling', 1.25)
        except tk.TclError:
            pass

        # State
        self.audio = AudioPlayer()
        self.audio_path = None
        self.lyrics_path = None
        self.lyrics: list[str] = []
        self.timestamps: list[str] = []  # string LRC "[mm:ss.xx]"
        self.current_index = 0

        # UI
        self._build_ui()
        self._bind_hotkeys()
        self._tick()  # start status updater

    # ---------- UI ----------
    def _build_ui(self):
        topbar = ttk.Frame(self, padding=8)
        topbar.pack(side=tk.TOP, fill=tk.X)

        self.btn_load_audio = ttk.Button(topbar, text="Load Audio", command=self.on_load_audio)
        self.btn_load_lyrics = ttk.Button(topbar, text="Load Lyrics", command=self.on_load_lyrics)
        self.btn_play = ttk.Button(topbar, text="Play", command=self.on_play)
        self.btn_pause = ttk.Button(topbar, text="Pause/Unpause", command=self.on_pause_toggle)
        self.btn_stop = ttk.Button(topbar, text="Stop", command=self.on_stop)

        for w in (self.btn_load_audio, self.btn_load_lyrics, self.btn_play, self.btn_pause, self.btn_stop):
            w.pack(side=tk.LEFT, padx=(0, 6))

        # Current & Next line
        mid = ttk.Frame(self, padding=8)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.lbl_now_title = ttk.Label(mid, text="Lirik Sekarang:")
        self.lbl_now_title.grid(row=0, column=0, sticky="w")
        self.txt_now = tk.Text(mid, height=3, wrap="word")
        self.txt_now.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(2, 8))

        self.lbl_next_title = ttk.Label(mid, text="Baris Berikut:")
        self.lbl_next_title.grid(row=2, column=0, sticky="w")
        self.txt_next = tk.Text(mid, height=3, wrap="word")
        self.txt_next.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(2, 8))

        # Controls
        controls = ttk.Frame(self, padding=8)
        controls.pack(side=tk.TOP, fill=tk.X)

        self.btn_prev = ttk.Button(controls, text="Back Line (←)", command=self.on_back_line)
        self.btn_next = ttk.Button(controls, text="Next Line (Enter)", command=self.on_next_line)
        self.btn_undo = ttk.Button(controls, text="Undo Timestamp", command=self.on_undo)
        self.btn_save = ttk.Button(controls, text="Save LRC (Ctrl+S)", command=self.on_save_lrc)

        for w in (self.btn_prev, self.btn_next, self.btn_undo, self.btn_save):
            w.pack(side=tk.LEFT, padx=(0, 6))

        # Progress + list preview
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))

        self.lbl_status = ttk.Label(bottom, text="Status: -")
        self.lbl_status.pack(side=tk.LEFT)

        # Listbox preview on right
        right_frame = ttk.Frame(self, padding=(0, 8, 8, 8))
        right_frame.place(relx=1.0, rely=0.0, anchor="ne", relheight=1.0, width=320)

        ttk.Label(right_frame, text="Preview Sinkronisasi").pack(anchor="w")
        self.list_preview = tk.Listbox(right_frame, height=18)
        self.list_preview.pack(fill=tk.BOTH, expand=True)

        # Make mid resizable
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_rowconfigure(1, weight=1)
        mid.grid_rowconfigure(3, weight=1)

    def _bind_hotkeys(self):
        self.bind("<space>", lambda e: self.on_pause_toggle())
        self.bind("<Return>", lambda e: self.on_next_line())
        self.bind("<BackSpace>", lambda e: self.on_back_line())
        self.bind("<Control-s>", lambda e: self.on_save_lrc())

    # ---------- Helpers ----------
    def _update_text_views(self):
        # Now line
        now = self.lyrics[self.current_index] if (0 <= self.current_index < len(self.lyrics)) else ""
        nxt = self.lyrics[self.current_index + 1] if (0 <= self.current_index + 1 < len(self.lyrics)) else ""

        for widget, text in ((self.txt_now, now), (self.txt_next, nxt)):
            widget.config(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, text.strip())
            widget.config(state="disabled")

    def _update_preview_list(self):
        self.list_preview.delete(0, tk.END)
        for i, lyric in enumerate(self.lyrics):
            tag = self.timestamps[i] if i < len(self.timestamps) else "[-]"
            self.list_preview.insert(tk.END, f"{tag} {lyric.strip()}")

        if 0 <= self.current_index < self.list_preview.size():
            self.list_preview.selection_clear(0, tk.END)
            self.list_preview.selection_set(self.current_index)
            self.list_preview.see(self.current_index)

    def _update_progress(self):
        total = max(1, len(self.lyrics))
        self.progress["maximum"] = total
        self.progress["value"] = min(len(self.timestamps), total)

    def _tick(self):
        # update status every 100ms
        pos_ms = self.audio.get_pos_ms() if self.audio.is_playing() else 0
        pos_str = ms_to_lrc(pos_ms).strip("[]")
        status = f"Status: {pos_str} | Baris: {min(len(self.timestamps), len(self.lyrics))}/{len(self.lyrics)}"
        if self.audio_path:
            status += f" | Audio: {os.path.basename(self.audio_path)}"
        if self.lyrics_path:
            status += f" | Lirik: {os.path.basename(self.lyrics_path)}"
        if self.audio.is_paused():
            status += " | PAUSED"
        self.lbl_status.config(text=status)
        self.after(100, self._tick)

    def _ensure_ready(self) -> bool:
        if not self.audio_path:
            messagebox.showwarning("Perlu Audio", "Silakan Load Audio terlebih dahulu.")
            return False
        if not self.lyrics:
            messagebox.showwarning("Perlu Lirik", "Silakan Load Lyrics (.txt) terlebih dahulu.")
            return False
        return True

    # ---------- Actions ----------
    def on_load_audio(self):
        path = filedialog.askopenfilename(
            title="Pilih File Audio",
            filetypes=[("Audio", "*.mp3 *.wav"), ("All Files", "*.*")]
        )
        if not path:
            return
        try:
            self.audio.load(path)
            self.audio_path = path
            self.audio.stop()  # reset
            messagebox.showinfo("Audio Loaded", os.path.basename(path))
        except Exception as e:
            messagebox.showerror("Gagal Load Audio", str(e))

    def on_load_lyrics(self):
        path = filedialog.askopenfilename(
            title="Pilih File Lyrics (.txt)",
            filetypes=[("Text", "*.txt"), ("All Files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
            # bersihkan: hapus baris kosong di awal/akhir dan normalisasi
            cleaned = [ln.strip() for ln in lines if ln.strip() != ""]
            if not cleaned:
                raise ValueError("File lirik kosong.")
            self.lyrics_path = path
            self.lyrics = cleaned
            self.timestamps = []
            self.current_index = 0
            self._update_text_views()
            self._update_preview_list()
            self._update_progress()
            messagebox.showinfo("Lyrics Loaded", f"{len(self.lyrics)} baris lirik dibaca.")
        except Exception as e:
            messagebox.showerror("Gagal Load Lyrics", str(e))

    def on_play(self):
        if not self.audio_path:
            messagebox.showwarning("Perlu Audio", "Silakan Load Audio terlebih dahulu.")
            return
        # Mulai dari awal lagi supaya sinkron dengan klik pertama
        self.audio.stop()
        self.audio.play()

    def on_pause_toggle(self):
        if not self.audio_path:
            return
        if not self.audio.is_playing():
            # jika belum play sama sekali, mulai play
            self.audio.play()
        else:
            self.audio.pause_toggle()

    def on_stop(self):
        self.audio.stop()

    def on_next_line(self):
        if not self._ensure_ready():
            return
        if self.current_index >= len(self.lyrics):
            messagebox.showinfo("Selesai", "Semua baris sudah tersinkron.")
            return

        # Ambil posisi saat ini sebagai timestamp baris sekarang
        pos_ms = self.audio.get_pos_ms()
        tag = ms_to_lrc(pos_ms)

        # Jika timestamp untuk baris ini sudah ada (karena back), kita overwrite posisi saat ini
        if self.current_index < len(self.timestamps):
            self.timestamps[self.current_index] = tag
        else:
            self.timestamps.append(tag)

        self.current_index += 1
        self._update_text_views()
        self._update_preview_list()
        self._update_progress()

        if self.current_index >= len(self.lyrics):
            # auto-stop saat selesai
            self.audio.stop()
            messagebox.showinfo("Selesai", "Semua baris sudah ditandai. Silakan Save LRC.")

    def on_back_line(self):
        if not self._ensure_ready():
            return
        if self.current_index <= 0:
            return
        self.current_index -= 1
        self._update_text_views()
        self._update_preview_list()

    def on_undo(self):
        # Hapus timestamp terakhir (kalau ada)
        if not self.timestamps:
            return
        self.timestamps.pop()
        if self.current_index > len(self.timestamps):
            self.current_index = len(self.timestamps)
        self._update_text_views()
        self._update_preview_list()
        self._update_progress()

    def on_save_lrc(self):
        if not self._ensure_ready():
            return
        if len(self.timestamps) == 0:
            if not messagebox.askyesno("Belum Ada Timestamp", "Belum ada timestamp. Tetap simpan?"):
                return

        default_name = "output.lrc"
        if self.audio_path:
            base = os.path.splitext(os.path.basename(self.audio_path))[0]
            default_name = f"{base}.lrc"

        save_path = filedialog.asksaveasfilename(
            defaultextension=".lrc",
            initialfile=default_name,
            title="Simpan File LRC",
            filetypes=[("LRC Lyrics", "*.lrc"), ("All Files", "*.*")]
        )
        if not save_path:
            return

        try:
            total = len(self.lyrics)
            with open(save_path, "w", encoding="utf-8") as f:
                # Optional: metadata header (kosongkan jika tidak perlu)
                # f.write("[ti:]\n[ar:]\n[al:]\n\n")

                for i in range(total):
                    ts = self.timestamps[i] if i < len(self.timestamps) else "[-]"
                    line = self.lyrics[i].strip()
                    if ts == "[-]":
                        # Jika belum bertimestamp, pakai terakhir yang ada atau 00:00.00
                        if self.timestamps:
                            ts = self.timestamps[-1]
                        else:
                            ts = "[00:00.00]"
                    f.write(f"{ts} {line}\n")

            messagebox.showinfo("Tersimpan", f"Berhasil menyimpan:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Gagal Menyimpan", str(e))

def main():
    app = KaraokeApp()
    app.mainloop()

if __name__ == "__main__":
    main()
