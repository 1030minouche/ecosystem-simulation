"""
Éditeur de terrain Python (tkinter).
Ouvert depuis main.py quand Unity envoie {"type": "open_terrain_editor"}.
Fournit une carte 2D interactive : cliquer/glisser applique l'outil sélectionné.
Les modifications sont envoyées en temps réel à Unity via les callbacks.
"""

import tkinter as tk
from tkinter import ttk
import threading
import copy
import random
import math
import numpy as np

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from world.terrain import (
    modify_altitude, paint_cell, draw_river, place_lake,
    generate_terrain, BIOME_PALETTE, altitude_to_rgb,
)


def _render_terrain(alt: np.ndarray, size: int) -> "ImageTk.PhotoImage or None":
    """Rend le terrain (numpy altitude HxW) en image tkinter (size×size)."""
    H, W = alt.shape
    gy = np.round(np.linspace(0, H - 1, size)).astype(int)
    gx = np.round(np.linspace(0, W - 1, size)).astype(int)
    sampled = alt[np.ix_(gy, gx)]          # (size, size)

    img = np.zeros((size, size, 3), dtype=np.uint8)
    for threshold, color in BIOME_PALETTE:
        img[sampled >= threshold] = color

    if _HAS_PIL:
        return ImageTk.PhotoImage(Image.fromarray(img, "RGB"))

    # Fallback sans PIL : PPM via fichier temp
    import tempfile, os
    ppm = b"P6\n" + f"{size} {size}\n255\n".encode() + img.tobytes()
    with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as f:
        f.write(ppm); fname = f.name
    photo = tk.PhotoImage(file=fname)
    os.unlink(fname)
    return photo


# ─────────────────────────────────────────────────────────────────────────────

