#!/usr/bin/env python3
"""
EcoSim — Éditeur d'espèces
Création, modification, suppression des fichiers JSON d'espèces.
Lancer directement ou via lancer_editeur_especes.bat
"""
from __future__ import annotations

import json
from pathlib import Path
from tkinter import colorchooser, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Optional

# ── Chemin vers le dossier espèces ────────────────────────────────────────────
SPECIES_DIR = Path(__file__).parent.parent / "species"

# ── Constantes ────────────────────────────────────────────────────────────────
TYPES            = ["plant", "herbivore", "carnivore", "omnivore"]
ACTIVITY_PATTERNS = ["diurnal", "crepuscular", "nocturnal"]
ACTIVITY_LABELS   = {"diurnal": "Diurne", "crepuscular": "Crépusculaire", "nocturnal": "Nocturne"}
TYPE_EMOJI        = {"plant": "🌿", "herbivore": "🐾", "carnivore": "🦊", "omnivore": "⚙", "": "❓"}

DAY_TICKS = 1_200   # ticks par jour simulé (1 min réelle à ×1)

def _ticks_to_days(t: int) -> str:
    """'36000t = 30.0 j'"""
    return f"= {t / DAY_TICKS:.1f} j sim"

# Valeurs par défaut pour une nouvelle espèce
DEFAULTS: dict = {
    "count": 50,
    "params": {
        "name": "NouvelleEspece",
        "type": "herbivore",
        "color": [0.7, 0.7, 0.7],
        "temp_min": 0.0,    "temp_max": 40.0,
        "humidity_min": 0.0, "humidity_max": 1.0,
        "altitude_min": 0.3, "altitude_max": 0.75,
        "growth_rate": 0.0,             "growth_rate_std": 0.0,
        "max_age": 438_000,             "max_age_std": 0,
        "reproduction_rate": 0.8,       "reproduction_rate_std": 0.0,
        "max_population": 200,
        "energy_start": 100.0,          "energy_start_std": 0.0,
        "energy_consumption": 0.05,     "energy_consumption_std": 0.0,
        "energy_from_food": 50.0,       "energy_from_food_std": 0.0,
        "speed": 1.0,                   "speed_std": 0.0,
        "perception_radius": 8.0,       "perception_radius_std": 0.0,
        "food_sources": [],
        "dispersal_radius": 0,
        "activity_pattern": "diurnal",
        "can_swim": False,
        "reproduction_cooldown_length": 60_000, "reproduction_cooldown_length_std": 0,
        "litter_size_min": 1,
        "litter_size_max": 3,
        "sexual_maturity_ticks": 0,     "sexual_maturity_ticks_std": 0,
        "gestation_ticks": 0,           "gestation_ticks_std": 0,
        "juvenile_mortality_rate": 0.0, "juvenile_mortality_rate_std": 0.0,
        "fear_factor": 0.0,             "fear_factor_std": 0.0,
        "herd_cohesion": 0.0,
    },
}

# ── Palette de couleurs (style Catppuccin Mocha) ───────────────────────────────
C = {
    "base":    "#1e1e2e",
    "mantle":  "#181825",
    "surface": "#313244",
    "overlay": "#45475a",
    "muted":   "#6c7086",
    "subtext": "#a6adc8",
    "text":    "#cdd6f4",
    "blue":    "#89b4fa",
    "green":   "#a6e3a1",
    "red":     "#f38ba8",
    "yellow":  "#f9e2af",
    "teal":    "#94e2d5",
    "sky":     "#89dceb",
    "peach":   "#fab387",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers UI
# ──────────────────────────────────────────────────────────────────────────────

def _apply_theme(root: tk.Tk) -> None:
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".",
        background=C["base"], foreground=C["text"],
        font=("Segoe UI", 10), borderwidth=0, relief="flat")
    s.configure("TFrame",      background=C["base"])
    s.configure("TLabel",      background=C["base"],    foreground=C["text"])
    s.configure("TEntry",      fieldbackground=C["surface"], foreground=C["text"],
                               insertcolor=C["text"], borderwidth=1, relief="solid")
    s.configure("TCombobox",   fieldbackground=C["surface"], foreground=C["text"],
                               selectbackground=C["overlay"], borderwidth=1)
    s.configure("TCheckbutton", background=C["base"],   foreground=C["text"])
    s.configure("TScrollbar",  background=C["surface"], troughcolor=C["mantle"],
                               arrowcolor=C["subtext"])
    s.configure("TLabelframe",
        background=C["base"], foreground=C["blue"],
        bordercolor=C["overlay"], borderwidth=1, relief="solid")
    s.configure("TLabelframe.Label",
        background=C["base"], foreground=C["blue"],
        font=("Segoe UI", 10, "bold"))
    s.map("TEntry",    fieldbackground=[("focus", C["overlay"])])
    s.map("TCombobox", fieldbackground=[("focus", C["overlay"])])


def _btn(parent: tk.Widget, text: str, cmd, bg: str, fg: str = C["base"],
         **kw) -> tk.Button:
    kw.setdefault("font",  ("Segoe UI", 9, "bold"))
    kw.setdefault("padx",  8)
    kw.setdefault("pady",  4)
    return tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
        relief=tk.FLAT, cursor="hand2", **kw
    )


