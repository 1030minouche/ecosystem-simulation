"""
Écran SETUP — configuration terrain, espèces, durée et lancement.
"""
from __future__ import annotations

import glob
import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import numpy as np
from PIL import Image, ImageTk

from gui.app import (
    C_BG, C_PANEL, C_CARD, C_BORDER, C_ACCENT, C_DANGER,
    C_SUCCESS, C_TEXT, C_SUB, C_WARN, WIN_W, WIN_H,
)

PREVIEW_SIZE = 260  # taille du canvas de prévisualisation

_SPECIES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "species")

_PRESETS = ["default", "ile", "archipel", "montagne", "continent"]
_PRESET_LABELS = {
    "default":   "Défaut",
    "ile":       "Île",
    "archipel":  "Archipel",
    "montagne":  "Montagne",
    "continent": "Continent",
}

_GRID_SIZES = [200, 300, 500]

# Groupes d'espèces pour l'affichage
_GROUPS = [
    ("PLANTES",     ["herbe", "fougere", "champignon", "baies"]),
    ("HERBIVORES",  ["lapin", "campagnol", "cerf", "sanglier"]),
    ("PRÉDATEURS",  ["renard", "loup", "hibou", "aigle"]),
]


def _species_hex(color_list) -> str:
    r, g, b = [int(c * 255) for c in color_list]
    return f"#{r:02x}{g:02x}{b:02x}"