class TerrainEditorGUI:

    TOOLS    = ["raise", "lower", "paint", "river", "lake", "regenerate"]
    TOOLS_FR = ["▲ Monter", "▼ Baisser", "🎨 Peindre",
                "〰 Rivière", "💧 Lac",    "🔄 Générer"]

    BIOMES    = ["water", "sand", "plain", "forest", "rock", "snow"]
    BIOMES_FR = ["Eau",  "Sable", "Plaine", "Forêt", "Roche", "Neige"]

    PRESETS    = ["default", "ile", "archipel", "montagne", "continent"]
    PRESETS_FR = ["Défaut",  "Île", "Archipel", "Montagne", "Continent"]

    MAP_SIZE = 420   # pixels de la carte 2D

    def __init__(self, grid, on_delta, on_full_terrain):
        """
        grid            : Grid Python (modifié en place par les outils)
        on_delta(list)  : callback → envoie terrain_delta à Unity
        on_full_terrain : callback → envoie terrain snapshot complet à Unity
        """
        self.grid             = grid
        self._on_delta        = on_delta
        self._on_full_terrain = on_full_terrain

        # Sauvegarde pour Annuler
        self._orig_alt   = grid.altitude.copy()
        self._orig_soil  = [[grid.cells[y][x].soil_type
                             for x in range(grid.width)]
                            for y in range(grid.height)]

        self._tool_idx   = 0
        self._biome_idx  = 2   # plaine
        self._preset_idx = 0
        self._radius     = 5
        self._seed       = 42
        self._confirmed  = False

        self._root      = None
        self._tk_img    = None   # référence pour éviter le GC
        self._tool_btns = []

    # ── API publique ──────────────────────────────────────────────────────────

    def run(self) -> str:
        """Bloque jusqu'à Confirmer ou Annuler. Retourne 'confirm' ou 'cancel'."""
        self._root = tk.Tk()
        self._root.title("EcoSim — Éditeur de Terrain")
        self._root.configure(bg="#0d0d1a")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._do_cancel)

        self._build_ui()
        self._refresh_canvas()

        self._root.mainloop()
        return "confirm" if self._confirmed else "cancel"

    # ── Construction de l'interface ───────────────────────────────────────────

    def _build_ui(self):
        # Conteneur principal : gauche (contrôles) | droite (carte)
        left  = tk.Frame(self._root, bg="#0d0d1a", width=260)
        right = tk.Frame(self._root, bg="#0d0d1a")
        left.pack (side=tk.LEFT, fill=tk.Y,    padx=10, pady=10)
        right.pack(side=tk.LEFT, fill=tk.BOTH, padx=10, pady=10)
        left.pack_propagate(False)

        # ── Titre ──────────────────────────────────────────────────────────
        tk.Label(left, text="🗺  ÉDITEUR DE TERRAIN",
                 bg="#0d0d1a", fg="#ffcc33",
                 font=("Arial", 12, "bold")).pack(pady=(0, 6))
        _sep(left)

        # ── Boutons d'outils (2 lignes × 3) ──────────────────────────────
        tframe = tk.Frame(left, bg="#0d0d1a")
        tframe.pack(fill=tk.X)
        for i, lbl in enumerate(self.TOOLS_FR):
            btn = tk.Button(tframe, text=lbl,
                            bg="#2a2a3a", fg="white",
                            font=("Arial", 9, "bold"),
                            relief=tk.FLAT, cursor="hand2",
                            command=lambda i=i: self._select_tool(i))
            btn.grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="ew")
            tframe.columnconfigure(i % 3, weight=1)
            self._tool_btns.append(btn)

        _sep(left)

        # ── Rayon ──────────────────────────────────────────────────────────
        row = tk.Frame(left, bg="#0d0d1a"); row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="Rayon :", bg="#0d0d1a", fg="white",
                 font=("Arial", 10)).pack(side=tk.LEFT)
        tk.Button(row, text="−", bg="#2a2a3a", fg="white", width=2,
                  relief=tk.FLAT, command=lambda: self._chg_radius(-1)
                  ).pack(side=tk.LEFT, padx=2)
        self._rad_lbl = tk.Label(row, text=str(self._radius),
                                  bg="#0d0d1a", fg="#ffcc44",
                                  font=("Arial", 10, "bold"), width=3)
        self._rad_lbl.pack(side=tk.LEFT)
        tk.Button(row, text="+", bg="#2a2a3a", fg="white", width=2,
                  relief=tk.FLAT, command=lambda: self._chg_radius(+1)
                  ).pack(side=tk.LEFT, padx=2)

        # ── Section Biome (visible si Paint) ──────────────────────────────
        self._biome_frame = tk.Frame(left, bg="#0d0d1a")
        self._biome_frame.pack(fill=tk.X, pady=2)
        tk.Label(self._biome_frame, text="Biome :",
                 bg="#0d0d1a", fg="white", font=("Arial", 10)).pack(side=tk.LEFT)
        tk.Button(self._biome_frame, text="◀", bg="#2a2a3a", fg="white",
                  relief=tk.FLAT, command=lambda: self._chg_biome(-1)
                  ).pack(side=tk.LEFT, padx=2)
        self._biome_lbl = tk.Label(self._biome_frame,
                                    text=self.BIOMES_FR[self._biome_idx],
                                    bg="#0d0d1a", fg="#ffcc44",
                                    font=("Arial", 10, "bold"), width=8)
        self._biome_lbl.pack(side=tk.LEFT)
        tk.Button(self._biome_frame, text="▶", bg="#2a2a3a", fg="white",
                  relief=tk.FLAT, command=lambda: self._chg_biome(+1)
                  ).pack(side=tk.LEFT, padx=2)

        # ── Section Régénération (visible si Générer) ──────────────────────
        self._regen_frame = tk.Frame(left, bg="#0d0d1a")
        self._regen_frame.pack(fill=tk.X, pady=2)

        pr = tk.Frame(self._regen_frame, bg="#0d0d1a"); pr.pack(fill=tk.X)
        tk.Label(pr, text="Preset :",
                 bg="#0d0d1a", fg="white", font=("Arial", 10)).pack(side=tk.LEFT)
        tk.Button(pr, text="◀", bg="#2a2a3a", fg="white",
                  relief=tk.FLAT, command=lambda: self._chg_preset(-1)
                  ).pack(side=tk.LEFT, padx=2)
        self._preset_lbl = tk.Label(pr, text=self.PRESETS_FR[self._preset_idx],
                                     bg="#0d0d1a", fg="#ffcc44",
                                     font=("Arial", 10, "bold"), width=10)
        self._preset_lbl.pack(side=tk.LEFT)
        tk.Button(pr, text="▶", bg="#2a2a3a", fg="white",
                  relief=tk.FLAT, command=lambda: self._chg_preset(+1)
                  ).pack(side=tk.LEFT, padx=2)

        sr = tk.Frame(self._regen_frame, bg="#0d0d1a"); sr.pack(fill=tk.X, pady=2)
        tk.Label(sr, text="Graine :",
                 bg="#0d0d1a", fg="white", font=("Arial", 10)).pack(side=tk.LEFT)
        tk.Button(sr, text="−", bg="#2a2a3a", fg="white", width=2,
                  relief=tk.FLAT, command=lambda: self._chg_seed(-1)
                  ).pack(side=tk.LEFT, padx=2)
        self._seed_lbl = tk.Label(sr, text=str(self._seed),
                                   bg="#0d0d1a", fg="white",
                                   font=("Arial", 10), width=5)
        self._seed_lbl.pack(side=tk.LEFT)
        tk.Button(sr, text="+", bg="#2a2a3a", fg="white", width=2,
                  relief=tk.FLAT, command=lambda: self._chg_seed(+1)
                  ).pack(side=tk.LEFT, padx=2)
        tk.Button(sr, text="🎲", bg="#2a2a3a", fg="white",
                  relief=tk.FLAT, command=self._random_seed
                  ).pack(side=tk.LEFT, padx=2)

        tk.Button(self._regen_frame, text="🔄  Générer ce terrain",
                  bg="#7a4a15", fg="white", font=("Arial", 10, "bold"),
                  relief=tk.FLAT, cursor="hand2",
                  command=self._do_regenerate
                  ).pack(fill=tk.X, pady=4)

        _sep(left)

        # ── Statut ─────────────────────────────────────────────────────────
        self._status_lbl = tk.Label(left,
            text="Cliquez sur la carte pour appliquer",
            bg="#0d0d1a", fg="#888888",
            font=("Arial", 9), wraplength=240, justify=tk.LEFT)
        self._status_lbl.pack(fill=tk.X, pady=4)

        _sep(left)

        # ── Confirmer / Annuler ────────────────────────────────────────────
        brow = tk.Frame(left, bg="#0d0d1a"); brow.pack(fill=tk.X, pady=8)
        tk.Button(brow, text="✓  Confirmer",
                  bg="#1e6b2e", fg="white", font=("Arial", 11, "bold"),
                  relief=tk.FLAT, cursor="hand2", command=self._do_confirm
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        tk.Button(brow, text="✗  Annuler",
                  bg="#6b1e1e", fg="white", font=("Arial", 11, "bold"),
                  relief=tk.FLAT, cursor="hand2", command=self._do_cancel
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        # ── Carte terrain (droite) ─────────────────────────────────────────
        s = self.MAP_SIZE
        self._canvas = tk.Canvas(right, width=s, height=s,
                                  bg="#000011", cursor="crosshair",
                                  highlightthickness=1,
                                  highlightbackground="#333355")
        self._canvas.pack()
        self._canvas.bind("<Button-1>",  self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<Motion>",    self._on_hover)

        # Légende sous la carte
        legend = f"Carte {self.grid.width}×{self.grid.height}  —  " \
                 f"cliquez / glissez pour appliquer l'outil"
        tk.Label(right, text=legend,
                 bg="#0d0d1a", fg="#555577", font=("Arial", 8)).pack(pady=(4, 0))

        # Sélection initiale
        self._select_tool(0)

    # ── Sélection d'outil ─────────────────────────────────────────────────────

    def _select_tool(self, idx: int):
        self._tool_idx = idx
        for i, btn in enumerate(self._tool_btns):
            btn.config(bg="#c89010" if i == idx else "#2a2a3a")

        is_paint  = (self.TOOLS[idx] == "paint")
        is_regen  = (self.TOOLS[idx] == "regenerate")
        is_radius = self.TOOLS[idx] not in ("river", "regenerate")

        # Montrer/cacher les sections contextuelles
        self._biome_frame.pack(fill=tk.X, pady=2) if is_paint \
            else self._biome_frame.pack_forget()
        self._regen_frame.pack(fill=tk.X, pady=2) if is_regen \
            else self._regen_frame.pack_forget()

        self._status_lbl.config(
            text="Cliquez sur la carte pour appliquer" if not is_regen
            else "Choisissez preset + graine puis cliquez 🔄 Générer")

    # ── Interactions carte ────────────────────────────────────────────────────

    def _canvas_to_grid(self, cx: int, cy: int):
        s = self.MAP_SIZE
        gx = int(cx / s * self.grid.width)
        gy = int(cy / s * self.grid.height)
        return (max(0, min(self.grid.width  - 1, gx)),
                max(0, min(self.grid.height - 1, gy)))

    def _apply_tool(self, cx: int, cy: int):
        gx, gy = self._canvas_to_grid(cx, cy)
        tool = self.TOOLS[self._tool_idx]

        if   tool == "raise":
            changes = modify_altitude(self.grid, gx, gy, self._radius,  0.05)
        elif tool == "lower":
            changes = modify_altitude(self.grid, gx, gy, self._radius, -0.05)
        elif tool == "paint":
            changes = paint_cell(self.grid, gx, gy, self._radius,
                                 self.BIOMES[self._biome_idx])
        elif tool == "river":
            changes = draw_river(self.grid, gx, gy)
        elif tool == "lake":
            changes = place_lake(self.grid, gx, gy, self._radius)
        else:
            return

        if changes:
            self._on_delta(changes)
            self._refresh_canvas()
            self._status_lbl.config(
                text=f"{self.TOOLS_FR[self._tool_idx]} @ ({gx}, {gy})")

    def _on_click(self, event):
        if self.TOOLS[self._tool_idx] != "regenerate":
            self._apply_tool(event.x, event.y)

    def _on_drag(self, event):
        if self.TOOLS[self._tool_idx] not in ("river", "lake", "regenerate"):
            self._apply_tool(event.x, event.y)

    def _on_hover(self, event):
        if self.TOOLS[self._tool_idx] == "regenerate":
            return
        gx, gy = self._canvas_to_grid(event.x, event.y)
        self._status_lbl.config(
            text=f"{self.TOOLS_FR[self._tool_idx]} — survol ({gx}, {gy})")

    # ── Régénération ──────────────────────────────────────────────────────────

    def _do_regenerate(self):
        generate_terrain(self.grid,
                         seed=self._seed,
                         preset=self.PRESETS[self._preset_idx])
        self._on_full_terrain()
        self._refresh_canvas()
        self._status_lbl.config(
            text=f"Terrain généré — preset={self.PRESETS_FR[self._preset_idx]}, graine={self._seed}")

    # ── Confirmer / Annuler ───────────────────────────────────────────────────

    def _do_confirm(self):
        self._confirmed = True
        self._root.destroy()

    def _do_cancel(self):
        # Restaurer l'état original
        np.copyto(self.grid.altitude, self._orig_alt)
        for y in range(self.grid.height):
            for x in range(self.grid.width):
                self.grid.cells[y][x].soil_type = self._orig_soil[y][x]
        self._on_full_terrain()
        self._confirmed = False
        self._root.destroy()

    # ── Rendu carte ───────────────────────────────────────────────────────────

    def _refresh_canvas(self):
        photo = _render_terrain(self.grid.altitude, self.MAP_SIZE)
        self._tk_img = photo          # empêcher le garbage collector
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor=tk.NW, image=photo)

    # ── Helpers paramètres ────────────────────────────────────────────────────

    def _chg_radius(self, d: int):
        self._radius = max(1, min(30, self._radius + d))
        self._rad_lbl.config(text=str(self._radius))

    def _chg_biome(self, d: int):
        self._biome_idx = (self._biome_idx + d) % len(self.BIOMES)
        self._biome_lbl.config(text=self.BIOMES_FR[self._biome_idx])

    def _chg_preset(self, d: int):
        self._preset_idx = (self._preset_idx + d) % len(self.PRESETS)
        self._preset_lbl.config(text=self.PRESETS_FR[self._preset_idx])

    def _chg_seed(self, d: int):
        self._seed = max(0, min(9999, self._seed + d))
        self._seed_lbl.config(text=str(self._seed))

    def _random_seed(self):
        self._seed = random.randint(0, 9999)
        self._seed_lbl.config(text=str(self._seed))


# ── Helpers UI ────────────────────────────────────────────────────────────────

def _sep(parent):
    f = tk.Frame(parent, bg="#333355", height=1)
    f.pack(fill=tk.X, pady=4)
