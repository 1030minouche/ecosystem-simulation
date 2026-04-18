"""
Écran REPLAY — visualisation d'un enregistrement .db.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageTk

from gui.app import (
    C_BG, C_PANEL, C_CARD, C_BORDER, C_ACCENT, C_DANGER,
    C_SUCCESS, C_TEXT, C_SUB, C_WARN, WIN_W, WIN_H,
)

if TYPE_CHECKING:
    from simulation.recording.replay import ReplayReader
    from simulation.recording.schema import WorldSnapshot

CANVAS_W = 650
CANVAS_H = 600
PANEL_W  = WIN_W - CANVAS_W - 32   # ≈ 418px
TIMELINE_H = 36

# Taille du dot par type d'entité
_DOT_PLANT  = 2
_DOT_ANIMAL = 3


class ReplayFrame(tk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=C_BG)
        self._app = app

        self._reader: "ReplayReader | None" = None
        self._terrain_img: ImageTk.PhotoImage | None = None
        self._terrain_canvas_img: int | None = None
        self._entity_items: dict[int, int] = {}   # entity_id → canvas_item
        self._species_colors: dict[str, str] = {}
        self._world_w = 500
        self._world_h = 500
        self._cur_tick = 0
        self._playing = False
        self._speed = 1.0          # keyframes/s
        self._play_job: str | None = None
        self._selected_id: int | None = None
        self._entity_history: dict[int, list] = {}  # id → [{tick, x, y, energy}]

        self._build_ui()

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        app = self._app

        # Header
        header = tk.Frame(self, bg=C_PANEL, height=54)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Button(
            header, text="←  Configuration",
            command=self._app.back_to_setup,
            bg=C_CARD, fg=C_SUB, relief=tk.FLAT,
            cursor="hand2", font=app.font("small"), padx=10,
        ).pack(side=tk.LEFT, padx=8, pady=10)

        self._title_lbl = tk.Label(
            header, text="EcoSim — Replay",
            font=app.font("title"), bg=C_PANEL, fg=C_ACCENT,
        )
        self._title_lbl.pack(side=tk.LEFT, pady=10)

        self._meta_lbl = tk.Label(
            header, text="", font=app.font("small"), bg=C_PANEL, fg=C_SUB,
        )
        self._meta_lbl.pack(side=tk.LEFT, padx=16, pady=10)

        tk.Button(
            header, text="📂  Ouvrir…",
            command=self._browse_db,
            bg=C_CARD, fg=C_TEXT, relief=tk.FLAT,
            cursor="hand2", font=app.font("small"), padx=10,
        ).pack(side=tk.RIGHT, padx=12, pady=10)

        # Corps
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        # ── Colonne gauche : canvas + timeline ────────────────────────────────
        left = tk.Frame(body, bg=C_BG)
        left.pack(side=tk.LEFT, fill=tk.Y)

        self._canvas = tk.Canvas(
            left, width=CANVAS_W, height=CANVAS_H,
            bg="#000818", highlightthickness=1, highlightbackground=C_BORDER,
        )
        self._canvas.pack()
        self._canvas.bind("<Button-1>", self._on_canvas_click)

        self._build_timeline(left)

        # ── Colonne droite : info + population ───────────────────────────────
        right = tk.Frame(body, bg=C_PANEL, width=PANEL_W)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0))
        right.pack_propagate(False)

        self._build_right_panel(right)

    def _build_timeline(self, parent: tk.Widget) -> None:
        app = self._app
        tl = tk.Frame(parent, bg=C_PANEL, height=TIMELINE_H,
                      highlightthickness=1, highlightbackground=C_BORDER)
        tl.pack(fill=tk.X, pady=(4, 0))
        tl.pack_propagate(False)

        # Boutons contrôle
        ctrl = tk.Frame(tl, bg=C_PANEL)
        ctrl.pack(side=tk.LEFT, padx=4)

        self._play_btn = tk.Button(
            ctrl, text="▶", command=self._toggle_play,
            bg=C_CARD, fg=C_ACCENT, relief=tk.FLAT,
            cursor="hand2", font=app.font("h2"), width=2,
        )
        self._play_btn.pack(side=tk.LEFT, padx=2)

        tk.Button(ctrl, text="◀◀", command=lambda: self._jump(-500),
                  bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                  font=app.font("small"), width=3).pack(side=tk.LEFT, padx=1)
        tk.Button(ctrl, text="◀", command=lambda: self._jump(-1),
                  bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                  font=app.font("small"), width=2).pack(side=tk.LEFT, padx=1)
        tk.Button(ctrl, text="▶", command=lambda: self._jump(1),
                  bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                  font=app.font("small"), width=2).pack(side=tk.LEFT, padx=1)
        tk.Button(ctrl, text="▶▶", command=lambda: self._jump(500),
                  bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                  font=app.font("small"), width=3).pack(side=tk.LEFT, padx=1)

        # Vitesse
        speed_frame = tk.Frame(tl, bg=C_PANEL)
        speed_frame.pack(side=tk.RIGHT, padx=6)
        tk.Button(speed_frame, text="−", command=self._speed_down,
                  bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                  font=app.font("body"), width=2).pack(side=tk.LEFT)
        self._speed_lbl = tk.Label(speed_frame, text="×1.0",
                                   font=app.font("small"), bg=C_PANEL, fg=C_SUB, width=5)
        self._speed_lbl.pack(side=tk.LEFT, padx=2)
        tk.Button(speed_frame, text="+", command=self._speed_up,
                  bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                  font=app.font("body"), width=2).pack(side=tk.LEFT)

        # Slider + tick label
        slider_frame = tk.Frame(tl, bg=C_PANEL)
        slider_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self._tick_lbl = tk.Label(slider_frame, text="0 / 0",
                                  font=app.font("small"), bg=C_PANEL, fg=C_SUB, width=14)
        self._tick_lbl.pack(side=tk.RIGHT)

        self._slider_var = tk.IntVar(value=0)
        self._slider = tk.Scale(
            slider_frame, from_=0, to=1, orient=tk.HORIZONTAL,
            variable=self._slider_var, command=self._on_slider,
            bg=C_PANEL, fg=C_TEXT, troughcolor=C_CARD,
            activebackground=C_ACCENT, highlightthickness=0,
            sliderlength=14, length=380, showvalue=False,
        )
        self._slider.pack(fill=tk.X, expand=True)

    def _build_right_panel(self, parent: tk.Widget) -> None:
        app = self._app

        # Population
        tk.Label(parent, text=" POPULATIONS", font=app.font("small"),
                 bg=C_BORDER, fg=C_SUB, anchor="w").pack(fill=tk.X)

        self._pop_frame = tk.Frame(parent, bg=C_PANEL)
        self._pop_frame.pack(fill=tk.X, padx=6, pady=4)
        self._pop_labels: dict[str, tk.Label] = {}

        # Graphe population
        tk.Label(parent, text=" GRAPHE", font=app.font("small"),
                 bg=C_BORDER, fg=C_SUB, anchor="w").pack(fill=tk.X, pady=(8, 0))

        self._graph_canvas = tk.Canvas(
            parent, width=PANEL_W - 12, height=140,
            bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER,
        )
        self._graph_canvas.pack(padx=6, pady=4)
        self._graph_history: dict[str, list[int]] = {}
        self._graph_colors:  dict[str, str]       = {}

        # Entité sélectionnée
        tk.Label(parent, text=" ENTITÉ SÉLECTIONNÉE", font=app.font("small"),
                 bg=C_BORDER, fg=C_SUB, anchor="w").pack(fill=tk.X, pady=(8, 0))

        self._entity_frame = tk.Frame(parent, bg=C_PANEL)
        self._entity_frame.pack(fill=tk.X, padx=6, pady=4)

        self._ent_name_lbl = tk.Label(self._entity_frame, text="—",
                                      font=app.font("h2"), bg=C_PANEL, fg=C_TEXT)
        self._ent_name_lbl.pack(anchor="w")
        self._ent_info_lbl = tk.Label(self._entity_frame, text="",
                                      font=app.font("small"), bg=C_PANEL, fg=C_SUB,
                                      justify=tk.LEFT)
        self._ent_info_lbl.pack(anchor="w")

    # ── API publique ──────────────────────────────────────────────────────────

    def load(self, db_path: str) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

        self._playing = False
        if self._play_job:
            self.after_cancel(self._play_job)
            self._play_job = None

        from simulation.recording.replay import ReplayReader
        self._reader = ReplayReader(Path(db_path))

        meta = self._reader.meta
        self._world_w = int(meta.get("world_width",  500))
        self._world_h = int(meta.get("world_height", 500))
        seed          = int(meta.get("seed", 42))
        max_tick      = self._reader.total_ticks

        self._title_lbl.config(text=f"EcoSim — Replay  {Path(db_path).name}")
        self._meta_lbl.config(
            text=f"seed={seed}  ·  {self._world_w}×{self._world_h}  ·  {max_tick:,} ticks"
        )

        self._slider.config(from_=self._reader.min_tick, to=max(max_tick, 1))
        self._slider_var.set(self._reader.min_tick)
        self._cur_tick = self._reader.min_tick

        self._graph_history.clear()
        self._graph_colors.clear()

        self._build_terrain_image(seed)
        self._goto_tick(self._cur_tick)
        self._play_btn.config(text="▶")

    def on_show(self) -> None:
        pass

    # ── Terrain ───────────────────────────────────────────────────────────────

    def _build_terrain_image(self, seed: int) -> None:
        from world.grid import Grid
        from world.terrain import generate_terrain, BIOME_PALETTE

        grid = Grid(width=self._world_w, height=self._world_h)
        generate_terrain(grid, seed=seed)

        alt = np.array(grid.altitude)
        rgb = np.zeros((self._world_h, self._world_w, 3), dtype=np.uint8)
        for threshold, color in BIOME_PALETTE:
            mask = alt >= threshold
            rgb[mask] = color

        img = Image.fromarray(rgb, "RGB").resize(
            (CANVAS_W, CANVAS_H), Image.NEAREST
        )
        self._terrain_img = ImageTk.PhotoImage(img)
        self._canvas.delete("all")
        self._terrain_canvas_img = self._canvas.create_image(
            0, 0, anchor="nw", image=self._terrain_img,
        )
        self._entity_items.clear()

    # ── Rendu entités ─────────────────────────────────────────────────────────

    def _goto_tick(self, tick: int) -> None:
        if self._reader is None:
            return

        snap = self._reader.state_at(tick)
        if snap is None:
            return

        self._cur_tick = snap.tick
        self._slider_var.set(self._cur_tick)
        self._tick_lbl.config(
            text=f"{self._cur_tick:,} / {self._reader.total_ticks:,}"
        )

        self._render_snap(snap)
        self._update_pop_panel(snap.species_counts)
        self._update_graph(snap.species_counts, snap.tick)

        if self._selected_id is not None:
            self._update_entity_panel(snap)

    def _render_snap(self, snap: "WorldSnapshot") -> None:
        canvas = self._canvas
        sx = CANVAS_W / self._world_w
        sy = CANVAS_H / self._world_h

        seen_ids: set[int] = set()

        for e in (*snap.plants, *snap.individuals):
            if not e.alive:
                continue
            seen_ids.add(e.id)
            cx = e.x * sx
            cy = e.y * sy
            is_plant = e in snap.plants
            r = _DOT_PLANT if is_plant else _DOT_ANIMAL
            fill = self._species_color(e.species)

            if e.id in self._entity_items:
                canvas.coords(
                    self._entity_items[e.id],
                    cx - r, cy - r, cx + r, cy + r,
                )
            else:
                item = canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    fill=fill, outline="", tags=("entity", str(e.id)),
                )
                self._entity_items[e.id] = item

        # Supprimer les entités mortes/absentes
        to_remove = [eid for eid in self._entity_items if eid not in seen_ids]
        for eid in to_remove:
            canvas.delete(self._entity_items.pop(eid))

    def _species_color(self, name: str) -> str:
        if name not in self._species_colors:
            import hashlib
            h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
            r = (h >> 16) & 0xFF
            g = (h >>  8) & 0xFF
            b =  h        & 0xFF
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum < 90:
                r = min(255, r + 110)
                g = min(255, g + 110)
                b = min(255, b + 110)
            self._species_colors[name] = f"#{r:02x}{g:02x}{b:02x}"
        return self._species_colors[name]

    # ── Panneau population ────────────────────────────────────────────────────

    def _update_pop_panel(self, counts: dict) -> None:
        app = self._app
        items = sorted(counts.items(), key=lambda x: -x[1])

        for name, _ in items:
            if name not in self._pop_labels:
                row = tk.Frame(self._pop_frame, bg=C_PANEL)
                row.pack(fill=tk.X, pady=1)
                dot = tk.Canvas(row, width=10, height=10, bg=C_PANEL,
                                highlightthickness=0)
                col = self._species_color(name)
                dot.create_oval(1, 1, 9, 9, fill=col, outline="")
                dot.pack(side=tk.LEFT, padx=(0, 4))
                lbl = tk.Label(row, text="", font=app.font("small"),
                               bg=C_PANEL, fg=C_TEXT, anchor="w")
                lbl.pack(side=tk.LEFT)
                self._pop_labels[name] = lbl
                self._graph_colors[name] = col

        for name, count in items:
            if name in self._pop_labels:
                self._pop_labels[name].config(
                    text=f"{name:<16}  {count:>5}",
                    fg=C_SUCCESS if count > 0 else C_DANGER,
                )

    # ── Graphe population ─────────────────────────────────────────────────────

    def _update_graph(self, counts: dict, tick: int) -> None:
        for name, count in counts.items():
            if name not in self._graph_history:
                self._graph_history[name] = []
            self._graph_history[name].append(count)
            if len(self._graph_history[name]) > 200:
                self._graph_history[name] = self._graph_history[name][-200:]

        self._draw_graph()

    def _draw_graph(self) -> None:
        c = self._graph_canvas
        c.delete("all")
        gw = PANEL_W - 12
        gh = 140

        if not self._graph_history:
            return

        max_val = max(
            (max(h) for h in self._graph_history.values() if h), default=1
        ) or 1

        n_pts = max(len(h) for h in self._graph_history.values())
        if n_pts < 2:
            return

        for name, history in self._graph_history.items():
            if not history:
                continue
            col = self._graph_colors.get(name, "#aaaaaa")
            pts = []
            for i, v in enumerate(history):
                x = int(i / (n_pts - 1) * (gw - 4)) + 2
                y = int((1 - v / max_val) * (gh - 6)) + 3
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(*pts, fill=col, width=1, smooth=True)

    # ── Sélection entité ──────────────────────────────────────────────────────

    def _on_canvas_click(self, event: tk.Event) -> None:
        if self._reader is None:
            return

        snap = self._reader.state_at(self._cur_tick)
        if snap is None:
            return

        sx = self._world_w / CANVAS_W
        sy = self._world_h / CANVAS_H
        wx = event.x * sx
        wy = event.y * sy

        best_id   = None
        best_dist = 15.0

        for e in (*snap.plants, *snap.individuals):
            if not e.alive:
                continue
            d = ((e.x - wx) ** 2 + (e.y - wy) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_id   = e.id

        self._selected_id = best_id
        self._update_entity_panel(snap)

    def _update_entity_panel(self, snap: "WorldSnapshot") -> None:
        if self._selected_id is None:
            self._ent_name_lbl.config(text="—")
            self._ent_info_lbl.config(text="")
            return

        entity = None
        for e in (*snap.plants, *snap.individuals):
            if e.id == self._selected_id:
                entity = e
                break

        if entity is None:
            self._ent_name_lbl.config(text="✝ disparu", fg=C_DANGER)
            self._ent_info_lbl.config(text="")
            return

        self._ent_name_lbl.config(text=entity.species, fg=self._species_color(entity.species))
        age_ticks = entity.age
        self._ent_info_lbl.config(
            text=(
                f"x: {entity.x:.1f}  y: {entity.y:.1f}\n"
                f"énergie: {entity.energy:.1f}\n"
                f"âge: {age_ticks:,} ticks\n"
                f"état: {entity.state}"
            ),
            fg=C_SUB,
        )

    # ── Playback ──────────────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._reader is None:
            return
        self._playing = not self._playing
        self._play_btn.config(text="⏸" if self._playing else "▶")
        if self._playing:
            self._play_next()

    def _play_next(self) -> None:
        if not self._playing or self._reader is None:
            return

        kf_ticks = self._reader._keyframe_ticks
        if not kf_ticks:
            self._playing = False
            self._play_btn.config(text="▶")
            return

        # Trouver la prochaine keyframe après cur_tick
        next_tick = None
        for t in kf_ticks:
            if t > self._cur_tick:
                next_tick = t
                break

        if next_tick is None:
            self._playing = False
            self._play_btn.config(text="▶")
            return

        self._goto_tick(next_tick)

        delay_ms = max(16, int(1000 / max(self._speed, 0.1)))
        self._play_job = self.after(delay_ms, self._play_next)

    def _jump(self, delta_kf: int) -> None:
        if self._reader is None:
            return
        kf_ticks = self._reader._keyframe_ticks
        if not kf_ticks:
            return

        # Trouver l'index de la keyframe courante
        cur_idx = 0
        for i, t in enumerate(kf_ticks):
            if t <= self._cur_tick:
                cur_idx = i

        new_idx = max(0, min(len(kf_ticks) - 1, cur_idx + delta_kf))
        self._goto_tick(kf_ticks[new_idx])

    def _speed_up(self) -> None:
        self._speed = min(16.0, self._speed * 2)
        self._speed_lbl.config(text=f"×{self._speed:.1f}")

    def _speed_down(self) -> None:
        self._speed = max(0.25, self._speed / 2)
        self._speed_lbl.config(text=f"×{self._speed:.1f}")

    def _on_slider(self, val: str) -> None:
        if self._reader is None:
            return
        tick = int(float(val))
        if tick != self._cur_tick:
            self._goto_tick(tick)

    # ── Ouvrir fichier ────────────────────────────────────────────────────────

    def _browse_db(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Base EcoSim", "*.db"), ("Tous", "*.*")],
            initialdir="runs",
            title="Ouvrir un enregistrement",
        )
        if path:
            self.load(path)