class SetupFrame(tk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=C_BG)
        self._app = app
        self._species_data: list[dict] = []
        self._species_vars: dict[str, dict] = {}  # name → {enabled, count_var}
        self._preview_img: ImageTk.PhotoImage | None = None
        self._preview_job: str | None = None

        self._load_species()
        self._build_ui()
        self._schedule_preview()

    # ── Chargement espèces ────────────────────────────────────────────────────

    def _load_species(self) -> None:
        for path in sorted(glob.glob(os.path.join(_SPECIES_DIR, "*.json"))):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            name = os.path.splitext(os.path.basename(path))[0]
            self._species_data.append({
                "file": name,
                "name": data["params"]["name"],
                "count_default": data["count"],
                "params": data["params"],
            })

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        app = self._app

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=C_PANEL, height=54)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header, text="◆ EcoSim", font=app.font("title"),
            bg=C_PANEL, fg=C_ACCENT,
        ).pack(side=tk.LEFT, padx=20, pady=10)

        tk.Label(
            header, text="Simulateur d'écosystème biologique",
            font=app.font("small"), bg=C_PANEL, fg=C_SUB,
        ).pack(side=tk.LEFT, pady=10)

        # ── Corps ─────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        left  = self._build_left(body)
        right = self._build_right(body)

        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ── Panneau gauche : terrain ──────────────────────────────────────────────

    def _build_left(self, parent: tk.Widget) -> tk.Frame:
        app = self._app
        frame = tk.Frame(parent, bg=C_PANEL, width=350)
        frame.pack_propagate(False)

        # Titre section
        _section_title(frame, "TERRAIN", app)

        # Canvas preview
        preview_frame = tk.Frame(frame, bg=C_BG, bd=0)
        preview_frame.pack(padx=16, pady=(4, 8))

        self._preview_canvas = tk.Canvas(
            preview_frame, width=PREVIEW_SIZE, height=PREVIEW_SIZE,
            bg="#000011", highlightthickness=1, highlightbackground=C_BORDER,
        )
        self._preview_canvas.pack()

        # Seed
        row_seed = tk.Frame(frame, bg=C_PANEL)
        row_seed.pack(fill=tk.X, padx=16, pady=3)
        tk.Label(row_seed, text="Seed", font=app.font("body"),
                 bg=C_PANEL, fg=C_SUB, width=10, anchor="w").pack(side=tk.LEFT)
        self._seed_var = tk.StringVar(value="42")
        seed_entry = tk.Entry(
            row_seed, textvariable=self._seed_var, width=10,
            bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
            relief=tk.FLAT, font=app.font("mono"),
            highlightthickness=1, highlightbackground=C_BORDER,
        )
        seed_entry.pack(side=tk.LEFT, padx=(0, 6))
        seed_entry.bind("<Return>", lambda _: self._schedule_preview())
        seed_entry.bind("<FocusOut>", lambda _: self._schedule_preview())

        # Preset
        row_preset = tk.Frame(frame, bg=C_PANEL)
        row_preset.pack(fill=tk.X, padx=16, pady=3)
        tk.Label(row_preset, text="Preset", font=app.font("body"),
                 bg=C_PANEL, fg=C_SUB, width=10, anchor="w").pack(side=tk.LEFT)
        self._preset_var = tk.StringVar(value="default")
        preset_menu = tk.OptionMenu(
            row_preset, self._preset_var,
            *_PRESETS,
            command=lambda _: self._schedule_preview(),
        )
        _style_option_menu(preset_menu, app)
        preset_menu.pack(side=tk.LEFT)

        # Taille grille
        row_size = tk.Frame(frame, bg=C_PANEL)
        row_size.pack(fill=tk.X, padx=16, pady=3)
        tk.Label(row_size, text="Grille", font=app.font("body"),
                 bg=C_PANEL, fg=C_SUB, width=10, anchor="w").pack(side=tk.LEFT)
        self._size_var = tk.IntVar(value=500)
        for sz in _GRID_SIZES:
            rb = tk.Radiobutton(
                row_size, text=str(sz), variable=self._size_var, value=sz,
                bg=C_PANEL, fg=C_TEXT, selectcolor=C_CARD,
                activebackground=C_PANEL, activeforeground=C_ACCENT,
                font=app.font("small"),
            )
            rb.pack(side=tk.LEFT, padx=2)

        # Bouton régénérer
        btn_regen = _button(frame, "↺  Régénérer", self._schedule_preview, app, color=C_SUB)
        btn_regen.pack(padx=16, pady=(8, 4), fill=tk.X)

        # Info biomes (label mis à jour)
        self._biome_lbl = tk.Label(
            frame, text="", font=app.font("small"),
            bg=C_PANEL, fg=C_SUB, justify=tk.LEFT, anchor="w", wraplength=320,
        )
        self._biome_lbl.pack(padx=16, pady=4, fill=tk.X)

        return frame

    # ── Panneau droit : espèces + config sim ──────────────────────────────────

    def _build_right(self, parent: tk.Widget) -> tk.Frame:
        app = self._app
        frame = tk.Frame(parent, bg=C_BG)

        # ── Espèces ───────────────────────────────────────────────────────────
        _section_title(frame, "ESPÈCES", app)

        species_outer = tk.Frame(frame, bg=C_BG)
        species_outer.pack(fill=tk.X, pady=(0, 8))

        # Lookup dict par file-name
        sp_by_file = {s["file"]: s for s in self._species_data}

        for group_label, files in _GROUPS:
            grp_frame = tk.Frame(species_outer, bg=C_PANEL, bd=0)
            grp_frame.pack(fill=tk.X, pady=(4, 0))

            tk.Label(
                grp_frame, text=f" {group_label}",
                font=app.font("small"), bg=C_BORDER, fg=C_SUB,
            ).pack(fill=tk.X)

            for fname in files:
                if fname not in sp_by_file:
                    continue
                sp = sp_by_file[fname]
                self._build_species_row(grp_frame, sp, app)

        # ── Paramètres simulation ─────────────────────────────────────────────
        _section_title(frame, "SIMULATION", app)

        sim_frame = tk.Frame(frame, bg=C_PANEL)
        sim_frame.pack(fill=tk.X, pady=(0, 8))

        # Durée
        row_ticks = tk.Frame(sim_frame, bg=C_PANEL)
        row_ticks.pack(fill=tk.X, padx=12, pady=6)
        tk.Label(row_ticks, text="Durée (ticks)", font=app.font("body"),
                 bg=C_PANEL, fg=C_SUB, width=16, anchor="w").pack(side=tk.LEFT)
        self._ticks_var = tk.StringVar(value="10000")
        tk.Entry(
            row_ticks, textvariable=self._ticks_var, width=10,
            bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
            relief=tk.FLAT, font=app.font("mono"),
            highlightthickness=1, highlightbackground=C_BORDER,
        ).pack(side=tk.LEFT)
        tk.Label(row_ticks, text="≈ 1 keyframe / 500 ticks",
                 font=app.font("small"), bg=C_PANEL, fg=C_SUB).pack(side=tk.LEFT, padx=8)

        # Fichier de sortie
        row_out = tk.Frame(sim_frame, bg=C_PANEL)
        row_out.pack(fill=tk.X, padx=12, pady=6)
        tk.Label(row_out, text="Fichier sortie", font=app.font("body"),
                 bg=C_PANEL, fg=C_SUB, width=16, anchor="w").pack(side=tk.LEFT)
        self._out_var = tk.StringVar(value="runs/sim.db")
        tk.Entry(
            row_out, textvariable=self._out_var, width=22,
            bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
            relief=tk.FLAT, font=app.font("mono"),
            highlightthickness=1, highlightbackground=C_BORDER,
        ).pack(side=tk.LEFT)
        tk.Button(
            row_out, text="…", command=self._browse_out,
            bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, cursor="hand2",
            font=app.font("small"), padx=6,
        ).pack(side=tk.LEFT, padx=4)

        # Bouton lancer
        launch_btn = _button(frame, "▶   LANCER LA SIMULATION",
                             self._on_launch, app, color=C_ACCENT, big=True)
        launch_btn.pack(fill=tk.X, pady=(4, 0))

        return frame

    def _build_species_row(self, parent: tk.Widget, sp: dict, app) -> None:
        row = tk.Frame(parent, bg=C_PANEL, pady=2)
        row.pack(fill=tk.X, padx=8, pady=1)

        # Point couleur
        hex_color = _species_hex(sp["params"]["color"])
        dot = tk.Canvas(row, width=14, height=14, bg=C_PANEL,
                        highlightthickness=0)
        dot.create_oval(2, 2, 12, 12, fill=hex_color, outline="")
        dot.pack(side=tk.LEFT, padx=(0, 4))

        # Checkbox activé
        enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            row, variable=enabled_var,
            bg=C_PANEL, activebackground=C_PANEL,
            selectcolor=C_CARD, cursor="hand2",
        ).pack(side=tk.LEFT)

        # Nom
        tk.Label(
            row, text=sp["name"], font=app.font("body"),
            bg=C_PANEL, fg=C_TEXT, width=12, anchor="w",
        ).pack(side=tk.LEFT)

        # Label "init:"
        tk.Label(row, text="init:", font=app.font("small"),
                 bg=C_PANEL, fg=C_SUB).pack(side=tk.LEFT, padx=(6, 2))

        # Spinbox count
        count_var = tk.StringVar(value=str(sp["count_default"]))
        sp_box = tk.Spinbox(
            row, from_=0, to=500, textvariable=count_var, width=5,
            bg=C_CARD, fg=C_TEXT, buttonbackground=C_BORDER,
            relief=tk.FLAT, font=app.font("mono"),
            highlightthickness=1, highlightbackground=C_BORDER,
        )
        sp_box.pack(side=tk.LEFT)

        # Bouton édition paramètres
        tk.Button(
            row, text="⚙", command=lambda s=sp: self._open_species_params_editor(s),
            bg=C_CARD, fg=C_SUB, relief=tk.FLAT, font=app.font("small"),
            cursor="hand2", padx=4, activebackground=C_BORDER,
        ).pack(side=tk.LEFT, padx=(4, 0))

        self._species_vars[sp["name"]] = {
            "enabled": enabled_var,
            "count":   count_var,
            "data":    sp,
        }

    def _open_species_params_editor(self, sp: dict) -> None:
        """Ouvre une fenêtre modale pour modifier les paramètres clés d'une espèce."""
        params = sp["params"]
        app    = self._app

        win = tk.Toplevel(app.root)
        win.title(f"Paramètres — {sp['name']}")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text=f"Espèce : {sp['name']}", font=app.font("body"),
                 bg=C_BG, fg=C_TEXT).pack(pady=(12, 4))

        fields = [
            ("reproduction_rate",    "Taux reproduction",     0.0, 1.0,   0.01),
            ("max_speed",            "Vitesse max",           0.5, 10.0,  0.1),
            ("perception_radius",    "Rayon perception",      2.0, 30.0,  0.5),
            ("max_energy",           "Énergie max",          50.0, 500.0, 5.0),
            ("mutation_rate",        "Taux mutation",         0.0, 0.5,   0.005),
            ("disease_resistance",   "Résistance maladie",   0.0, 1.0,   0.01),
        ]

        vars_: dict[str, tk.DoubleVar] = {}
        for key, label, lo, hi, step in fields:
            val = float(params.get(key, (lo + hi) / 2))
            var = tk.DoubleVar(value=val)
            vars_[key] = var

            row = tk.Frame(win, bg=C_BG)
            row.pack(fill=tk.X, padx=16, pady=3)
            tk.Label(row, text=label, width=22, anchor="w",
                     bg=C_BG, fg=C_TEXT, font=app.font("small")).pack(side=tk.LEFT)
            tk.Scale(row, variable=var, from_=lo, to=hi, resolution=step,
                     orient=tk.HORIZONTAL, length=200,
                     bg=C_CARD, fg=C_TEXT, troughcolor=C_BORDER,
                     highlightthickness=0, showvalue=True).pack(side=tk.LEFT)

        def _apply():
            for key, var in vars_.items():
                params[key] = round(var.get(), 4)
            win.destroy()

        btn_row = tk.Frame(win, bg=C_BG)
        btn_row.pack(pady=10)
        tk.Button(btn_row, text="Appliquer", command=_apply,
                  bg=C_ACCENT, fg=C_BG, relief=tk.FLAT,
                  font=app.font("body"), padx=12).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Annuler", command=win.destroy,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT,
                  font=app.font("body"), padx=12).pack(side=tk.LEFT, padx=6)

    # ── Prévisualisation terrain ──────────────────────────────────────────────

    def _schedule_preview(self, *_) -> None:
        if self._preview_job:
            self._app.root.after_cancel(self._preview_job)
        self._preview_job = self._app.root.after(300, self._generate_preview)

    def _generate_preview(self) -> None:
        self._preview_job = None
        threading.Thread(target=self._render_preview_bg, daemon=True).start()

    def _render_preview_bg(self) -> None:
        try:
            seed_str = self._seed_var.get().strip()
            seed = int(seed_str) if seed_str else 42
        except ValueError:
            seed = 42

        preset = self._preset_var.get()

        from world.grid import Grid
        from world.terrain import generate_terrain, BIOME_PALETTE

        size = 150
        grid = Grid(width=size, height=size)
        generate_terrain(grid, seed=seed, preset=preset)

        alt = np.array(grid.altitude)
        rgb = np.zeros((size, size, 3), dtype=np.uint8)
        for threshold, color in BIOME_PALETTE:
            mask = alt >= threshold
            rgb[mask] = color

        img = Image.fromarray(rgb, "RGB").resize(
            (PREVIEW_SIZE, PREVIEW_SIZE), Image.NEAREST
        )
        self._app.root.after(0, self._update_preview_canvas, img, seed, alt)

    def _update_preview_canvas(self, img: Image.Image, seed: int, alt: np.ndarray) -> None:
        self._preview_img = ImageTk.PhotoImage(img)
        self._preview_canvas.delete("all")
        self._preview_canvas.create_image(0, 0, anchor="nw", image=self._preview_img)

        water_pct  = float((alt < 0.30).mean() * 100)
        forest_pct = float(((alt >= 0.40) & (alt < 0.75)).mean() * 100)
        rock_pct   = float((alt >= 0.75).mean() * 100)
        self._biome_lbl.config(
            text=f"Seed {seed}  ·  Eau {water_pct:.0f}%  "
                 f"·  Forêt {forest_pct:.0f}%  ·  Roche {rock_pct:.0f}%"
        )

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse_out(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("Base SQLite", "*.db"), ("Tous", "*.*")],
            initialdir="runs",
            title="Fichier de sortie",
        )
        if path:
            self._out_var.set(path)

    def _on_launch(self) -> None:
        try:
            seed   = int(self._seed_var.get().strip() or "42")
            ticks  = int(self._ticks_var.get().strip() or "10000")
            size   = self._size_var.get()
            out    = self._out_var.get().strip() or "runs/sim.db"
        except ValueError:
            messagebox.showerror("Paramètre invalide",
                                 "Seed et durée doivent être des entiers.")
            return

        if ticks <= 0:
            messagebox.showerror("Paramètre invalide", "La durée doit être > 0.")
            return

        species_cfg = []
        for name, v in self._species_vars.items():
            try:
                count = int(v["count"].get())
            except ValueError:
                count = 0
            species_cfg.append({
                "enabled": v["enabled"].get(),
                "count":   count,
                "params":  v["data"]["params"],
            })

        config = {
            "seed":      seed,
            "ticks":     ticks,
            "grid_size": size,
            "preset":    self._preset_var.get(),
            "out_path":  out,
            "species":   species_cfg,
        }
        self._app.start_simulation(config)


