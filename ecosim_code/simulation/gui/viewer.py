"""
Viewer 2D Python — vue du dessus, caméra fixe.
Affiche le terrain coloré par altitude et les entités sous forme de pixels/carrés.
"""

import tkinter as tk
from tkinter import font as tkfont
import math
import time
import numpy as np
from PIL import Image, ImageTk
from simulation.utils.counting import count_by_species
from world.terrain import BIOME_PALETTE

CANVAS_W = 700
CANVAS_H = 700
REFRESH_MS = 50   # 20 fps

# ── Constantes panneau cartes entités ────────────────────────────────────────
CARD_H      = 58    # hauteur d'une carte en pixels
CARD_PAD    = 6     # marge haute/basse dans le canvas cartes
N_CARDS_MAX = 50    # nombre maximum de cartes rendues simultanément (viewport virtuel)


class SimViewer:
    def __init__(self, engine):
        self.engine = engine
        self.root = tk.Tk()
        self.root.title("EcoSim — Simulateur d'écosystème")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d0d1a")

        self._tk_img = None              # référence PhotoImage terrain (évite GC)
        self._canvas_img_id = None       # item image terrain sur le canvas
        self._canvas_bg = None           # couleur de fond courante
        self._terrain_base = None        # np.ndarray H×W×3 pré-calculé
        self._terrain_grid_id = None     # détecte changement de grille

        # Cache terrain : recalcul uniquement si la vue ou l'éclairage change
        self._last_cam_key    = None  # (x0, y0, x1, y1) — vue monde
        self._last_tod_bucket = -1    # int(tod * 72) — tranche d'éclairage

        # Rendu PIL : tableaux numpy cachés
        self._cached_terrain_arr: np.ndarray | None = None   # terrain seul, CANVAS_W×H×3
        self._cached_entity_arr:  np.ndarray | None = None   # terrain + entités
        self._entity_brightness:  float = 1.0                # facteur jour/nuit courant
        self._species_color_cache: dict = {}                  # sp → np.uint8[3]

        # True si le verrou moteur a été acquis ce frame (snapshot frais)
        self._snap_updated: bool = False

        # Item canvas du highlight de sélection (créé une seule fois)
        self._highlight_item = None

        # Snapshots thread-safe (mis à jour quand le verrou est disponible)
        self._snap_tick        = 0
        self._snap_plants      = []
        self._snap_individuals = []

        # Suivi individuel
        self._selected_eid       = None  # id() de l'entité sélectionnée
        self._selected_card_idx  = None  # index dans _entity_map
        self._entity_map         = []    # list[entity] parallèle aux cartes
        self._last_entity_count  = -1
        self._last_rebuild_time  = 0.0   # timestamp du dernier rebuild des cartes
        self._last_detail_time   = 0.0   # timestamp du dernier update du détail
        self._last_detail_text   = None  # contenu affiché (anti-clignotement)
        self._last_detail_name   = None
        self._rendered_range: tuple[int, int] = (0, 0)  # (start, end) des cartes dessinées

        # Caméra et zoom (animés par interpolation exponentielle)
        self._zoom    = 1.0
        self._zoom_t  = 1.0
        self._cam_x   = 250.0
        self._cam_y   = 250.0
        self._cam_tx  = 250.0
        self._cam_ty  = 250.0

        self._setup_ui()
        self._setup_entity_panel()
        self._build_terrain_base()

    # ── Construction de l'interface ───────────────────────────────────────────

    def _setup_ui(self):
        # Canvas gauche
        left = tk.Frame(self.root, bg="#0d0d1a")
        left.pack(side=tk.LEFT)
        self.canvas = tk.Canvas(left, width=CANVAS_W, height=CANVAS_H,
                                bg="#000011", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # Panneau de contrôle droit
        right = tk.Frame(self.root, bg="#16213e", width=220)
        right.pack(side=tk.LEFT, fill=tk.Y)
        right.pack_propagate(False)

        pad = {"padx": 12}
        title_font = tkfont.Font(family="Consolas", size=14, weight="bold")
        hud_font   = tkfont.Font(family="Consolas", size=10)
        btn_font   = tkfont.Font(family="Consolas", size=10, weight="bold")
        small_font = tkfont.Font(family="Consolas", size=9)

        def sep():
            tk.Frame(right, bg="#334477", height=1).pack(fill=tk.X, padx=12, pady=7)

        tk.Frame(right, bg="#16213e", height=12).pack()
        tk.Label(right, text="ECOSIM", fg="#e94560", bg="#16213e",
                 font=title_font, **pad).pack(anchor="w")
        sep()

        # ── HUD ──────────────────────────────────────────────────────────────
        self._tick_var    = tk.StringVar(value="Tick: 0")
        self._time_var    = tk.StringVar(value="☀  00h  Jour 0")
        self._year_var    = tk.StringVar(value="Année 1")
        self._speed_var_d = tk.StringVar(value="Vitesse: ×1")

        for var, color in [
            (self._tick_var,    "#aaaaff"),
            (self._time_var,    "#88aacc"),
            (self._year_var,    "#88aacc"),
            (self._speed_var_d, "#ffcc44"),
        ]:
            tk.Label(right, textvariable=var, fg=color, bg="#16213e",
                     font=hud_font, **pad, anchor="w").pack(fill=tk.X)

        # Barre de position du soleil
        self._sun_canvas = tk.Canvas(right, width=196, height=14,
                                     bg="#020810", highlightthickness=1,
                                     highlightbackground="#334477")
        self._sun_canvas.pack(padx=12, pady=(4, 0))

        sep()

        # ── Populations ───────────────────────────────────────────────────────
        tk.Label(right, text="Populations :", fg="#cccccc", bg="#16213e",
                 font=hud_font, **pad, anchor="w").pack(fill=tk.X)
        self._pop_frame = tk.Frame(right, bg="#16213e")
        self._pop_frame.pack(fill=tk.X, **pad)
        self._pop_vars = {}

        sep()

        # ── Boutons Play/Pause/Reset ──────────────────────────────────────────
        self._play_btn = tk.Button(
            right, text="▶  Play", font=btn_font,
            bg="#1e6b2e", fg="white", activebackground="#27ae60",
            relief=tk.FLAT, bd=0, padx=8, pady=7,
            command=self._toggle_play,
        )
        self._play_btn.pack(fill=tk.X, padx=12, pady=2)

        tk.Button(
            right, text="↺  Reset", font=btn_font,
            bg="#6b1e1e", fg="white", activebackground="#c0392b",
            relief=tk.FLAT, bd=0, padx=8, pady=7,
            command=self._reset,
        ).pack(fill=tk.X, padx=12, pady=2)

        sep()

        # ── Vitesse ───────────────────────────────────────────────────────────
        tk.Label(right, text="Vitesse :", fg="#cccccc", bg="#16213e",
                 font=hud_font, **pad, anchor="w").pack(fill=tk.X)
        speed_frame = tk.Frame(right, bg="#16213e")
        speed_frame.pack(fill=tk.X, **pad)
        self._speed_var = tk.IntVar(value=1)
        for val, label in [(1, "×1"), (10, "×10"), (100, "×100"), (1000, "×1K")]:
            tk.Radiobutton(
                speed_frame, text=label, variable=self._speed_var, value=val,
                bg="#16213e", fg="#dddddd", selectcolor="#0f3460",
                activebackground="#16213e", font=small_font,
                command=self._set_speed,
            ).pack(side=tk.LEFT)

        sep()

        tk.Button(
            right, text="📊  Rapport", font=btn_font,
            bg="#1a4a7a", fg="white", activebackground="#2980b9",
            relief=tk.FLAT, bd=0, padx=8, pady=7,
            command=self._generate_report,
        ).pack(fill=tk.X, padx=12, pady=2)

        sep()

        # ── Légende terrain ───────────────────────────────────────────────────
        tk.Label(right, text="Légende terrain :", fg="#cccccc", bg="#16213e",
                 font=hud_font, **pad, anchor="w").pack(fill=tk.X)
        leg_frame = tk.Frame(right, bg="#16213e")
        leg_frame.pack(fill=tk.X, **pad)
        for color, label in [
            ("#1450a0", "Eau profonde"),
            ("#1e6ebc", "Eau peu prof."),
            ("#c8af5f", "Plage"),
            ("#82be4b", "Plaine"),
            ("#3c7a1a", "Forêt"),
            ("#686460", "Roche"),
            ("#e6e6f0", "Neige"),
        ]:
            row = tk.Frame(leg_frame, bg="#16213e")
            row.pack(fill=tk.X, pady=1)
            tk.Frame(row, bg=color, width=12, height=12).pack(side=tk.LEFT, padx=(0, 5))
            tk.Label(row, text=label, fg="#aaaaaa", bg="#16213e",
                     font=small_font).pack(side=tk.LEFT)

    # ── Panneau cartes d'entités ──────────────────────────────────────────────

    def _setup_entity_panel(self):
        """Panneau droit : cartes visuelles scrollables + zone de détail."""
        ep = tk.Frame(self.root, bg="#0b1628", width=275)
        ep.pack(side=tk.LEFT, fill=tk.Y)
        ep.pack_propagate(False)
        self._entity_panel = ep

        _ff = "Consolas"
        self._cf_title  = tkfont.Font(family=_ff, size=11, weight="bold")
        self._cf_count  = tkfont.Font(family=_ff, size=9)
        self._cf_name   = tkfont.Font(family=_ff, size=9,  weight="bold")
        self._cf_small  = tkfont.Font(family=_ff, size=8)
        self._cf_detail = tkfont.Font(family=_ff, size=8)

        def sep():
            tk.Frame(ep, bg="#1e3a5a", height=1).pack(fill=tk.X, padx=8, pady=5)

        # ── En-tête ──────────────────────────────────────────────────────────
        tk.Frame(ep, bg="#0b1628", height=8).pack()
        tk.Label(ep, text="ENTITÉS", fg="#4fc3f7", bg="#0b1628",
                 font=self._cf_title, padx=8).pack(anchor="w")
        self._entity_count_var = tk.StringVar(value="")
        tk.Label(ep, textvariable=self._entity_count_var, fg="#4a7a9b",
                 bg="#0b1628", font=self._cf_count, padx=8).pack(anchor="w")

        sep()

        # ── Canvas cartes (scrollable) ────────────────────────────────────────
        cards_frame = tk.Frame(ep, bg="#0b1628")
        cards_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 2))

        self._cards_sb = tk.Scrollbar(cards_frame, orient=tk.VERTICAL,
                                      bg="#091524", troughcolor="#060e1a",
                                      width=8)
        self._cards_canvas = tk.Canvas(
            cards_frame,
            bg="#07101e",
            highlightthickness=0,
            yscrollcommand=self._cards_sb.set,
        )
        self._cards_sb.config(command=self._cards_canvas.yview)
        self._cards_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._cards_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._cards_canvas.bind("<Button-1>",   self._on_card_click)
        self._cards_canvas.bind("<MouseWheel>",  self._on_cards_scroll)
        self._cards_canvas.bind("<Button-4>",    self._on_cards_scroll)
        self._cards_canvas.bind("<Button-5>",    self._on_cards_scroll)
        self._cards_canvas.bind("<Configure>",   lambda _e: self._draw_visible_cards())

        sep()

        # ── Zone de détail ────────────────────────────────────────────────────
        detail_hdr = tk.Frame(ep, bg="#0b1628")
        detail_hdr.pack(fill=tk.X, padx=8)
        tk.Label(detail_hdr, text="▸ Détail", fg="#7ab8d4", bg="#0b1628",
                 font=self._cf_count).pack(side=tk.LEFT)
        self._detail_name_var = tk.StringVar(value="")
        tk.Label(detail_hdr, textvariable=self._detail_name_var,
                 fg="#cccccc", bg="#0b1628",
                 font=tkfont.Font(family="Consolas", size=9, weight="bold")
                 ).pack(side=tk.LEFT, padx=(6, 0))

        detail_outer = tk.Frame(ep, bg="#050c18", bd=0)
        detail_outer.pack(fill=tk.X, padx=8, pady=(3, 8))

        self._detail_text = tk.Text(
            detail_outer,
            bg="#050c18",
            fg="#7aaabb",
            font=self._cf_detail,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            height=13,
            state=tk.DISABLED,
            wrap=tk.NONE,
            cursor="arrow",
        )
        self._detail_text.pack(fill=tk.X, padx=6, pady=6)
        self._set_detail("Cliquez sur une entité.")

    # ── Dessin des cartes ─────────────────────────────────────────────────────

    def _rebuild_entity_list(self):
        """Met à jour _entity_map et redessine les cartes visibles."""
        prev_eid = self._selected_eid
        self._entity_map = (
            sorted(self._snap_individuals, key=lambda e: (e.species.name, e.x)) +
            sorted(self._snap_plants,      key=lambda e: (e.species.name, e.x))
        )
        self._selected_card_idx = None

        # Scrollregion globale (permet au scrollbar de refléter la taille totale)
        cc = self._cards_canvas
        cc.update_idletasks()
        cw = cc.winfo_width() or 251
        total_h = CARD_PAD + len(self._entity_map) * CARD_H + CARD_PAD
        cc.config(scrollregion=(0, 0, cw, total_h))

        n_a = len(self._snap_individuals)
        n_p = len(self._snap_plants)
        self._entity_count_var.set(f"{n_a} animaux · {n_p} plantes")

        self._draw_visible_cards()

        # Scroller vers la carte sélectionnée si elle existe
        if prev_eid is not None:
            for i, e in enumerate(self._entity_map):
                if id(e) == prev_eid:
                    self._selected_card_idx = i
                    if total_h > 0:
                        frac = (i * CARD_H) / total_h
                        cc.yview_moveto(frac)
                    break

    def _draw_visible_cards(self):
        """Redessine uniquement les N_CARDS_MAX cartes visibles dans la fenêtre scrollable."""
        from entities.animal import Individual

        cc = self._cards_canvas
        cc.update_idletasks()
        cw = cc.winfo_width() or 251

        if not self._entity_map:
            cc.delete("card")
            self._rendered_range = (0, 0)
            return

        # Calculer la fenêtre visible (en px dans l'espace canvas)
        total_h = CARD_PAD + len(self._entity_map) * CARD_H + CARD_PAD
        yview = cc.yview()
        vis_top_px = int(yview[0] * total_h)

        first = max(0, (vis_top_px - CARD_PAD) // CARD_H)
        last  = min(len(self._entity_map), first + N_CARDS_MAX)

        # Pas de changement de fenêtre → ne rien faire
        if (first, last) == self._rendered_range and cc.find_withtag("card"):
            return

        cc.delete("card")
        self._rendered_range = (first, last)

        bar_x0 = 16
        bar_x1 = cw - 8
        bar_w  = max(1, bar_x1 - bar_x0)

        _state_labels = {
            "wander":    "erre",
            "seek_food": "cherche nourriture",
            "flee":      "fuit !",
            "reproduce": "s'accouple",
            "sleep":     "dort",
            "en_vol":    "en vol",
            "au_sol":    "au sol",
        }

        for idx in range(first, last):
            entity    = self._entity_map[idx]
            sp        = entity.species
            is_animal = isinstance(entity, Individual)
            selected  = (idx == self._selected_card_idx)

            r, g, b = [int(v * 255) for v in sp.color]
            sp_hex  = f"#{r:02x}{g:02x}{b:02x}"

            y0 = CARD_PAD + idx * CARD_H
            y1 = y0 + CARD_H - 3

            # ── Fond carte ────────────────────────────────────────────────
            bg_col  = "#132440" if selected else "#0a1322"
            brd_col = "#2a5080" if selected else "#152030"
            cc.create_rectangle(2, y0, cw - 2, y1,
                                 fill=bg_col, outline=brd_col, width=1,
                                 tags=(f"card_bg_{idx}", "card"))

            # ── Bande couleur gauche ──────────────────────────────────────
            cc.create_rectangle(2, y0, 6, y1, fill=sp_hex, outline="", tags="card")

            # ── Icône type ────────────────────────────────────────────────
            type_icons = {"herbivore": "◆", "carnivore": "▲",
                          "omnivore": "●", "plant": "✿"}
            icon = type_icons.get(sp.type, "·")

            # ── Ligne 1 : icône + nom + position ─────────────────────────
            name_col = sp_hex if selected else _blend_hex(sp_hex, "#aaaaaa", 0.55)
            cc.create_text(12, y0 + 11,
                           text=f"{icon} {sp.name}",
                           font=self._cf_name, fill=name_col, anchor="w", tags="card")
            cc.create_text(cw - 5, y0 + 11,
                           text=f"({int(entity.x):3},{int(entity.y):3})",
                           font=self._cf_small, fill="#3a5a70", anchor="e", tags="card")

            # ── Ligne 2 : barre énergie ───────────────────────────────────
            max_e = max(sp.energy_start, 0.001)
            pct   = max(0.0, min(1.0, entity.energy / max_e))
            if   pct > 0.65: bar_col = "#27a855"
            elif pct > 0.35: bar_col = "#c87d18"
            else:             bar_col = "#b82828"

            cc.create_rectangle(bar_x0, y0 + 26, bar_x1, y0 + 33,
                                 fill="#0d1a28", outline="#1a2e42", tags="card")
            fill_x = bar_x0 + int(bar_w * pct)
            if fill_x > bar_x0:
                cc.create_rectangle(bar_x0, y0 + 26, fill_x, y0 + 33,
                                     fill=bar_col, outline="", tags="card")
            pct_col = "#5a9a6a" if pct > 0.65 else ("#c8961a" if pct > 0.35 else "#a03030")
            cc.create_text(bar_x1 + 2, y0 + 29,
                           text=f"{int(pct*100)}%",
                           font=self._cf_small, fill=pct_col, anchor="w", tags="card")

            # ── Ligne 3 : sexe + état / croissance ───────────────────────
            if is_animal:
                sex_sym  = "♂" if entity.sex == "male" else "♀"
                sex_col  = "#5588cc" if entity.sex == "male" else "#cc6688"
                state_lbl = _state_labels.get(entity.state, entity.state)
                state_col = "#bb3333" if entity.state == "flee" else "#5a8898"
                if entity.gestation_timer > 0:
                    state_lbl = f"♥ gestation ({entity.gestation_timer})"
                    state_col = "#cc88aa"
                cc.create_text(12, y0 + 46,
                               text=sex_sym, font=self._cf_small,
                               fill=sex_col, anchor="w", tags="card")
                cc.create_text(22, y0 + 46,
                               text=state_lbl, font=self._cf_small,
                               fill=state_col, anchor="w", tags="card")
            else:
                growth_pct = max(0.0, min(1.0, entity.growth))
                gbar_x1 = bar_x0 + int(bar_w * growth_pct * 0.6)
                cc.create_rectangle(bar_x0, y0 + 41, bar_x0 + int(bar_w * 0.6), y0 + 46,
                                     fill="#0a1820", outline="", tags="card")
                if gbar_x1 > bar_x0:
                    cc.create_rectangle(bar_x0, y0 + 41, gbar_x1, y0 + 46,
                                         fill="#2a7a3a", outline="", tags="card")
                cc.create_text(12, y0 + 46,
                               text=f"✿ croiss. {entity.growth:.2f}",
                               font=self._cf_small, fill="#3a8a4a", anchor="w", tags="card")

    def _highlight_card(self, idx: int, selected: bool):
        """Change rapidement la couleur de fond d'une carte sans tout redessiner."""
        bg  = "#132440" if selected else "#0a1322"
        brd = "#2a5080" if selected else "#152030"
        self._cards_canvas.itemconfig(f"card_bg_{idx}",
                                       fill=bg, outline=brd)

    # ── Interaction cartes ────────────────────────────────────────────────────

    def _on_card_click(self, event):
        canvas_y = self._cards_canvas.canvasy(event.y)
        idx = int((canvas_y - CARD_PAD) / CARD_H)
        if 0 <= idx < len(self._entity_map):
            # Désélectionner ancienne carte
            if self._selected_card_idx is not None:
                self._highlight_card(self._selected_card_idx, False)
            # Sélectionner nouvelle
            entity = self._entity_map[idx]
            self._selected_eid      = id(entity)
            self._selected_card_idx = idx
            self._highlight_card(idx, True)
            self._show_entity_detail(entity)
            self._zoom_t = 5.0
            self._cam_tx = entity.x
            self._cam_ty = entity.y

    def _on_cards_scroll(self, event):
        if event.num == 4:
            self._cards_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._cards_canvas.yview_scroll(1, "units")
        else:
            self._cards_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._rendered_range = (0, 0)  # force le re-dessin au prochain frame
        self._draw_visible_cards()

    # ── Détail entité ─────────────────────────────────────────────────────────

    def _set_detail(self, text: str, name: str = ""):
        if text == self._last_detail_text and name == self._last_detail_name:
            return
        self._last_detail_text = text
        self._last_detail_name = name
        self._detail_name_var.set(name)
        self._detail_text.config(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert("1.0", text)
        self._detail_text.config(state=tk.DISABLED)

    def _show_entity_detail(self, entity):
        from entities.animal import Individual
        sp  = entity.species
        bar = "─" * 28
        lines = [
            f"Position  : ({entity.x:.1f}, {entity.y:.1f})",
            f"Âge       : {entity.age:,} ticks",
            f"Énergie   : {entity.energy:.1f} / {sp.energy_start:.1f}",
        ]
        if isinstance(entity, Individual):
            lines += [
                f"État      : {entity.state}",
                f"Sexe      : {entity.sex}",
            ]
            if entity.gestation_timer > 0:
                lines.append(f"Gestation : {entity.gestation_timer} ticks")
            lines += [
                bar,
                f"Vitesse   : {sp.speed:.3f}",
                f"Perception: {sp.perception_radius:.2f}",
                f"Repr.taux : {sp.reproduction_rate:.3f}",
                f"Consomm.  : {sp.energy_consumption:.4f}",
                f"E.nourrit.: {sp.energy_from_food:.1f}",
                f"Âge max   : {sp.max_age:,}",
                f"Maturité  : {sp.sexual_maturity_ticks:,}",
                f"Gest.ticks: {sp.gestation_ticks:,}",
                f"Mort.juv. : {sp.juvenile_mortality_rate:.2e}",
                f"Peur      : {sp.fear_factor:.2f}",
            ]
        else:
            lines += [
                f"Croissance: {entity.growth:.3f}",
                bar,
                f"Tx crois. : {sp.growth_rate:.5f}",
                f"Repr.taux : {sp.reproduction_rate:.3f}",
                f"Âge max   : {sp.max_age:,}",
            ]
        self._set_detail("\n".join(lines), name=f"  {sp.name}")

    # ── Mise à jour panneau (chaque frame) ───────────────────────────────────

    def _update_entity_panel(self):
        # Vérifie si l'entité sélectionnée est encore vivante
        if self._selected_eid is not None:
            current_ids = (
                {id(e) for e in self._snap_individuals} |
                {id(e) for e in self._snap_plants}
            )
            if self._selected_eid not in current_ids:
                self._selected_eid      = None
                self._selected_card_idx = None
                self._set_detail("Entité disparue.")
                self._zoom_reset()

        total = len(self._snap_individuals) + len(self._snap_plants)
        now   = time.monotonic()
        if total != self._last_entity_count and (now - self._last_rebuild_time) >= 0.5:
            self._last_entity_count = total
            self._last_rebuild_time = now
            self._rebuild_entity_list()

        # Mise à jour temps réel du détail + caméra (throttlé à 4 fps)
        if self._selected_eid is not None and (now - self._last_detail_time) >= 0.25:
            self._last_detail_time = now
            for e in self._entity_map:
                if id(e) == self._selected_eid:
                    self._show_entity_detail(e)
                    self._cam_tx = e.x
                    self._cam_ty = e.y
                    break

    # ── Filtre jour / nuit ────────────────────────────────────────────────────

    @staticmethod
    def _day_night_filter(img_arr: np.ndarray, tod: float) -> np.ndarray:
        sun = math.sin(tod * 2 * math.pi - math.pi / 2)
        brightness = 0.28 + 0.72 * (sun + 1) / 2
        img = img_arr.astype(np.float32)
        img *= brightness
        night = max(0.0, -sun * 0.7)
        if night > 0:
            img[:, :, 2] = np.minimum(255, img[:, :, 2] + night * 28)
            img[:, :, 0] *= (1.0 - night * 0.30)
            img[:, :, 1] *= (1.0 - night * 0.18)
        golden = max(0.0, 1.0 - abs(sun) * 4.5) if sun > -0.25 else 0.0
        if golden > 0:
            img[:, :, 0] = np.minimum(255, img[:, :, 0] + golden * 45)
            img[:, :, 1] = np.minimum(255, img[:, :, 1] + golden * 18)
        return np.clip(img, 0, 255).astype(np.uint8)

    @staticmethod
    def _sky_color(tod: float) -> str:
        sun = math.sin(tod * 2 * math.pi - math.pi / 2)
        if sun < -0.25:
            return "#020810"
        if sun < 0.0:
            return "#0c0c1e"
        if sun < 0.3:
            return "#0a0a18"
        return "#000011"

    # ── Rendu terrain ─────────────────────────────────────────────────────────

    def _build_terrain_base(self):
        alt = self.engine.grid.altitude
        h, w = alt.shape
        img = np.zeros((h, w, 3), dtype=np.uint8)
        for threshold, color in BIOME_PALETTE:
            img[alt >= threshold] = color
        self._terrain_base = img
        self._terrain_grid_id = id(self.engine.grid)

    # ── Rendu frame ──────────────────────────────────────────────────────────

    def _render_frame(self, tod: float):
        if id(self.engine.grid) != self._terrain_grid_id:
            self._build_terrain_base()
            self._last_cam_key = None   # force re-rendu du terrain

        grid_h, grid_w = self._terrain_base.shape[:2]

        # ── Fenêtre de vue (coords monde) ────────────────────────────────────
        view_w = grid_w / self._zoom
        view_h = grid_h / self._zoom
        x0 = int(self._cam_x - view_w / 2)
        y0 = int(self._cam_y - view_h / 2)
        x0 = max(0, min(x0, grid_w - int(view_w)))
        y0 = max(0, min(y0, grid_h - int(view_h)))
        x1 = min(grid_w, x0 + int(view_w))
        y1 = min(grid_h, y0 + int(view_h))
        vw, vh = x1 - x0, y1 - y0

        scale_x = CANVAS_W / max(vw, 1)
        scale_y = CANVAS_H / max(vh, 1)

        # ── Éclairage : bucket de 72 tranches/jour (~20 min simulées) ───────────
        tod_bucket = int(tod * 72)
        lighting_changed = (tod_bucket != self._last_tod_bucket)
        if lighting_changed:
            self._last_tod_bucket = tod_bucket
            sun = math.sin(tod * 2 * math.pi - math.pi / 2)
            self._entity_brightness = 0.28 + 0.72 * (sun + 1) / 2

        # ── Terrain : recalculé si caméra ou éclairage a changé ─────────────
        cam_key = (x0, y0, x1, y1)
        terrain_changed = (cam_key != self._last_cam_key or lighting_changed)
        if terrain_changed or self._cached_terrain_arr is None:
            self._last_cam_key = cam_key
            filtered = self._day_night_filter(self._terrain_base[y0:y1, x0:x1], tod)
            self._cached_terrain_arr = np.array(
                Image.fromarray(filtered, "RGB").resize((CANVAS_W, CANVAS_H), Image.NEAREST)
            )
            if lighting_changed:
                self._species_color_cache.clear()
            self._cached_entity_arr = None   # invalide le calque entités

        # ── Entités : recalculées seulement si snapshot frais ou éclairage ────
        # Quand le verrou est contesté (_snap_updated=False), on réutilise le
        # calque précédent → zéro calcul → GUI reste responsive à ×10/×100.
        if self._snap_updated or lighting_changed or self._cached_entity_arr is None:
            brt = self._entity_brightness

            def _sp_color(sp) -> np.ndarray:
                # Species n'est pas hashable (dataclass mutable) → clé par nom
                c = self._species_color_cache.get(sp.name)
                if c is None:
                    c = np.array(
                        [min(255, int(ch * 255 * brt)) for ch in sp.color],
                        dtype=np.uint8,
                    )
                    self._species_color_cache[sp.name] = c
                return c

            img_arr = self._cached_terrain_arr.copy()
            pw = max(1, int(scale_x))
            ph = max(1, int(scale_y))

            # Plantes groupées par espèce (clé = nom) → broadcast NumPy par espèce
            plants_by_sp: dict = {}   # name → (species, list[plant])
            for p in self._snap_plants:
                entry = plants_by_sp.get(p.species.name)
                if entry is None:
                    plants_by_sp[p.species.name] = (p.species, [p])
                else:
                    entry[1].append(p)

            for _name, (sp, sp_plants) in plants_by_sp.items():
                col = _sp_color(sp)
                n   = len(sp_plants)
                pxi = np.empty(n, dtype=np.int32)
                pyi = np.empty(n, dtype=np.int32)
                for k, p in enumerate(sp_plants):
                    pxi[k] = int((p.x - x0) * scale_x)
                    pyi[k] = int((p.y - y0) * scale_y)
                mask = (pxi >= 0) & (pxi + pw <= CANVAS_W) & (pyi >= 0) & (pyi + ph <= CANVAS_H)
                if pw == 1 and ph == 1:
                    img_arr[pyi[mask], pxi[mask]] = col
                else:
                    for i in np.where(mask)[0]:
                        img_arr[pyi[i]:pyi[i] + ph, pxi[i]:pxi[i] + pw] = col

            sz   = max(1, int(3 * scale_x))
            half = sz // 2
            for ind in self._snap_individuals:
                col = _sp_color(ind.species)
                cx  = int((ind.x - x0) * scale_x)
                cy  = int((ind.y - y0) * scale_y)
                x1e = max(0, cx - half)
                x2e = min(CANVAS_W, cx + half + 1)
                y1e = max(0, cy - half)
                y2e = min(CANVAS_H, cy + half + 1)
                if x2e > x1e and y2e > y1e:
                    img_arr[y1e:y2e, x1e:x2e] = col

            self._cached_entity_arr = img_arr

        # ── Mise à jour canvas : une seule opération Tk par frame ─────────────
        self._tk_img = ImageTk.PhotoImage(
            Image.fromarray(self._cached_entity_arr, "RGB")
        )
        if self._canvas_img_id is None:
            self._canvas_img_id = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self._tk_img)
        else:
            self.canvas.itemconfig(self._canvas_img_id, image=self._tk_img)

        # ── Highlight entité sélectionnée : déplacer sans recréer ─────────────
        if self._selected_eid is not None:
            for e in self._entity_map:
                if id(e) == self._selected_eid:
                    cx = (e.x - x0) * scale_x
                    cy = (e.y - y0) * scale_y
                    r  = 9
                    if self._highlight_item is None:
                        self._highlight_item = self.canvas.create_oval(
                            cx-r, cy-r, cx+r, cy+r,
                            outline="#ffffff", width=2)
                    else:
                        self.canvas.coords(self._highlight_item,
                                           cx-r, cy-r, cx+r, cy+r)
                        self.canvas.itemconfig(self._highlight_item, state="normal")
                    break
        else:
            if self._highlight_item is not None:
                self.canvas.itemconfig(self._highlight_item, state="hidden")

    # ── Mise à jour HUD ───────────────────────────────────────────────────────

    def _update_hud(self):
        from simulation.engine import DAY_LENGTH, SIM_YEAR
        # Lecture directe de tick_count — atomique sous GIL, toujours à jour
        # même si le verrou non-bloquant n'a pas été acquis ce frame.
        tick  = self.engine.tick_count
        tod   = (tick % DAY_LENGTH) / DAY_LENGTH
        day   = (tick // DAY_LENGTH) % 365
        year  = tick // SIM_YEAR + 1
        heure = int(tod * 24)
        sun   = math.sin(tod * 2 * math.pi - math.pi / 2)
        icone = "🌙" if sun < -0.1 else ("🌅" if sun < 0.2 else "☀")

        self._tick_var.set(f"Tick: {tick:,}")
        self._time_var.set(f"{icone}  {heure:02d}h  Jour {day}")
        self._year_var.set(f"Année {year}")
        self._speed_var_d.set(f"Vitesse: ×{self.engine.speed}")
        self._draw_sun_bar(tod)

        counts = count_by_species(list(self._snap_plants) + list(self._snap_individuals))

        for sp in self.engine.species_list:
            n = sp.name
            c = counts.get(n, 0)
            if n not in self._pop_vars:
                r, g, b = [int(x * 255) for x in sp.color]
                color = f"#{r:02x}{g:02x}{b:02x}"
                var = tk.StringVar()
                lbl = tk.Label(
                    self._pop_frame, textvariable=var,
                    fg=color, bg="#16213e",
                    font=tkfont.Font(family="Consolas", size=10),
                    anchor="w",
                )
                lbl.pack(fill=tk.X)
                self._pop_vars[n] = var
            self._pop_vars[n].set(f"  {n}: {c:,}")

    def _draw_sun_bar(self, tod: float):
        W, H = 196, 14
        self._sun_canvas.delete("all")
        segments = [
            (0.00, "#020810"), (0.20, "#0d1030"), (0.25, "#c06030"),
            (0.30, "#e0c060"), (0.50, "#87ceeb"), (0.70, "#e0c060"),
            (0.75, "#c06030"), (0.80, "#0d1030"), (1.00, "#020810"),
        ]
        for i in range(len(segments) - 1):
            t0, c0 = segments[i]
            t1, _  = segments[i + 1]
            x0, x1 = int(t0 * W), int(t1 * W)
            self._sun_canvas.create_rectangle(x0, 0, x1, H, fill=c0, outline="")
        sun = math.sin(tod * 2 * math.pi - math.pi / 2)
        marker_x = int(tod * W)
        color = "#ffee44" if sun >= 0 else "#aaaadd"
        r = 5
        self._sun_canvas.create_oval(
            marker_x - r, H // 2 - r, marker_x + r, H // 2 + r,
            fill=color, outline="#ffffff", width=1,
        )

    # ── Boucle d'affichage ────────────────────────────────────────────────────

    def _loop(self):
        from simulation.engine import DAY_LENGTH
        # Acquisition non-bloquante : si le moteur tient le verrou (batch ×N),
        # on réutilise le snapshot précédent plutôt que de bloquer le thread UI.
        self._snap_updated = False
        if self.engine.lock.acquire(blocking=False):
            try:
                self._snap_tick        = self.engine.tick_count
                self._snap_plants      = list(self.engine.plants)
                self._snap_individuals = list(self.engine.individuals)
                self._snap_updated     = True
            finally:
                self.engine.lock.release()
        tick = self._snap_tick
        tod  = (tick % DAY_LENGTH) / DAY_LENGTH

        alpha = 0.14
        self._zoom  += (self._zoom_t  - self._zoom)  * alpha
        self._cam_x += (self._cam_tx - self._cam_x) * alpha
        self._cam_y += (self._cam_ty - self._cam_y) * alpha

        self._render_frame(tod)
        self._update_hud()
        self._update_entity_panel()

        sky = self._sky_color(tod)
        if sky != self._canvas_bg:
            self._canvas_bg = sky
            self.canvas.configure(bg=sky)
        self.root.after(REFRESH_MS, self._loop)

    # ── Contrôles ─────────────────────────────────────────────────────────────

    def _toggle_play(self):
        self.engine.running = not self.engine.running
        if self.engine.running:
            self._play_btn.config(text="⏸  Pause", bg="#7a5010")
        else:
            self._play_btn.config(text="▶  Play", bg="#1e6b2e")

    def _set_speed(self):
        self.engine.speed = self._speed_var.get()

    def _zoom_reset(self):
        self._zoom_t = 1.0
        self._cam_tx = self.engine.grid.width  / 2
        self._cam_ty = self.engine.grid.height / 2

    def _on_canvas_click(self, _event):
        """Clic sur le canvas → désélectionne et revient à la vue globale."""
        if self._selected_card_idx is not None:
            self._highlight_card(self._selected_card_idx, False)
        self._selected_eid      = None
        self._selected_card_idx = None
        self._set_detail("Cliquez sur une entité.")
        self._zoom_reset()

    def _reset(self):
        self.engine.running = False
        with self.engine.lock:
            self.engine.reset()
        for widget in self._pop_frame.winfo_children():
            widget.destroy()
        self._pop_vars.clear()
        self._play_btn.config(text="▶  Play", bg="#1e6b2e")
        self._selected_eid      = None
        self._selected_card_idx = None
        self._entity_map.clear()
        self._last_entity_count = -1
        self._cached_terrain_arr = None
        self._cached_entity_arr  = None
        self._species_color_cache.clear()
        self._last_cam_key    = None
        self._last_tod_bucket = -1
        self._highlight_item  = None
        self.canvas.delete("entity")
        self.canvas.delete("highlight")
        self._cards_canvas.delete("all")
        self._entity_count_var.set("")
        self._set_detail("Cliquez sur une entité.")
        self._zoom = 1.0
        self._zoom_t = 1.0
        self._cam_x  = self.engine.grid.width  / 2
        self._cam_y  = self.engine.grid.height / 2
        self._cam_tx = self._cam_x
        self._cam_ty = self._cam_y

    def _generate_report(self):
        filename = self.engine.generate_report()
        print(f"Rapport généré : {filename}")

    def run(self):
        self.root.after(REFRESH_MS, self._loop)
        self.root.mainloop()


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _apply_brightness(base_rgb: tuple, brt: float) -> str:
    """Retourne un hex '#rrggbb' en appliquant un facteur de luminosité [0,1]."""
    r = min(255, int(base_rgb[0] * brt))
    g = min(255, int(base_rgb[1] * brt))
    b = min(255, int(base_rgb[2] * brt))
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend_hex(hex1: str, hex2: str, t: float) -> str:
    """Mélange deux couleurs hex avec un facteur t ∈ [0,1] (0 = hex1, 1 = hex2)."""
    r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
    r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"
