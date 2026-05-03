"""
Écran RUNNING — barre de progression, stats live, annulation.
"""
from __future__ import annotations

import time
import tkinter as tk

from gui.app import (
    C_BG, C_PANEL, C_CARD, C_BORDER, C_ACCENT, C_DANGER,
    C_SUCCESS, C_TEXT, C_SUB, C_WARN, WIN_W, WIN_H,
)

_BAR_W = 700
_BAR_H = 28


class RunFrame(tk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=C_BG)
        self._app = app
        self.cancelled = False
        self._total = 1
        self._start_time: float = 0.0
        self._last_tick = 0
        self._last_tick_time: float = 0.0
        self._ticks_per_s: float = 0.0
        self._out_path = ""
        self._poll_job: str | None = None

        self._build_ui()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        app = self._app

        # Header
        header = tk.Frame(self, bg=C_PANEL, height=54)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        self._title_lbl = tk.Label(
            header, text="⏳  Simulation en cours…",
            font=app.font("title"), bg=C_PANEL, fg=C_ACCENT,
        )
        self._title_lbl.pack(side=tk.LEFT, padx=20, pady=10)

        # Corps centré
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True)

        center = tk.Frame(body, bg=C_BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        # ── Nom du fichier ────────────────────────────────────────────────────
        self._file_lbl = tk.Label(
            center, text="", font=app.font("small"),
            bg=C_BG, fg=C_SUB,
        )
        self._file_lbl.pack(pady=(0, 16))

        # ── Barre de progression ──────────────────────────────────────────────
        bar_frame = tk.Frame(center, bg=C_CARD, width=_BAR_W, height=_BAR_H,
                             highlightthickness=1, highlightbackground=C_BORDER)
        bar_frame.pack()
        bar_frame.pack_propagate(False)

        self._bar_canvas = tk.Canvas(
            bar_frame, width=_BAR_W, height=_BAR_H,
            bg=C_CARD, highlightthickness=0,
        )
        self._bar_canvas.pack()
        self._bar_fill = self._bar_canvas.create_rectangle(
            0, 0, 0, _BAR_H, fill=C_ACCENT, outline="",
        )
        self._bar_text = self._bar_canvas.create_text(
            _BAR_W // 2, _BAR_H // 2,
            text="0 %", font=app.font("h2"), fill=C_BG,
        )

        # ── Ligne stats ───────────────────────────────────────────────────────
        stats_row = tk.Frame(center, bg=C_BG)
        stats_row.pack(pady=8)

        self._pct_lbl    = _stat_label(stats_row, "0 %",           app, C_TEXT,  w=80)
        _sep(stats_row)
        self._tick_lbl   = _stat_label(stats_row, "0 / 0",         app, C_SUB,   w=160)
        _sep(stats_row)
        self._speed_lbl  = _stat_label(stats_row, "- ticks/s",     app, C_SUB,   w=120)
        _sep(stats_row)
        self._eta_lbl    = _stat_label(stats_row, "ETA  --:--",    app, C_SUB,   w=130)

        # ── Grille populations ────────────────────────────────────────────────
        pop_outer = tk.Frame(center, bg=C_PANEL, width=_BAR_W,
                             highlightthickness=1, highlightbackground=C_BORDER)
        pop_outer.pack(pady=12)
        pop_outer.pack_propagate(False)

        tk.Label(
            pop_outer, text=" POPULATIONS", font=app.font("small"),
            bg=C_BORDER, fg=C_SUB, anchor="w",
        ).pack(fill=tk.X)

        self._pop_frame = tk.Frame(pop_outer, bg=C_PANEL)
        self._pop_frame.pack(fill=tk.X, padx=8, pady=6)
        self._pop_labels: dict[str, tk.Label] = {}

        # ── Bouton annuler ────────────────────────────────────────────────────
        self._cancel_btn = tk.Button(
            center, text="✕  Annuler",
            command=self._on_cancel,
            bg=C_DANGER, fg=C_BG,
            relief=tk.FLAT, cursor="hand2",
            font=app.font("h2"), padx=30, pady=8,
        )
        self._cancel_btn.pack(pady=(8, 0))

        # Bouton "Voir replay" (caché au départ)
        self._replay_btn = tk.Button(
            center, text="▶  Voir le replay",
            command=self._on_replay,
            bg=C_SUCCESS, fg=C_BG,
            relief=tk.FLAT, cursor="hand2",
            font=app.font("h2"), padx=30, pady=8,
        )

        # Bouton "Nouvelle simulation"
        self._new_btn = tk.Button(
            center, text="↩  Nouvelle simulation",
            command=self._app.back_to_setup,
            bg=C_PANEL, fg=C_TEXT,
            relief=tk.FLAT, cursor="hand2",
            font=app.font("body"), padx=20, pady=6,
        )

    # ── API publique ──────────────────────────────────────────────────────────

    def prepare(self, config: dict) -> None:
        self.cancelled = False
        self._total = config["ticks"]
        self._out_path = config["out_path"]
        self._start_time = time.monotonic()
        self._last_tick = 0
        self._last_tick_time = self._start_time
        self._ticks_per_s = 0.0

        self._title_lbl.config(text="⏳  Simulation en cours…", fg=C_ACCENT)
        self._file_lbl.config(text=f"→ {self._out_path}")
        self._tick_lbl.config(text=f"0 / {self._total:,}")
        self._pct_lbl.config(text="0 %")
        self._speed_lbl.config(text="- ticks/s")
        self._eta_lbl.config(text="ETA  --:--")
        self._bar_canvas.itemconfig(self._bar_fill, fill=C_ACCENT)
        self._bar_canvas.coords(self._bar_fill, 0, 0, 0, _BAR_H)
        self._bar_canvas.itemconfig(self._bar_text, text="0 %", fill=C_BG)

        self._cancel_btn.pack(pady=(8, 0))
        self._replay_btn.pack_forget()
        self._new_btn.pack_forget()

        # Réinitialise la grille de population
        for w in self._pop_frame.winfo_children():
            w.destroy()
        self._pop_labels.clear()

    def update_progress(self, tick: int, total: int, species_counts: dict) -> None:
        if self.cancelled:
            return

        now = time.monotonic()
        elapsed = now - self._start_time
        delta_tick = tick - self._last_tick
        delta_t = now - self._last_tick_time

        if delta_t > 0 and delta_tick > 0:
            self._ticks_per_s = delta_tick / delta_t

        self._last_tick = tick
        self._last_tick_time = now

        pct = tick / max(total, 1) * 100
        bar_px = int(_BAR_W * pct / 100)
        self._bar_canvas.coords(self._bar_fill, 0, 0, bar_px, _BAR_H)
        self._bar_canvas.itemconfig(
            self._bar_text,
            text=f"{pct:.1f} %",
            fill=C_BG if bar_px > 40 else C_TEXT,
        )
        self._pct_lbl.config(text=f"{pct:.1f} %")
        self._tick_lbl.config(text=f"{tick:,} / {total:,}")

        if self._ticks_per_s > 0:
            self._speed_lbl.config(text=f"{self._ticks_per_s:,.0f} ticks/s")
            remaining = (total - tick) / self._ticks_per_s
            mins, secs = divmod(int(remaining), 60)
            self._eta_lbl.config(text=f"ETA  {mins:02d}:{secs:02d}")

        self._update_pop_grid(species_counts)

    def _update_pop_grid(self, species_counts: dict) -> None:
        app = self._app
        # Trier : plantes d'abord (count élevé), puis animaux
        items = sorted(species_counts.items(), key=lambda x: -x[1])

        # Créer les labels manquants
        for name, _ in items:
            if name not in self._pop_labels:
                col = len(self._pop_labels) % 4
                row_idx = len(self._pop_labels) // 4
                cell = tk.Frame(self._pop_frame, bg=C_PANEL, width=160, height=28)
                cell.grid(row=row_idx, column=col, padx=4, pady=2, sticky="w")
                cell.pack_propagate(False)
                lbl = tk.Label(cell, text="", font=app.font("small"),
                               bg=C_PANEL, fg=C_TEXT, anchor="w")
                lbl.pack(fill=tk.BOTH, expand=True, padx=4)
                self._pop_labels[name] = lbl

        for name, count in items:
            if name in self._pop_labels:
                color = C_SUCCESS if count > 0 else C_DANGER
                self._pop_labels[name].config(
                    text=f"{name[:12]:<12}  {count:>5}",
                    fg=color,
                )

    def on_done(self, db_path: str) -> None:
        self._out_path = db_path
        self._title_lbl.config(text="✓  Simulation terminée", fg=C_SUCCESS)
        self._bar_canvas.itemconfig(self._bar_fill, fill=C_SUCCESS)
        self._cancel_btn.pack_forget()
        self._replay_btn.pack(pady=(8, 4))
        self._new_btn.pack(pady=(0, 4))

    def on_error(self, msg: str) -> None:
        self._title_lbl.config(text=f"✗  Erreur : {msg[:60]}", fg=C_DANGER)
        self._cancel_btn.pack_forget()
        self._new_btn.pack(pady=(8, 4))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        self.cancelled = True
        self._title_lbl.config(text="✕  Simulation annulée", fg=C_WARN)
        self._cancel_btn.pack_forget()
        self._new_btn.pack(pady=(8, 4))

    def _on_replay(self) -> None:
        self._app.open_replay(self._out_path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stat_label(parent: tk.Widget, text: str, app, fg: str, w: int = 120) -> tk.Label:
    lbl = tk.Label(parent, text=text, font=app.font("body"),
                   bg=C_BG, fg=fg, width=w // 8, anchor="center")
    lbl.pack(side=tk.LEFT, padx=6)
    return lbl


def _sep(parent: tk.Widget) -> None:
    tk.Frame(parent, bg=C_BORDER, width=1, height=20).pack(side=tk.LEFT)