# ── Helpers UI ────────────────────────────────────────────────────────────────

def _section_title(parent: tk.Widget, text: str, app) -> tk.Label:
    lbl = tk.Label(
        parent, text=f"  {text}",
        font=app.font("small"), bg=C_BORDER, fg=C_SUB,
        anchor="w",
    )
    lbl.pack(fill=tk.X, pady=(6, 0))
    return lbl


def _button(
    parent: tk.Widget, text: str, command,
    app, color: str = C_ACCENT, big: bool = False,
) -> tk.Button:
    font = app.font("h2") if big else app.font("body")
    btn = tk.Button(
        parent, text=text, command=command,
        bg=color, fg=C_BG if color in (C_ACCENT, C_SUCCESS) else C_TEXT,
        relief=tk.FLAT, cursor="hand2", font=font,
        activebackground=color, activeforeground=C_BG,
        pady=10 if big else 5,
    )
    return btn


def _style_option_menu(menu: tk.OptionMenu, app) -> None:
    menu.config(
        bg=C_CARD, fg=C_TEXT, relief=tk.FLAT,
        activebackground=C_BORDER, activeforeground=C_TEXT,
        highlightthickness=1, highlightbackground=C_BORDER,
        font=app.font("body"),
    )
    menu["menu"].config(
        bg=C_CARD, fg=C_TEXT,
        activebackground=C_ACCENT, activeforeground=C_BG,
        font=app.font("body"),
    )
