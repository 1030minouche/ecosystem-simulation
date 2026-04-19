"""
Écran REPLAY — rendu fluide via composite numpy → PIL → PhotoImage.

Principe de rendu :
  Un seul numpy array (H×W×3) est recalculé par frame :
    1. Copie du terrain pré-calculé (self._terrain_arr)
    2. Dépôt vectorisé des pixels plantes (fancy-indexing numpy)
    3. Boucle sur animaux (<500) pour les dots 5×5
    4. Highlight de l'entité sélectionnée (bague blanche)
    5. Conversion PIL → PhotoImage → itemconfig (1 seul appel canvas)
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog

from gui.app import (
    C_BG, C_PANEL, C_CARD, C_BORDER, C_ACCENT, C_DANGER,
    C_SUCCESS, C_TEXT, C_SUB, C_WARN, WIN_W, WIN_H,
)

if TYPE_CHECKING:
    from simulation.recording.replay import ReplayReader
    from simulation.recording.schema import WorldSnapshot

CANVAS_W  = 680
CANVAS_H  = 590
PANEL_W   = WIN_W - CANVAS_W - 28
TIMELINE_H = 38
HEADER_H  = 54

_SPECIES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "species")

# Tailles des points de rendu
_R_PLANT  = 1   # rayon en pixels canvas (dot 3×3 centrée)
_R_ANIMAL = 2   # rayon → dot 5×5
_R_SEL    = 7   # rayon bague de sélection


# ── Helpers de rendu numpy ────────────────────────────────────────────────────

def _dot(arr: np.ndarray, cx: int, cy: int, r: int, color: np.ndarray) -> None:
    h, w = arr.shape[:2]
    x0, x1 = max(0, cx - r), min(w, cx + r + 1)
    y0, y1 = max(0, cy - r), min(h, cy + r + 1)
    if x0 < x1 and y0 < y1:
        arr[y0:y1, x0:x1] = color


def _ring(arr: np.ndarray, cx: int, cy: int, r: int, color: np.ndarray) -> None:
    h, w = arr.shape[:2]
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if abs(abs(dx) - r) <= 1 or abs(abs(dy) - r) <= 1:
                px, py = cx + dx, cy + dy
                if 0 <= px < w and 0 <= py < h:
                    arr[py, px] = color


class ReplayFrame(tk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=C_BG)
        self._app = app

        self._reader: "ReplayReader | None" = None
        self._world_w = 500
        self._world_h = 500
        self._scale_x = CANVAS_W / 500
        self._scale_y = CANVAS_H / 500
        self._terrain_preset = "default"

        # Rendu numpy
        self._terrain_arr: np.ndarray | None = None        # H×W×3 uint8 (fixe)
        self._frame_arr:   np.ndarray | None = None        # buffer de travail
        self._frame_photo: ImageTk.PhotoImage | None = None
        self._canvas_img_id: int | None = None

        # Couleurs espèces
        self._sp_color_hex: dict[str, str] = {}            # name → "#rrggbb"
        self._sp_color_arr: dict[str, np.ndarray] = {}     # name → uint8[3]
        self._sp_max_pop:   dict[str, int] = {}            # pour les barres

        # Playback
        self._cur_tick = 0
        self._playing  = False
        self._speed    = 1.0
        self._next_frame_target: float = 0.0
        self._play_job: str | None = None

        # Sélection
        self._selected_id: int | None = None
        self._snap_cache: "WorldSnapshot | None" = None    # dernier snap rendu

        self._build_ui()
        self._load_species_colors()

    # ── Couleurs espèces ──────────────────────────────────────────────────────

    def _load_species_colors(self) -> None:
        for path in glob.glob(os.path.join(_SPECIES_DIR, "*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                name = data["params"]["name"]
                r, g, b = [int(c * 255) for c in data["params"]["color"]]
                self._sp_color_hex[name] = f"#{r:02x}{g:02x}{b:02x}"
                self._sp_color_arr[name] = np.array([r, g, b], dtype=np.uint8)
            except Exception:
                pass

    def _color_hex(self, name: str) -> str:
        if name not in self._sp_color_hex:
            import hashlib
            h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
            r = min(255, ((h >> 16) & 0xFF) + 80)
            g = min(255, ((h >>  8) & 0xFF) + 80)
            b = min(255, ( h        & 0xFF) + 80)
            self._sp_color_hex[name] = f"#{r:02x}{g:02x}{b:02x}"
            self._sp_color_arr[name] = np.array([r, g, b], dtype=np.uint8)
        return self._sp_color_hex[name]

    def _color_arr(self, name: str) -> np.ndarray:
        self._color_hex(name)
        return self._sp_color_arr[name]

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        app = self._app

        # Header
        header = tk.Frame(self, bg=C_PANEL, height=HEADER_H)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Button(
            header, text="←",
            command=self._app.back_to_setup,
            bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
            font=app.font("h2"), width=3,
        ).pack(side=tk.LEFT, padx=8, pady=8)

        self._title_lbl = tk.Label(
            header, text="EcoSim — Replay",
            font=app.font("title"), bg=C_PANEL, fg=C_ACCENT,
        )
        self._title_lbl.pack(side=tk.LEFT, padx=4, pady=8)

        self._meta_lbl = tk.Label(
            header, text="", font=app.font("small"), bg=C_PANEL, fg=C_SUB,
        )
        self._meta_lbl.pack(side=tk.LEFT, padx=12, pady=8)

        tk.Button(
            header, text="📂  Ouvrir…",
            command=self._browse_db,
            bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, cursor="hand2",
            font=app.font("small"), padx=10,
        ).pack(side=tk.RIGHT, padx=12, pady=8)

        # Corps
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 8))

        # Gauche : canvas + timeline
        left = tk.Frame(body, bg=C_BG)
        left.pack(side=tk.LEFT)

        self._canvas = tk.Canvas(
            left, width=CANVAS_W, height=CANVAS_H,
            bg="#050d18", highlightthickness=1, highlightbackground=C_BORDER,
            cursor="crosshair",
        )
        self._canvas.pack()
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas.bind("<Motion>",   self._on_canvas_hover)

        # HUD sur le canvas
        self._hud_tick = self._canvas.create_text(
            8, 8, anchor="nw", text="",
            font=app.font("small"), fill=C_SUB,
        )
        self._hud_hover = self._canvas.create_text(
            CANVAS_W - 8, 8, anchor="ne", text="",
            font=app.font("small"), fill=C_TEXT,
        )

        self._build_timeline(left, app)

        # Droite : populations + graphe + entité
        right = tk.Frame(body, bg=C_PANEL, width=PANEL_W)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0))
        right.pack_propagate(False)
        self._build_right_panel(right, app)

        # Raccourcis clavier
        self.bind_all("<space>",           lambda _: self._toggle_play())
        self.bind_all("<Left>",            lambda _: self._jump(-1))
        self.bind_all("<Right>",           lambda _: self._jump(1))
        self.bind_all("<Shift-Left>",      lambda _: self._jump(-10))
        self.bind_all("<Shift-Right>",     lambda _: self._jump(10))
        self.bind_all("<Control-Left>",    lambda _: self._jump(-9999))
        self.bind_all("<Control-Right>",   lambda _: self._jump(9999))
        self.bind_all("<plus>",            lambda _: self._speed_up())
        self.bind_all("<minus>",           lambda _: self._speed_down())
        self.bind_all("<KP_Add>",          lambda _: self._speed_up())
        self.bind_all("<KP_Subtract>",     lambda _: self._speed_down())

    def _build_timeline(self, parent: tk.Widget, app) -> None:
        tl = tk.Frame(parent, bg=C_PANEL, height=TIMELINE_H,
                      highlightthickness=1, highlightbackground=C_BORDER)
        tl.pack(fill=tk.X, pady=(4, 0))
        tl.pack_propagate(False)

        # Play/Pause
        self._play_btn = tk.Button(
            tl, text="▶", command=self._toggle_play,
            bg=C_ACCENT, fg=C_BG, relief=tk.FLAT, cursor="hand2",
            font=app.font("h2"), width=3, pady=2,
        )
        self._play_btn.pack(side=tk.LEFT, padx=(6, 2), pady=4)

        # Steps
        for lbl, delta in [("⏮", -9999), ("◀", -1), ("▶", 1), ("⏭", 9999)]:
            tk.Button(
                tl, text=lbl, command=lambda d=delta: self._jump(d),
                bg=C_CARD, fg=C_SUB, relief=tk.FLAT, cursor="hand2",
                font=app.font("body"), width=2, pady=2,
            ).pack(side=tk.LEFT, padx=1, pady=4)

        # Vitesse
        speed_f = tk.Frame(tl, bg=C_PANEL)
        speed_f.pack(side=tk.RIGHT, padx=8, pady=4)
        tk.Label(speed_f, text="vitesse", font=app.font("small"),
                 bg=C_PANEL, fg=C_SUB).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(speed_f, text="−", command=self._speed_down,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, cursor="hand2",
                  font=app.font("body"), width=2).pack(side=tk.LEFT)
        self._speed_lbl = tk.Label(speed_f, text="×1",
                                   font=app.font("body"), bg=C_PANEL, fg=C_TEXT, width=4)
        self._speed_lbl.pack(side=tk.LEFT)
        tk.Button(speed_f, text="+", command=self._speed_up,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, cursor="hand2",
                  font=app.font("body"), width=2).pack(side=tk.LEFT)

        # Slider
        mid = tk.Frame(tl, bg=C_PANEL)
        mid.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self._tick_lbl = tk.Label(mid, text="0 / 0",
                                  font=app.font("small"), bg=C_PANEL, fg=C_SUB, width=16)
        self._tick_lbl.pack(side=tk.RIGHT)

        self._slider_var = tk.IntVar(value=0)
        self._slider = tk.Scale(
            mid, from_=0, to=1, orient=tk.HORIZONTAL,
            variable=self._slider_var, command=self._on_slider,
            bg=C_PANEL, fg=C_TEXT, troughcolor=C_CARD,
            activebackground=C_ACCENT, highlightthickness=0,
            sliderlength=12, showvalue=False,
        )
        self._slider.pack(fill=tk.X, expand=True)

    def _build_right_panel(self, parent: tk.Widget, app) -> None:
        # ── Populations ───────────────────────────────────────────────────────
        tk.Label(parent, text=" POPULATIONS", font=app.font("small"),
                 bg=C_BORDER, fg=C_SUB, anchor="w").pack(fill=tk.X)

        self._pop_frame = tk.Frame(parent, bg=C_PANEL)
        self._pop_frame.pack(fill=tk.X, padx=6, pady=4)
        self._pop_rows: dict[str, dict] = {}   # name → {lbl_count, bar_canvas, bar_fill}

        # ── Graphe ────────────────────────────────────────────────────────────
        tk.Label(parent, text=" GRAPHE POPULATION", font=app.font("small"),
                 bg=C_BORDER, fg=C_SUB, anchor="w").pack(fill=tk.X, pady=(8, 0))

        self._graph_c = tk.Canvas(
            parent, width=PANEL_W - 8, height=130,
            bg="#0a1020", highlightthickness=1, highlightbackground=C_BORDER,
        )
        self._graph_c.pack(padx=4, pady=4)
        self._graph_hist: dict[str, list[int]] = {}

        # ── Entité sélectionnée ───────────────────────────────────────────────
        tk.Label(parent, text=" ENTITÉ SÉLECTIONNÉE", font=app.font("small"),
                 bg=C_BORDER, fg=C_SUB, anchor="w").pack(fill=tk.X, pady=(8, 0))

        ef = tk.Frame(parent, bg=C_PANEL)
        ef.pack(fill=tk.X, padx=6, pady=6)

        self._ent_dot = tk.Canvas(ef, width=14, height=14, bg=C_PANEL,
                                  highlightthickness=0)
        self._ent_dot.pack(side=tk.LEFT, padx=(0, 6))

        ename_f = tk.Frame(ef, bg=C_PANEL)
        ename_f.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._ent_name_lbl = tk.Label(ename_f, text="—  cliquez une entité",
                                      font=app.font("h2"), bg=C_PANEL, fg=C_SUB)
        self._ent_name_lbl.pack(anchor="w")

        # Barre d'énergie
        self._ent_energy_canvas = tk.Canvas(
            parent, width=PANEL_W - 12, height=12,
            bg=C_CARD, highlightthickness=1, highlightbackground=C_BORDER,
        )
        self._ent_energy_canvas.pack(padx=6, pady=(0, 4))
        self._ent_energy_bar = self._ent_energy_canvas.create_rectangle(
            0, 0, 0, 12, fill=C_SUCCESS, outline="",
        )

        self._ent_info_lbl = tk.Label(
            parent, text="", font=app.font("small"),
            bg=C_PANEL, fg=C_SUB, justify=tk.LEFT, anchor="w",
        )
        self._ent_info_lbl.pack(padx=8, anchor="w")

        # Raccourcis
        tk.Label(
            parent,
            text="Espace · ← → · Shift·← → · + −",
            font=app.font("small"), bg=C_PANEL, fg=C_BORDER, anchor="w",
        ).pack(side=tk.BOTTOM, padx=6, pady=4, fill=tk.X)

    # ── API publique ──────────────────────────────────────────────────────────

    def load(self, db_path: str) -> None:
        self._stop_play()
        if self._reader is not None:
            self._reader.close()

        from simulation.recording.replay import ReplayReader
        self._reader = ReplayReader(Path(db_path))

        meta       = self._reader.meta
        self._world_w = int(meta.get("world_width",  500))
        self._world_h = int(meta.get("world_height", 500))
        self._scale_x = CANVAS_W / self._world_w
        self._scale_y = CANVAS_H / self._world_h
        seed          = int(meta.get("seed", 42))
        self._terrain_preset = meta.get("terrain_preset", "default")
        max_tick      = self._reader.total_ticks
        min_tick      = self._reader.min_tick

        self._title_lbl.config(text=f"EcoSim — {Path(db_path).name}")
        self._meta_lbl.config(
            text=f"seed={seed}  ·  {self._world_w}×{self._world_h}  "
                 f"·  {len(self._reader._keyframe_ticks)} keyframes"
        )
        self._slider.config(from_=min_tick, to=max(max_tick, 1))
        self._slider_var.set(min_tick)
        self._cur_tick = min_tick

        self._graph_hist.clear()
        self._sp_max_pop.clear()
        for w in self._pop_frame.winfo_children():
            w.destroy()
        self._pop_rows.clear()

        self._snap_cache = None
        self._selected_id = None
        self._ent_name_lbl.config(text="—  cliquez une entité", fg=C_SUB)
        self._ent_info_lbl.config(text="")
        self._ent_dot.delete("all")
        self._canvas.delete("all")
        self._canvas_img_id = None

        # Terrain en thread de fond
        self._show_loading()
        threading.Thread(
            target=self._build_terrain_bg, args=(seed, self._terrain_preset), daemon=True
        ).start()

    def on_show(self) -> None:
        pass

    # ── Terrain (thread de fond) ──────────────────────────────────────────────

    def _show_loading(self) -> None:
        self._canvas.delete("all")
        self._canvas.create_text(
            CANVAS_W // 2, CANVAS_H // 2,
            text="Génération du terrain…", fill=C_SUB,
            font=self._app.font("h2"),
        )

    def _build_terrain_bg(self, seed: int, preset: str = "default") -> None:
        from world.grid import Grid
        from world.terrain import generate_terrain, BIOME_PALETTE

        grid = Grid(width=self._world_w, height=self._world_h)
        generate_terrain(grid, seed=seed, preset=preset)

        alt = np.array(grid.altitude)
        rgb = np.zeros((self._world_h, self._world_w, 3), dtype=np.uint8)
        for threshold, color in BIOME_PALETTE:
            rgb[alt >= threshold] = color

        # Redimensionner au canvas
        img = Image.fromarray(rgb, "RGB").resize((CANVAS_W, CANVAS_H), Image.NEAREST)
        self._terrain_arr = np.asarray(img).copy()
        self._frame_arr   = np.empty_like(self._terrain_arr)

        self._app.root.after(0, self._on_terrain_ready)

    def _on_terrain_ready(self) -> None:
        self._canvas.delete("all")
        # Créer l'item image unique
        blank = ImageTk.PhotoImage(Image.fromarray(self._terrain_arr))
        self._frame_photo   = blank
        self._canvas_img_id = self._canvas.create_image(0, 0, anchor="nw",
                                                         image=self._frame_photo)
        # Remonter le HUD par-dessus
        self._canvas.tag_raise(self._hud_tick)
        self._canvas.tag_raise(self._hud_hover)

        self._goto_tick(self._cur_tick)

    # ── Rendu d'une frame ─────────────────────────────────────────────────────

    def _goto_tick(self, tick: int) -> None:
        if self._reader is None or self._terrain_arr is None:
            return

        snap = self._reader.state_at(tick)
        if snap is None:
            return

        self._cur_tick  = snap.tick
        self._snap_cache = snap
        self._slider_var.set(self._cur_tick)
        self._tick_lbl.config(
            text=f"{self._cur_tick:,} / {self._reader.total_ticks:,}"
        )
        self._canvas.itemconfig(
            self._hud_tick, text=f"tick {self._cur_tick:,}"
        )

        self._render_frame(snap)
        self._update_pop_panel(snap.species_counts)
        self._update_graph(snap.species_counts)
        if self._selected_id is not None:
            self._update_entity_panel(snap)

    def _render_frame(self, snap: "WorldSnapshot") -> None:
        arr = self._frame_arr
        np.copyto(arr, self._terrain_arr)

        sx, sy = self._scale_x, self._scale_y
        W, H   = CANVAS_W, CANVAS_H

        # ── Plantes (pixel unique, vectorisé par espèce) ───────────────────
        # Grouper par espèce pour le fancy-indexing
        plant_by_sp: dict[str, list] = {}
        for e in snap.plants:
            if e.alive:
                plant_by_sp.setdefault(e.species, []).append(e)

        for sp_name, plants in plant_by_sp.items():
            col = self._color_arr(sp_name)
            px  = np.clip(
                np.round(np.array([e.x for e in plants]) * sx).astype(int), 0, W - 1
            )
            py  = np.clip(
                np.round(np.array([e.y for e in plants]) * sy).astype(int), 0, H - 1
            )
            arr[py, px] = col   # assignment vectorisé

        # ── Animaux (dot 5×5) ─────────────────────────────────────────────
        for e in snap.individuals:
            if not e.alive:
                continue
            cx = int(e.x * sx + 0.5)
            cy = int(e.y * sy + 0.5)
            col = self._color_arr(e.species)
            if e.id == self._selected_id:
                _ring(arr, cx, cy, _R_SEL, np.array([255, 255, 200], dtype=np.uint8))
            _dot(arr, cx, cy, _R_ANIMAL, col)

        # ── PhotoImage ────────────────────────────────────────────────────
        img = Image.fromarray(arr, "RGB")
        self._frame_photo = ImageTk.PhotoImage(img)
        self._canvas.itemconfig(self._canvas_img_id, image=self._frame_photo)

    # ── Population panel ──────────────────────────────────────────────────────

    def _update_pop_panel(self, counts: dict) -> None:
        app  = self._app
        BAR_W = PANEL_W - 110

        items = sorted(counts.items(), key=lambda x: -x[1])

        for name, count in items:
            self._sp_max_pop[name] = max(self._sp_max_pop.get(name, 1), count, 1)

            if name not in self._pop_rows:
                row = tk.Frame(self._pop_frame, bg=C_PANEL)
                row.pack(fill=tk.X, pady=1)

                dot_c = tk.Canvas(row, width=10, height=10, bg=C_PANEL,
                                  highlightthickness=0)
                dot_c.create_oval(1, 1, 9, 9,
                                  fill=self._color_hex(name), outline="")
                dot_c.pack(side=tk.LEFT, padx=(0, 4))

                name_lbl = tk.Label(row, text=name[:14], font=app.font("small"),
                                    bg=C_PANEL, fg=C_TEXT, width=13, anchor="w")
                name_lbl.pack(side=tk.LEFT)

                bar_c = tk.Canvas(row, width=BAR_W, height=8,
                                  bg=C_CARD, highlightthickness=0)
                bar_c.pack(side=tk.LEFT, padx=(2, 4))
                bar_fill = bar_c.create_rectangle(0, 0, 0, 8,
                                                  fill=self._color_hex(name), outline="")

                cnt_lbl = tk.Label(row, text="0", font=app.font("small"),
                                   bg=C_PANEL, fg=C_SUCCESS, width=5, anchor="e")
                cnt_lbl.pack(side=tk.LEFT)

                self._pop_rows[name] = {
                    "bar_c": bar_c, "bar_fill": bar_fill,
                    "cnt_lbl": cnt_lbl, "max": 1,
                }

            row_data = self._pop_rows[name]
            max_pop  = self._sp_max_pop[name]
            bar_w    = int(BAR_W * count / max_pop) if count else 0
            row_data["bar_c"].coords(row_data["bar_fill"], 0, 0, bar_w, 8)
            fg = C_SUCCESS if count > 0 else C_DANGER
            row_data["cnt_lbl"].config(text=str(count), fg=fg)

    # ── Graphe ────────────────────────────────────────────────────────────────

    def _update_graph(self, counts: dict) -> None:
        for name, count in counts.items():
            lst = self._graph_hist.setdefault(name, [])
            lst.append(count)
            if len(lst) > 300:
                del lst[:100]

        c  = self._graph_c
        gw = PANEL_W - 8
        gh = 130
        c.delete("all")

        if not self._graph_hist:
            return

        max_val = max(
            (max(h) for h in self._graph_hist.values() if h), default=1
        ) or 1
        n_pts = max((len(h) for h in self._graph_hist.values()), default=0)
        if n_pts < 2:
            return

        for name, hist in self._graph_hist.items():
            if len(hist) < 2:
                continue
            col = self._color_hex(name)
            coords = []
            for i, v in enumerate(hist):
                x = 2 + int(i / (n_pts - 1) * (gw - 4))
                y = gh - 4 - int(v / max_val * (gh - 8))
                coords += [x, y]
            c.create_line(*coords, fill=col, width=1, smooth=True)

    # ── Sélection entité ──────────────────────────────────────────────────────

    def _on_canvas_click(self, event: tk.Event) -> None:
        if self._snap_cache is None:
            return
        snap = self._snap_cache
        wx = event.x / self._scale_x
        wy = event.y / self._scale_y

        best_id, best_d = None, 12.0
        for e in (*snap.plants, *snap.individuals):
            if not e.alive:
                continue
            d = ((e.x - wx) ** 2 + (e.y - wy) ** 2) ** 0.5
            if d < best_d:
                best_d, best_id = d, e.id

        self._selected_id = best_id
        self._render_frame(snap)
        self._update_entity_panel(snap)

    def _on_canvas_hover(self, event: tk.Event) -> None:
        if self._snap_cache is None:
            return
        snap = self._snap_cache
        wx = event.x / self._scale_x
        wy = event.y / self._scale_y

        best_name, best_d = "", 8.0
        for e in (*snap.plants, *snap.individuals):
            if not e.alive:
                continue
            d = ((e.x - wx) ** 2 + (e.y - wy) ** 2) ** 0.5
            if d < best_d:
                best_d, best_name = d, e.species

        self._canvas.itemconfig(self._hud_hover, text=best_name)

    def _update_entity_panel(self, snap: "WorldSnapshot") -> None:
        app = self._app
        if self._selected_id is None:
            return

        entity = next(
            (e for e in (*snap.plants, *snap.individuals)
             if e.id == self._selected_id),
            None,
        )

        if entity is None:
            self._ent_name_lbl.config(text="✝ disparu", fg=C_DANGER)
            self._ent_info_lbl.config(text="")
            self._ent_dot.delete("all")
            return

        col = self._color_hex(entity.species)
        self._ent_dot.delete("all")
        self._ent_dot.create_oval(1, 1, 13, 13, fill=col, outline="")
        self._ent_name_lbl.config(text=entity.species, fg=col)

        # Barre d'énergie (max supposé = 200)
        max_e = 200.0
        ratio = max(0.0, min(1.0, entity.energy / max_e))
        bar_w = int((PANEL_W - 12) * ratio)
        fill  = C_SUCCESS if ratio > 0.5 else C_WARN if ratio > 0.2 else C_DANGER
        self._ent_energy_canvas.itemconfig(self._ent_energy_bar, fill=fill)
        self._ent_energy_canvas.coords(self._ent_energy_bar, 0, 0, bar_w, 12)

        self._ent_info_lbl.config(
            text=(
                f"x: {entity.x:.1f}   y: {entity.y:.1f}\n"
                f"énergie: {entity.energy:.1f}\n"
                f"âge: {entity.age:,} ticks\n"
                f"état: {entity.state}"
            ),
            fg=C_SUB,
        )

    # ── Playback ──────────────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._reader is None or self._terrain_arr is None:
            return
        self._playing = not self._playing
        self._play_btn.config(
            text="⏸" if self._playing else "▶",
            bg=C_WARN if self._playing else C_ACCENT,
        )
        if self._playing:
            self._next_frame_target = time.monotonic()
            self._schedule_next_frame()

    def _stop_play(self) -> None:
        self._playing = False
        if self._play_job:
            try:
                self.after_cancel(self._play_job)
            except Exception:
                pass
            self._play_job = None
        self._play_btn.config(text="▶", bg=C_ACCENT)

    def _schedule_next_frame(self) -> None:
        if not self._playing:
            return
        now   = time.monotonic()
        delay = max(0, int((self._next_frame_target - now) * 1000))
        self._play_job = self.after(delay, self._play_step)

    def _play_step(self) -> None:
        if not self._playing or self._reader is None:
            return

        kf = self._reader._keyframe_ticks
        if not kf:
            self._stop_play()
            return

        # Trouver prochaine keyframe
        nxt = next((t for t in kf if t > self._cur_tick), None)
        if nxt is None:
            self._stop_play()
            return

        self._goto_tick(nxt)

        # Temps jusqu'à la prochaine frame (compensation de drift)
        self._next_frame_target += 1.0 / max(self._speed, 0.1)
        self._schedule_next_frame()

    def _jump(self, delta: int) -> None:
        if self._reader is None:
            return
        kf = self._reader._keyframe_ticks
        if not kf:
            return
        cur_idx = max(0, min(
            len(kf) - 1,
            next((i for i, t in enumerate(kf) if t >= self._cur_tick), len(kf) - 1)
        ))
        new_idx = max(0, min(len(kf) - 1, cur_idx + delta))
        self._goto_tick(kf[new_idx])

    def _speed_up(self) -> None:
        self._speed = min(32.0, self._speed * 2)
        self._speed_lbl.config(
            text=f"×{self._speed:.0f}" if self._speed >= 1 else f"×{self._speed:.2f}"
        )

    def _speed_down(self) -> None:
        self._speed = max(0.25, self._speed / 2)
        self._speed_lbl.config(
            text=f"×{self._speed:.0f}" if self._speed >= 1 else f"×{self._speed:.2f}"
        )

    def _on_slider(self, val: str) -> None:
        if self._reader is None or self._terrain_arr is None:
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