def _label(parent: tk.Widget, text: str, fg: str = C["subtext"],
           **kw) -> tk.Label:
    kw.setdefault("bg", C["base"])
    return tk.Label(parent, text=text, fg=fg, **kw)


# ──────────────────────────────────────────────────────────────────────────────
# Classe principale
# ──────────────────────────────────────────────────────────────────────────────

class SpeciesEditor:

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EcoSim — Éditeur d'espèces")
        self.root.configure(bg=C["base"])
        self.root.geometry("1100x820")
        self.root.minsize(880, 620)

        _apply_theme(root)

        self._current_stem: Optional[str] = None
        self._file_stems:   list[str]     = []

        self._build_layout()
        self._refresh_list()

    # ── Construction de l'interface ───────────────────────────────────────────

    def _build_layout(self) -> None:
        paned = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL,
            bg=C["base"], sashwidth=6, sashrelief=tk.FLAT, sashpad=0,
        )
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left  = self._build_left_panel(paned)
        right = self._build_right_panel(paned)

        paned.add(left,  minsize=170, width=195)
        paned.add(right, minsize=600)

    # ── Panneau gauche ────────────────────────────────────────────────────────

    def _build_left_panel(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=C["mantle"])

        _label(frame, "Espèces", fg=C["blue"],
               font=("Segoe UI", 13, "bold"), bg=C["mantle"]
               ).pack(pady=(14, 6), padx=12, anchor="w")

        lb_frame = tk.Frame(frame, bg=C["mantle"])
        lb_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)

        sb = tk.Scrollbar(lb_frame, bg=C["surface"], troughcolor=C["mantle"],
                          relief=tk.FLAT, width=8)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(
            lb_frame, yscrollcommand=sb.set,
            bg=C["mantle"], fg=C["text"],
            selectbackground=C["overlay"], selectforeground=C["text"],
            font=("Segoe UI", 11), relief=tk.FLAT, borderwidth=0,
            activestyle="none", highlightthickness=0,
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        btn_frame = tk.Frame(frame, bg=C["mantle"])
        btn_frame.pack(fill=tk.X, padx=6, pady=8)

        _btn(btn_frame, "＋  Nouvelle",   self._new_species,       C["green"]  ).pack(fill=tk.X, pady=(0, 3))
        _btn(btn_frame, "⎘  Dupliquer",   self._duplicate_species, C["sky"]    ).pack(fill=tk.X, pady=(0, 3))
        _btn(btn_frame, "✕  Supprimer",   self._delete_species,    C["red"]    ).pack(fill=tk.X)

        return frame

    # ── Panneau droit ─────────────────────────────────────────────────────────

    def _build_right_panel(self, parent: tk.Widget) -> tk.Frame:
        outer = tk.Frame(parent, bg=C["base"])

        canvas  = tk.Canvas(outer, bg=C["base"], highlightthickness=0)
        vscroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)

        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._form    = tk.Frame(canvas, bg=C["base"])
        self._form_id = canvas.create_window((0, 0), window=self._form, anchor="nw")

        self._form.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._form_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self._build_form(self._form)
        return outer

    # ── Formulaire ────────────────────────────────────────────────────────────

    def _build_form(self, p: tk.Frame) -> None:

        def section(label: str) -> ttk.LabelFrame:
            f = ttk.LabelFrame(p, text=f"  {label}  ")
            f.pack(fill=tk.X, padx=12, pady=(10, 0))
            return f

        def field_row(parent, label: str, var: tk.Variable,
                      width: int = 14, hint: str = "",
                      v_std: tk.Variable = None) -> ttk.Entry:
            """Ligne label + Entry [± σ] [+ hint en muted]."""
            row = tk.Frame(parent, bg=C["base"])
            row.pack(fill=tk.X, padx=10, pady=2)
            _label(row, label, width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
            e = ttk.Entry(row, textvariable=var, width=width)
            e.pack(side=tk.LEFT)
            if v_std is not None:
                _label(row, "± σ", fg=C["muted"],
                       font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(6, 2))
                ttk.Entry(row, textvariable=v_std, width=10).pack(side=tk.LEFT)
            if hint:
                _label(row, hint, fg=C["muted"],
                       font=("Segoe UI", 8, "italic")).pack(side=tk.LEFT, padx=(6, 0))
            return e

        def tick_row(parent, label: str, var: tk.StringVar, width: int = 14, hint: str = "",
                     v_std: tk.Variable = None) -> None:
            """Ligne avec Entry ticks + label de conversion auto [± σ]."""
            row = tk.Frame(parent, bg=C["base"])
            row.pack(fill=tk.X, padx=10, pady=2)
            _label(row, label, width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
            ttk.Entry(row, textvariable=var, width=width).pack(side=tk.LEFT)
            conv = _label(row, "", fg=C["muted"], font=("Segoe UI", 8, "italic"))
            conv.pack(side=tk.LEFT, padx=(6, 0))
            if v_std is not None:
                _label(row, "± σ", fg=C["muted"],
                       font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(8, 2))
                ttk.Entry(row, textvariable=v_std, width=10).pack(side=tk.LEFT)
            if hint:
                _label(row, hint, fg=C["muted"], font=("Segoe UI", 8, "italic")).pack(side=tk.LEFT, padx=(8, 0))

            def _update_conv(*_):
                try:
                    t = int(var.get())
                    conv.config(text=_ticks_to_days(t))
                except ValueError:
                    conv.config(text="")
            var.trace_add("write", _update_conv)

        def range_row(parent, label: str, v_min: tk.Variable, v_max: tk.Variable) -> None:
            row = tk.Frame(parent, bg=C["base"])
            row.pack(fill=tk.X, padx=10, pady=2)
            _label(row, label, width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
            ttk.Entry(row, textvariable=v_min, width=9).pack(side=tk.LEFT)
            _label(row, "→", fg=C["muted"]).pack(side=tk.LEFT, padx=4)
            ttk.Entry(row, textvariable=v_max, width=9).pack(side=tk.LEFT)

        # ── Identité ──────────────────────────────────────────────────────────
        sec_id = section("Identité")

        self.v_name = tk.StringVar()
        row_name = tk.Frame(sec_id, bg=C["base"])
        row_name.pack(fill=tk.X, padx=10, pady=2)
        _label(row_name, "Nom", width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(row_name, textvariable=self.v_name,
                  font=("Segoe UI", 11, "bold"), width=22).pack(side=tk.LEFT)

        self.v_type = tk.StringVar()
        row_type = tk.Frame(sec_id, bg=C["base"])
        row_type.pack(fill=tk.X, padx=10, pady=2)
        _label(row_type, "Type", width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
        self.combo_type = ttk.Combobox(
            row_type, textvariable=self.v_type,
            values=TYPES, state="readonly", width=16,
        )
        self.combo_type.pack(side=tk.LEFT)
        self.combo_type.bind("<<ComboboxSelected>>", self._on_type_changed)

        # Couleur
        self.v_cr = tk.StringVar(); self.v_cg = tk.StringVar(); self.v_cb = tk.StringVar()
        row_col = tk.Frame(sec_id, bg=C["base"])
        row_col.pack(fill=tk.X, padx=10, pady=(2, 8))
        _label(row_col, "Couleur (R G B)", width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
        for v in (self.v_cr, self.v_cg, self.v_cb):
            ttk.Entry(row_col, textvariable=v, width=7).pack(side=tk.LEFT, padx=2)
        self.color_swatch = tk.Label(
            row_col, text="      ", bg="#aaaaaa",
            cursor="hand2", relief=tk.FLAT, width=4,
        )
        self.color_swatch.pack(side=tk.LEFT, padx=(8, 0), ipadx=2, ipady=2)
        self.color_swatch.bind("<Button-1>", self._pick_color)
        _label(row_col, "← cliquer", fg=C["muted"],
               font=("Segoe UI", 8, "italic")).pack(side=tk.LEFT, padx=4)

        for v in (self.v_cr, self.v_cg, self.v_cb):
            v.trace_add("write", self._sync_color_swatch)

        # ── Population de base ────────────────────────────────────────────────
        sec_pop = section("Population")
        self.v_count          = tk.StringVar()
        self.v_max_pop        = tk.StringVar()
        self.v_max_age        = tk.StringVar()
        self.v_max_age_std    = tk.StringVar()
        self.v_repro_rate     = tk.StringVar()
        self.v_repro_rate_std = tk.StringVar()
        field_row(sec_pop, "Count initial",            self.v_count)
        field_row(sec_pop, "Population max",           self.v_max_pop)
        tick_row (sec_pop, "Âge max (ticks)",          self.v_max_age,    v_std=self.v_max_age_std)
        field_row(sec_pop, "Taux reproduction [0–1]",  self.v_repro_rate, v_std=self.v_repro_rate_std)
        tk.Frame(sec_pop, bg=C["base"], height=4).pack()

        # ── Reproduction biologique avancée ───────────────────────────────────
        self.sec_repro = section("Reproduction biologique")
        self.v_repro_cd             = tk.StringVar()
        self.v_repro_cd_std         = tk.StringVar()
        self.v_litter_min           = tk.StringVar()
        self.v_litter_max           = tk.StringVar()
        self.v_sexual_maturity      = tk.StringVar()
        self.v_sexual_maturity_std  = tk.StringVar()
        self.v_gestation            = tk.StringVar()
        self.v_gestation_std        = tk.StringVar()

        tick_row (self.sec_repro, "Cooldown repro (ticks)",   self.v_repro_cd,
                  hint="après la naissance", v_std=self.v_repro_cd_std)
        range_row(self.sec_repro, "Taille portée (min → max)",
                  self.v_litter_min, self.v_litter_max)
        tick_row (self.sec_repro, "Maturité sexuelle (ticks)", self.v_sexual_maturity,
                  v_std=self.v_sexual_maturity_std)
        tick_row (self.sec_repro, "Gestation (ticks)",         self.v_gestation,
                  v_std=self.v_gestation_std)
        tk.Frame(self.sec_repro, bg=C["base"], height=4).pack()

        # ── Mortalité ─────────────────────────────────────────────────────────
        self.sec_mortalite = section("Mortalité")
        self.v_juv_mort        = tk.StringVar()
        self.v_juv_mort_std    = tk.StringVar()
        self.v_fear_factor     = tk.StringVar()
        self.v_fear_factor_std = tk.StringVar()
        field_row(self.sec_mortalite, "Mortalité juvénile/tick",
                  self.v_juv_mort, v_std=self.v_juv_mort_std,
                  hint="(ex : 1.28e-5 → 75% meurent avant maturité)")
        field_row(self.sec_mortalite, "Facteur de peur",
                  self.v_fear_factor, v_std=self.v_fear_factor_std,
                  hint="(0 = aucun | 3 = fort | formule : rate÷(1+k·n_pred))")
        tk.Frame(self.sec_mortalite, bg=C["base"], height=4).pack()

        # ── Énergie ───────────────────────────────────────────────────────────
        sec_nrj = section("Énergie")
        self.v_nrj_start     = tk.StringVar()
        self.v_nrj_start_std = tk.StringVar()
        self.v_nrj_conso     = tk.StringVar()
        self.v_nrj_conso_std = tk.StringVar()
        self.v_nrj_food      = tk.StringVar()
        self.v_nrj_food_std  = tk.StringVar()
        field_row(sec_nrj, "Énergie de départ",  self.v_nrj_start, v_std=self.v_nrj_start_std)
        field_row(sec_nrj, "Consommation/tick",  self.v_nrj_conso, v_std=self.v_nrj_conso_std)
        field_row(sec_nrj, "Gain par repas",     self.v_nrj_food,  v_std=self.v_nrj_food_std)
        tk.Frame(sec_nrj, bg=C["base"], height=4).pack()

        # ── Survie environnementale ───────────────────────────────────────────
        self.sec_survie = section("Survie environnementale")
        self.v_temp_min = tk.StringVar(); self.v_temp_max = tk.StringVar()
        self.v_hum_min  = tk.StringVar(); self.v_hum_max  = tk.StringVar()
        self.v_alt_min  = tk.StringVar(); self.v_alt_max  = tk.StringVar()
        range_row(self.sec_survie, "Température (°C)", self.v_temp_min, self.v_temp_max)
        range_row(self.sec_survie, "Humidité [0–1]",   self.v_hum_min,  self.v_hum_max)
        range_row(self.sec_survie, "Altitude [0–1]",   self.v_alt_min,  self.v_alt_max)
        tk.Frame(self.sec_survie, bg=C["base"], height=4).pack()

        # ── Section animaux ───────────────────────────────────────────────────
        self.sec_animal = section("Comportement — Animaux")
        self.v_speed          = tk.StringVar()
        self.v_speed_std      = tk.StringVar()
        self.v_perception     = tk.StringVar()
        self.v_perception_std = tk.StringVar()
        field_row(self.sec_animal, "Vitesse",          self.v_speed,      v_std=self.v_speed_std)
        field_row(self.sec_animal, "Rayon perception", self.v_perception, v_std=self.v_perception_std)

        # Sources de nourriture
        fs_row = tk.Frame(self.sec_animal, bg=C["base"])
        fs_row.pack(fill=tk.X, padx=10, pady=4)
        _label(fs_row, "Sources nourriture", width=26, anchor="e"
               ).pack(side=tk.LEFT, padx=(0, 6))

        fs_right = tk.Frame(fs_row, bg=C["base"])
        fs_right.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.food_lb = tk.Listbox(
            fs_right, height=3,
            bg=C["surface"], fg=C["text"],
            selectbackground=C["overlay"], selectforeground=C["text"],
            font=("Segoe UI", 9), relief=tk.FLAT, highlightthickness=0,
        )
        self.food_lb.pack(side=tk.LEFT, fill=tk.X, expand=True)

        fs_ctrl = tk.Frame(fs_right, bg=C["base"])
        fs_ctrl.pack(side=tk.LEFT, padx=(6, 0))
        self.v_food_input = tk.StringVar()
        ttk.Entry(fs_ctrl, textvariable=self.v_food_input, width=12).pack(pady=(0, 3))
        _btn(fs_ctrl, "＋", self._add_food,    C["blue"],  width=4).pack(pady=(0, 3))
        _btn(fs_ctrl, "✕", self._remove_food, C["red"],   width=4).pack()

        # Rythme d'activité + options
        act_row = tk.Frame(self.sec_animal, bg=C["base"])
        act_row.pack(fill=tk.X, padx=10, pady=(4, 2))
        _label(act_row, "Rythme d'activité", width=26, anchor="e").pack(side=tk.LEFT, padx=(0, 6))
        self.v_activity = tk.StringVar(value="diurnal")
        self.combo_activity = ttk.Combobox(
            act_row, textvariable=self.v_activity,
            values=ACTIVITY_PATTERNS, state="readonly", width=16,
        )
        self.combo_activity.pack(side=tk.LEFT)
        _label(act_row,
               "diurne · crépusculaire · nocturne",
               fg=C["muted"], font=("Segoe UI", 8, "italic"),
               ).pack(side=tk.LEFT, padx=(8, 0))

        chk_row = tk.Frame(self.sec_animal, bg=C["base"])
        chk_row.pack(fill=tk.X, padx=10, pady=(2, 4))
        tk.Label(chk_row, text="", width=26, bg=C["base"]).pack(side=tk.LEFT)
        self.v_can_swim = tk.BooleanVar()
        ttk.Checkbutton(chk_row, text="Peut nager", variable=self.v_can_swim).pack(side=tk.LEFT)

        self.v_herd_cohesion = tk.StringVar()
        field_row(self.sec_animal, "Cohésion troupeau",
                  self.v_herd_cohesion,
                  hint="(0 = solitaire · 1 = colle au groupe)")

        # ── Section plantes ───────────────────────────────────────────────────
        self.sec_plant = section("Comportement — Plantes")
        self.v_growth_rate     = tk.StringVar()
        self.v_growth_rate_std = tk.StringVar()
        self.v_dispersal_rad   = tk.StringVar()
        field_row(self.sec_plant, "Taux croissance/tick",
                  self.v_growth_rate, v_std=self.v_growth_rate_std,
                  hint="(ex : 0.000025 ≈ 3%/j sim)")
        field_row(self.sec_plant, "Rayon dispersion",    self.v_dispersal_rad)
        tk.Frame(self.sec_plant, bg=C["base"], height=4).pack()

        # ── Barre de sauvegarde ───────────────────────────────────────────────
        self.save_bar = tk.Frame(p, bg=C["base"])
        self.save_bar.pack(fill=tk.X, padx=12, pady=14)

        _btn(self.save_bar, "💾  Sauvegarder", self._save,
             C["green"], font=("Segoe UI", 11, "bold"), padx=14, pady=6,
             ).pack(side=tk.LEFT, padx=(0, 8))
        _btn(self.save_bar, "↺  Annuler", self._revert,
             C["overlay"], fg=C["text"], font=("Segoe UI", 11), padx=14, pady=6,
             ).pack(side=tk.LEFT)

        self.status_lbl = _label(
            self.save_bar, "", fg=C["subtext"],
            font=("Segoe UI", 9, "italic"),
        )
        self.status_lbl.pack(side=tk.RIGHT, padx=10)

        self._on_type_changed()

    # ── Liste des espèces ─────────────────────────────────────────────────────

    def _refresh_list(self, select_stem: Optional[str] = None) -> None:
        self.listbox.delete(0, tk.END)
        self._file_stems = []
        for path in sorted(SPECIES_DIR.glob("*.json")):
            try:
                data  = json.loads(path.read_text(encoding="utf-8"))
                name  = data.get("params", {}).get("name",  path.stem)
                stype = data.get("params", {}).get("type",  "")
                emoji = TYPE_EMOJI.get(stype, "❓")
                self.listbox.insert(tk.END, f"  {emoji}  {name}")
                self._file_stems.append(path.stem)
            except Exception:
                pass

        if select_stem and select_stem in self._file_stems:
            idx = self._file_stems.index(select_stem)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _on_list_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        stem = self._file_stems[sel[0]]
        if stem == self._current_stem:
            return
        self._load_into_form(stem)

    # ── Chargement depuis JSON ────────────────────────────────────────────────

    def _load_into_form(self, stem: str) -> None:
        path = SPECIES_DIR / f"{stem}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("Erreur lecture", f"Impossible de lire {stem}.json :\n{e}")
            return

        p = data.get("params", {})
        self._current_stem = stem

        self.v_name.set(p.get("name", ""))
        self.v_type.set(p.get("type", "herbivore"))

        c = p.get("color", [0.7, 0.7, 0.7])
        self.v_cr.set(str(round(c[0], 4)))
        self.v_cg.set(str(round(c[1], 4)))
        self.v_cb.set(str(round(c[2], 4)))

        self.v_count.set(          str(data.get("count", 50)))
        self.v_max_pop.set(        str(p.get("max_population",           200)))
        self.v_max_age.set(        str(p.get("max_age",             438_000)))
        self.v_max_age_std.set(    str(p.get("max_age_std",               0)))
        self.v_repro_rate.set(     str(p.get("reproduction_rate",         0.8)))
        self.v_repro_rate_std.set( str(p.get("reproduction_rate_std",     0.0)))

        self.v_repro_cd.set(            str(p.get("reproduction_cooldown_length",      60_000)))
        self.v_repro_cd_std.set(        str(p.get("reproduction_cooldown_length_std",  0)))
        self.v_litter_min.set(          str(p.get("litter_size_min",                  1)))
        self.v_litter_max.set(          str(p.get("litter_size_max",                  1)))
        self.v_sexual_maturity.set(     str(p.get("sexual_maturity_ticks",             0)))
        self.v_sexual_maturity_std.set( str(p.get("sexual_maturity_ticks_std",         0)))
        self.v_gestation.set(           str(p.get("gestation_ticks",                  0)))
        self.v_gestation_std.set(       str(p.get("gestation_ticks_std",               0)))
        self.v_juv_mort.set(            str(p.get("juvenile_mortality_rate",           0.0)))
        self.v_juv_mort_std.set(        str(p.get("juvenile_mortality_rate_std",       0.0)))
        self.v_fear_factor.set(         str(p.get("fear_factor",                       0.0)))
        self.v_fear_factor_std.set(     str(p.get("fear_factor_std",                   0.0)))
        self.v_herd_cohesion.set(       str(p.get("herd_cohesion",                     0.0)))

        self.v_nrj_start.set(    str(p.get("energy_start",          100.0)))
        self.v_nrj_start_std.set(str(p.get("energy_start_std",        0.0)))
        self.v_nrj_conso.set(    str(p.get("energy_consumption",      0.05)))
        self.v_nrj_conso_std.set(str(p.get("energy_consumption_std",  0.0)))
        self.v_nrj_food.set(     str(p.get("energy_from_food",       50.0)))
        self.v_nrj_food_std.set( str(p.get("energy_from_food_std",    0.0)))

        self.v_temp_min.set(str(p.get("temp_min",     0.0)))
        self.v_temp_max.set(str(p.get("temp_max",    40.0)))
        self.v_hum_min.set( str(p.get("humidity_min", 0.0)))
        self.v_hum_max.set( str(p.get("humidity_max", 1.0)))
        self.v_alt_min.set( str(p.get("altitude_min", 0.3)))
        self.v_alt_max.set( str(p.get("altitude_max", 0.75)))

        self.v_speed.set(          str(p.get("speed",                1.0)))
        self.v_speed_std.set(      str(p.get("speed_std",             0.0)))
        self.v_perception.set(     str(p.get("perception_radius",     8.0)))
        self.v_perception_std.set( str(p.get("perception_radius_std", 0.0)))

        # activity_pattern — compat ascendante avec l'ancien champ nocturnal
        if "activity_pattern" in p:
            act = p["activity_pattern"]
        elif p.get("nocturnal", False):
            act = "nocturnal"
        else:
            act = "diurnal"
        self.v_activity.set(act if act in ACTIVITY_PATTERNS else "diurnal")

        self.v_can_swim.set(bool(p.get("can_swim", False)))

        self.food_lb.delete(0, tk.END)
        for src in p.get("food_sources", []):
            self.food_lb.insert(tk.END, src)

        self.v_growth_rate.set(     str(p.get("growth_rate",      0.0)))
        self.v_growth_rate_std.set( str(p.get("growth_rate_std",  0.0)))
        self.v_dispersal_rad.set(   str(p.get("dispersal_radius",   0)))

        self._on_type_changed()
        self._set_status(f"Chargé : {stem}.json")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _new_species(self) -> None:
        d    = dict(DEFAULTS["params"])
        stem = self._unique_stem("nouvelle_espece")
        (SPECIES_DIR / f"{stem}.json").write_text(
            json.dumps({"count": DEFAULTS["count"], "params": d}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._refresh_list(select_stem=stem)
        self._load_into_form(stem)

    def _duplicate_species(self) -> None:
        if self._current_stem is None:
            messagebox.showwarning("Aucune sélection", "Sélectionne une espèce à dupliquer.")
            return
        src_path = SPECIES_DIR / f"{self._current_stem}.json"
        data = json.loads(src_path.read_text(encoding="utf-8"))
        data["params"]["name"] = data["params"]["name"] + "_copie"
        stem = self._unique_stem(self._current_stem + "_copie")
        (SPECIES_DIR / f"{stem}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._refresh_list(select_stem=stem)
        self._load_into_form(stem)

    def _delete_species(self) -> None:
        if self._current_stem is None:
            messagebox.showwarning("Aucune sélection", "Sélectionne une espèce à supprimer.")
            return
        name = self.v_name.get() or self._current_stem
        if not messagebox.askyesno(
            "Confirmer la suppression",
            f"Supprimer définitivement « {name} » ?\nCette action est irréversible.",
        ):
            return
        (SPECIES_DIR / f"{self._current_stem}.json").unlink(missing_ok=True)
        self._current_stem = None
        self._refresh_list()
        self._clear_form()
        self._set_status("Espèce supprimée.")

    def _save(self) -> None:
        errors = self._validate()
        if errors:
            messagebox.showerror("Erreurs de validation", "\n".join(errors))
            return

        data     = self._collect()
        name     = data["params"]["name"]
        new_stem = name.lower().replace(" ", "_")
        new_path = SPECIES_DIR / f"{new_stem}.json"
        old_path = (SPECIES_DIR / f"{self._current_stem}.json"
                    if self._current_stem else None)

        if new_path.exists() and new_path != old_path:
            if not messagebox.askyesno("Fichier existant",
                                       f"{new_stem}.json existe déjà.\nL'écraser ?"):
                return

        new_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if old_path and old_path != new_path and old_path.exists():
            old_path.unlink()

        self._current_stem = new_stem
        self._refresh_list(select_stem=new_stem)
        self._set_status(f"✓ Sauvegardé : {new_stem}.json")

    def _revert(self) -> None:
        if self._current_stem:
            self._load_into_form(self._current_stem)
        else:
            self._clear_form()
        self._set_status("Modifications annulées.")

    # ── Collecte des données du formulaire ────────────────────────────────────

    def _collect(self) -> dict:
        def f(v: tk.StringVar) -> float: return float(v.get())
        def i(v: tk.StringVar) -> int:   return int(v.get())

        return {
            "count": i(self.v_count),
            "params": {
                "name":                              self.v_name.get().strip(),
                "type":                              self.v_type.get(),
                "color":                             [f(self.v_cr), f(self.v_cg), f(self.v_cb)],
                "temp_min":                          f(self.v_temp_min),
                "temp_max":                          f(self.v_temp_max),
                "humidity_min":                      f(self.v_hum_min),
                "humidity_max":                      f(self.v_hum_max),
                "altitude_min":                      f(self.v_alt_min),
                "altitude_max":                      f(self.v_alt_max),
                "reproduction_rate":                 f(self.v_repro_rate),
                "reproduction_rate_std":             f(self.v_repro_rate_std),
                "max_age":                           i(self.v_max_age),
                "max_age_std":                       i(self.v_max_age_std),
                "max_population":                    i(self.v_max_pop),
                "energy_start":                      f(self.v_nrj_start),
                "energy_start_std":                  f(self.v_nrj_start_std),
                "energy_consumption":                f(self.v_nrj_conso),
                "energy_consumption_std":            f(self.v_nrj_conso_std),
                "energy_from_food":                  f(self.v_nrj_food),
                "energy_from_food_std":              f(self.v_nrj_food_std),
                "speed":                             f(self.v_speed),
                "speed_std":                         f(self.v_speed_std),
                "perception_radius":                 f(self.v_perception),
                "perception_radius_std":             f(self.v_perception_std),
                "food_sources":                      list(self.food_lb.get(0, tk.END)),
                "growth_rate":                       f(self.v_growth_rate),
                "growth_rate_std":                   f(self.v_growth_rate_std),
                "dispersal_radius":                  i(self.v_dispersal_rad),
                "activity_pattern":                  self.v_activity.get(),
                "can_swim":                          self.v_can_swim.get(),
                "reproduction_cooldown_length":      i(self.v_repro_cd),
                "reproduction_cooldown_length_std":  i(self.v_repro_cd_std),
                "litter_size_min":                   i(self.v_litter_min),
                "litter_size_max":                   i(self.v_litter_max),
                "sexual_maturity_ticks":             i(self.v_sexual_maturity),
                "sexual_maturity_ticks_std":         i(self.v_sexual_maturity_std),
                "gestation_ticks":                   i(self.v_gestation),
                "gestation_ticks_std":               i(self.v_gestation_std),
                "juvenile_mortality_rate":           f(self.v_juv_mort),
                "juvenile_mortality_rate_std":       f(self.v_juv_mort_std),
                "fear_factor":                       f(self.v_fear_factor),
                "fear_factor_std":                   f(self.v_fear_factor_std),
                "herd_cohesion":                     f(self.v_herd_cohesion),
            },
        }

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate(self) -> list[str]:
        errors: list[str] = []

        if not self.v_name.get().strip():
            errors.append("• Le nom est obligatoire.")

        def chk_float(var: tk.StringVar, label: str,
                      mn: Optional[float] = None, mx: Optional[float] = None) -> None:
            try:
                v = float(var.get())
                if mn is not None and v < mn:
                    errors.append(f"• {label} doit être ≥ {mn}")
                if mx is not None and v > mx:
                    errors.append(f"• {label} doit être ≤ {mx}")
            except ValueError:
                errors.append(f"• {label} : nombre attendu")

        def chk_int(var: tk.StringVar, label: str, mn: Optional[int] = None) -> None:
            try:
                v = int(var.get())
                if mn is not None and v < mn:
                    errors.append(f"• {label} doit être ≥ {mn}")
            except ValueError:
                errors.append(f"• {label} : entier attendu")

        chk_float(self.v_cr,                   "Rouge",                      0.0, 1.0)
        chk_float(self.v_cg,                   "Vert",                       0.0, 1.0)
        chk_float(self.v_cb,                   "Bleu",                       0.0, 1.0)
        chk_float(self.v_temp_min,             "Temp min")
        chk_float(self.v_temp_max,             "Temp max")
        chk_float(self.v_hum_min,              "Humidité min",               0.0, 1.0)
        chk_float(self.v_hum_max,              "Humidité max",               0.0, 1.0)
        chk_float(self.v_alt_min,              "Altitude min",               0.0, 1.0)
        chk_float(self.v_alt_max,              "Altitude max",               0.0, 1.0)
        chk_float(self.v_repro_rate,           "Taux reproduction",          0.0, 1.0)
        chk_float(self.v_repro_rate_std,       "σ Taux reproduction",        0.0)
        chk_float(self.v_nrj_start,            "Énergie départ",             1.0)
        chk_float(self.v_nrj_start_std,        "σ Énergie départ",           0.0)
        chk_float(self.v_nrj_conso,            "Consommation",               0.0)
        chk_float(self.v_nrj_conso_std,        "σ Consommation",             0.0)
        chk_float(self.v_nrj_food,             "Gain repas",                 0.0)
        chk_float(self.v_nrj_food_std,         "σ Gain repas",               0.0)
        chk_float(self.v_speed,                "Vitesse",                    0.0)
        chk_float(self.v_speed_std,            "σ Vitesse",                  0.0)
        chk_float(self.v_perception,           "Rayon perception",           0.0)
        chk_float(self.v_perception_std,       "σ Rayon perception",         0.0)
        chk_float(self.v_growth_rate,          "Taux croissance",            0.0)
        chk_float(self.v_growth_rate_std,      "σ Taux croissance",          0.0)
        chk_float(self.v_juv_mort,             "Mortalité juvénile",         0.0, 1.0)
        chk_float(self.v_juv_mort_std,         "σ Mortalité juvénile",       0.0)
        chk_float(self.v_fear_factor,          "Facteur de peur",            0.0)
        chk_float(self.v_fear_factor_std,      "σ Facteur de peur",          0.0)
        chk_float(self.v_herd_cohesion,        "Cohésion troupeau",          0.0, 1.0)
        chk_int(self.v_count,                  "Count initial",               0)
        chk_int(self.v_max_pop,                "Population max",              1)
        chk_int(self.v_max_age,                "Âge max",                     1)
        chk_int(self.v_max_age_std,            "σ Âge max",                   0)
        chk_int(self.v_repro_cd,               "Cooldown repro",              0)
        chk_int(self.v_repro_cd_std,           "σ Cooldown repro",            0)
        chk_int(self.v_litter_min,             "Portée min",                  1)
        chk_int(self.v_litter_max,             "Portée max",                  1)
        chk_int(self.v_sexual_maturity,        "Maturité sexuelle",           0)
        chk_int(self.v_sexual_maturity_std,    "σ Maturité sexuelle",         0)
        chk_int(self.v_gestation,              "Gestation",                   0)
        chk_int(self.v_gestation_std,          "σ Gestation",                 0)
        chk_int(self.v_dispersal_rad,          "Rayon dispersion",            0)

        try:
            if int(self.v_litter_min.get()) > int(self.v_litter_max.get()):
                errors.append("• Portée min doit être ≤ portée max")
        except ValueError:
            pass

        return errors

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _on_type_changed(self, _event=None) -> None:
        t = self.v_type.get()
        self.sec_animal.pack_forget()
        self.sec_plant.pack_forget()
        if t == "plant":
            self.sec_plant.pack(fill=tk.X, padx=12, pady=(10, 0),
                                after=self.sec_survie)
        else:
            self.sec_animal.pack(fill=tk.X, padx=12, pady=(10, 0),
                                 after=self.sec_survie)

    def _pick_color(self, _event=None) -> None:
        try:
            init = "#{:02x}{:02x}{:02x}".format(
                int(float(self.v_cr.get()) * 255),
                int(float(self.v_cg.get()) * 255),
                int(float(self.v_cb.get()) * 255),
            )
        except ValueError:
            init = "#888888"
        result = colorchooser.askcolor(color=init, title="Choisir une couleur")
        if result and result[0]:
            r, g, b = result[0]
            self.v_cr.set(str(round(r / 255, 4)))
            self.v_cg.set(str(round(g / 255, 4)))
            self.v_cb.set(str(round(b / 255, 4)))

    def _sync_color_swatch(self, *_) -> None:
        try:
            r = max(0, min(255, int(float(self.v_cr.get()) * 255)))
            g = max(0, min(255, int(float(self.v_cg.get()) * 255)))
            b = max(0, min(255, int(float(self.v_cb.get()) * 255)))
            self.color_swatch.config(bg=f"#{r:02x}{g:02x}{b:02x}")
        except ValueError:
            pass

    def _add_food(self) -> None:
        val = self.v_food_input.get().strip()
        if val and val not in self.food_lb.get(0, tk.END):
            self.food_lb.insert(tk.END, val)
            self.v_food_input.set("")

    def _remove_food(self) -> None:
        sel = self.food_lb.curselection()
        if sel:
            self.food_lb.delete(sel[0])

    def _clear_form(self) -> None:
        for v in (self.v_name, self.v_cr, self.v_cg, self.v_cb,
                  self.v_count, self.v_max_pop,
                  self.v_max_age, self.v_max_age_std,
                  self.v_repro_rate, self.v_repro_rate_std,
                  self.v_repro_cd, self.v_repro_cd_std,
                  self.v_litter_min, self.v_litter_max,
                  self.v_sexual_maturity, self.v_sexual_maturity_std,
                  self.v_gestation, self.v_gestation_std,
                  self.v_juv_mort, self.v_juv_mort_std,
                  self.v_fear_factor, self.v_fear_factor_std,
                  self.v_nrj_start, self.v_nrj_start_std,
                  self.v_nrj_conso, self.v_nrj_conso_std,
                  self.v_nrj_food, self.v_nrj_food_std,
                  self.v_temp_min, self.v_temp_max, self.v_hum_min, self.v_hum_max,
                  self.v_alt_min, self.v_alt_max,
                  self.v_speed, self.v_speed_std,
                  self.v_perception, self.v_perception_std,
                  self.v_growth_rate, self.v_growth_rate_std,
                  self.v_dispersal_rad, self.v_food_input):
            v.set("")
        self.v_activity.set("diurnal")
        self.v_can_swim.set(False)
        self.food_lb.delete(0, tk.END)

    def _set_status(self, msg: str, duration_ms: int = 4000) -> None:
        self.status_lbl.config(text=msg)
        self.root.after(duration_ms, lambda: self.status_lbl.config(text=""))

    # ── Utilitaires ───────────────────────────────────────────────────────────

    @staticmethod
    def _unique_stem(base: str) -> str:
        stem = base
        i = 1
        while (SPECIES_DIR / f"{stem}.json").exists():
            stem = f"{base}_{i}"
            i += 1
        return stem


# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    SPECIES_DIR.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    SpeciesEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
