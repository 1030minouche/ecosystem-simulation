"""
Viewer 2D Python — vue du dessus, caméra fixe.
Affiche le terrain coloré par altitude et les entités sous forme de pixels/carrés.
"""

import tkinter as tk
from tkinter import font as tkfont
import math
import numpy as np
from PIL import Image, ImageTk

CANVAS_W = 700
CANVAS_H = 700
REFRESH_MS = 50   # 20 fps


class SimViewer:
    def __init__(self, engine):
        self.engine = engine
        self.root = tk.Tk()
        self.root.title("EcoSim — Simulateur d'écosystème")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d0d1a")

        self._tk_img = None           # référence PhotoImage (évite GC)
        self._terrain_base = None     # np.ndarray H×W×3 pré-calculé
        self._terrain_grid_id = None  # détecte changement de grille (reset)

        self._setup_ui()
        self._build_terrain_base()

    # ── Construction de l'interface ───────────────────────────────────────────

    def _setup_ui(self):
        # Canvas gauche
        left = tk.Frame(self.root, bg="#0d0d1a")
        left.pack(side=tk.LEFT)
        self.canvas = tk.Canvas(left, width=CANVAS_W, height=CANVAS_H,
                                bg="#000011", highlightthickness=0)
        self.canvas.pack()

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

    # ── Filtre jour / nuit ────────────────────────────────────────────────────

    @staticmethod
    def _day_night_filter(img_arr: np.ndarray, tod: float) -> np.ndarray:
        """
        Applique un filtre de luminosité + teinte selon l'heure simulée.
        tod ∈ [0, 1) : 0 = minuit, 0.25 = aube, 0.5 = midi, 0.75 = crépuscule.
        """
        # Hauteur du soleil : -1 (minuit) → +1 (midi)
        sun = math.sin(tod * 2 * math.pi - math.pi / 2)

        # Luminosité globale : 0.28 la nuit, 1.0 à midi
        brightness = 0.28 + 0.72 * (sun + 1) / 2

        img = img_arr.astype(np.float32)
        img *= brightness

        # Teinte bleue nocturne (soleil sous l'horizon)
        night = max(0.0, -sun * 0.7)
        if night > 0:
            img[:, :, 2] = np.minimum(255, img[:, :, 2] + night * 28)
            img[:, :, 0] *= (1.0 - night * 0.30)
            img[:, :, 1] *= (1.0 - night * 0.18)

        # Teinte dorée à l'aube et au crépuscule (soleil proche de l'horizon)
        golden = max(0.0, 1.0 - abs(sun) * 4.5) if sun > -0.25 else 0.0
        if golden > 0:
            img[:, :, 0] = np.minimum(255, img[:, :, 0] + golden * 45)
            img[:, :, 1] = np.minimum(255, img[:, :, 1] + golden * 18)

        return np.clip(img, 0, 255).astype(np.uint8)

    @staticmethod
    def _sky_color(tod: float) -> str:
        """Couleur de fond du canvas selon l'heure (vue du ciel)."""
        sun = math.sin(tod * 2 * math.pi - math.pi / 2)
        if sun < -0.25:
            return "#020810"   # nuit profonde
        if sun < 0.0:
            return "#0c0c1e"   # aube/crépuscule sombre
        if sun < 0.3:
            return "#0a0a18"   # matin/soir
        return "#000011"       # journée

    # ── Rendu terrain ─────────────────────────────────────────────────────────

    def _build_terrain_base(self):
        """Construit l'image RGB du terrain (vectorisé numpy, exécuté une fois)."""
        alt = self.engine.grid.altitude   # shape (H, W), float 0-1
        h, w = alt.shape
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:]           = ( 20,  80, 160)  # eau profonde
        img[alt >= 0.28] = ( 30, 110, 185)  # eau peu profonde
        img[alt >= 0.30] = (200, 175,  95)  # plage
        img[alt >= 0.40] = (130, 190,  75)  # plaine
        img[alt >= 0.60] = ( 60, 122,  51)  # forêt
        img[alt >= 0.75] = (105, 100,  95)  # roche
        img[alt >= 0.85] = (230, 230, 240)  # neige
        self._terrain_base = img
        self._terrain_grid_id = id(self.engine.grid)

    # ── Rendu frame ──────────────────────────────────────────────────────────

    def _render_frame(self, tod: float):
        if id(self.engine.grid) != self._terrain_grid_id:
            self._build_terrain_base()

        img_arr = self._terrain_base.copy()
        h, w = img_arr.shape[:2]

        # Plantes — pixel unique (couleur de l'espèce)
        for plant in list(self.engine.plants):
            px, py = int(plant.x), int(plant.y)
            if 0 <= px < w and 0 <= py < h:
                r, g, b = [int(c * 255) for c in plant.species.color]
                img_arr[py, px] = (r, g, b)

        # Animaux — carré 3×3 pour être visibles
        for ind in list(self.engine.individuals):
            px, py = int(ind.x), int(ind.y)
            r, g, b = [int(c * 255) for c in ind.species.color]
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    ny2, nx2 = py + dy, px + dx
                    if 0 <= nx2 < w and 0 <= ny2 < h:
                        img_arr[ny2, nx2] = (r, g, b)

        # Filtre jour/nuit
        img_arr = self._day_night_filter(img_arr, tod)

        img = Image.fromarray(img_arr, "RGB")
        img = img.resize((CANVAS_W, CANVAS_H), Image.NEAREST)
        self._tk_img = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)

    # ── Mise à jour HUD ───────────────────────────────────────────────────────

    def _update_hud(self, tod: float):
        from simulation.engine import DAY_LENGTH, SIM_YEAR
        tick  = self.engine.tick_count
        day   = (tick // DAY_LENGTH) % 365
        year  = tick // SIM_YEAR + 1
        heure = int(tod * 24)
        sun   = math.sin(tod * 2 * math.pi - math.pi / 2)
        icone = "🌙" if sun < -0.1 else ("🌅" if sun < 0.2 else "☀")

        self._tick_var.set(f"Tick: {tick:,}")
        self._time_var.set(f"{icone}  {heure:02d}h  Jour {day}")
        self._year_var.set(f"Année {year}")
        self._speed_var_d.set(f"Vitesse: ×{self.engine.speed}")

        # Barre solaire (position du soleil dans la journée)
        self._draw_sun_bar(tod)

        # Populations
        counts = {}
        for p in list(self.engine.plants):
            counts[p.species.name] = counts.get(p.species.name, 0) + 1
        for i in list(self.engine.individuals):
            counts[i.species.name] = counts.get(i.species.name, 0) + 1

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
        """Dessine une petite barre arc-en-ciel avec la position du soleil."""
        W, H = 196, 14
        self._sun_canvas.delete("all")

        # Fond dégradé nuit→aube→jour→crépuscule→nuit
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

        # Marqueur (soleil ou lune)
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
        tick = self.engine.tick_count
        tod  = (tick % DAY_LENGTH) / DAY_LENGTH

        self._render_frame(tod)
        self._update_hud(tod)

        # Couleur de fond du canvas selon le ciel
        self.canvas.configure(bg=self._sky_color(tod))

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

    def _reset(self):
        self.engine.running = False
        self.engine.reset()
        for widget in self._pop_frame.winfo_children():
            widget.destroy()
        self._pop_vars.clear()
        self._play_btn.config(text="▶  Play", bg="#1e6b2e")

    def _generate_report(self):
        filename = self.engine.generate_report()
        print(f"Rapport généré : {filename}")

    def run(self):
        self.root.after(REFRESH_MS, self._loop)
        self.root.mainloop()
