"""Fenêtre d'édition d'un template importé.

Compteurs de structures, rayon, niveau CC, nom — le modèle (colony_model)
fait la chirurgie, analyze_template mesure, _draw_map dessine. Tout est
rapporté, rien n'est interdit : le bandeau passe au rouge, il ne bloque pas.
"""
import json
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from src.services import colony_model as cm
from src.services.template_service import analyze_template

COUNTERS = (
    ("factories", "Factories"),
    ("extractors", "Extractors"),
    ("heads", "Heads / extr."),
    ("launch_pads", "Launch Pads"),
    ("storage", "Storage"),
)


def open_template_editor(app, template, source_name=None):
    """Ouvre l'éditeur sur un template (dict déjà décodé)."""
    import PI  # tardif : PI importe ce module
    EVE = PI.EVE

    shape = cm.template_shape_error(template)
    if shape is not None:
        messagebox.showerror("Cannot open template",
                             f"This is not a PI template: {shape}",
                             parent=app.root)
        return

    try:
        model = cm.parse_colony(template)
        parse_reason = None
    except cm.ParseError as e:
        model = None
        parse_reason = str(e)

    win = tk.Toplevel(app.root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    try:
        win.attributes("-alpha", app.alpha)
    except Exception:
        pass
    win.configure(bg=EVE["bg_deep"])
    cfg = PI._load_window_config()
    win.geometry(cfg.get("editor_geometry", "860x820"))
    win.minsize(560, 560)

    def close():
        PI._update_window_config("editor_geometry", win.geometry())
        win.destroy()

    title = "Template Editor" + (f" — {source_name}" if source_name else "")
    app._build_title_bar(win, title, close)
    app._add_resize_handles(win)

    state = {"model": model, "template": dict(template), "analysis": None,
             "name_touched": False}

    # ── Rangée compteurs ─────────────────────────────────────────────────
    ctr_frame = ttk.Frame(win)
    ctr_frame.pack(fill=tk.X, padx=10, pady=(8, 2))
    counter_vars, counter_boxes = {}, {}

    def current_counts():
        m = state["model"]
        counts = cm.structure_counts(m)
        return {
            "factories": sum(c for k, c in counts.items() if k in cm.FACTORY_KINDS),
            "extractors": counts.get("Extractor Control Unit", 0),
            "heads": cm.heads_per_extractor(m),
            "launch_pads": counts.get("Launch Pad", 0),
            "storage": counts.get("Storage Facility", 0),
        }

    def apply_counter(key):
        m = state["model"]
        try:
            want = int(counter_vars[key].get())
        except (ValueError, TypeError):
            return
        try:
            if key == "heads":
                m = cm.set_heads(m, want)
            else:
                have = current_counts()[key]
                ops = {
                    "factories": (cm.add_factory, cm.remove_factory),
                    "extractors": (cm.add_extractor, cm.remove_extractor),
                    "launch_pads": (lambda x: cm.add_hub(x, "Launch Pad"),
                                    lambda x: cm.remove_hub(x, "Launch Pad")),
                    "storage": (lambda x: cm.add_hub(x, "Storage Facility"),
                                lambda x: cm.remove_hub(x, "Storage Facility")),
                }[key]
                for _ in range(abs(want - have)):
                    m = ops[0](m) if want > have else ops[1](m)
        except (cm.EditError, cm.ParseError) as e:
            messagebox.showwarning("Cannot apply", str(e), parent=win)
        state["model"] = m
        refresh()

    for key, label in COUNTERS:
        cell = ttk.Frame(ctr_frame)
        cell.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(cell, text=label, bg=EVE["bg_deep"], fg=EVE["fg_dim"],
                 font=("Segoe UI", 8)).pack(anchor=tk.W)
        var = tk.StringVar()
        box = tk.Spinbox(cell, from_=0, to=99, width=5, textvariable=var,
                         bg=EVE["bg_input"], fg=EVE["fg_bright"],
                         relief=tk.FLAT, font=("Consolas", 10),
                         command=lambda k=key: apply_counter(k))
        box.bind("<Return>", lambda _e, k=key: apply_counter(k))
        box.bind("<FocusOut>", lambda _e, k=key: apply_counter(k))
        box.pack()
        counter_vars[key], counter_boxes[key] = var, box

    # ── Rangée rayon / CC / nom ──────────────────────────────────────────
    meta = ttk.Frame(win)
    meta.pack(fill=tk.X, padx=10, pady=(4, 2))

    tk.Label(meta, text="Radius km", bg=EVE["bg_deep"], fg=EVE["fg_dim"],
             font=("Segoe UI", 8)).pack(side=tk.LEFT)
    radius_var = tk.StringVar()
    radius_entry = tk.Entry(meta, textvariable=radius_var, width=8,
                            bg=EVE["bg_input"], fg=EVE["fg_bright"],
                            relief=tk.FLAT, font=("Consolas", 10))
    radius_entry.pack(side=tk.LEFT, padx=(4, 12))

    tk.Label(meta, text="CC", bg=EVE["bg_deep"], fg=EVE["fg_dim"],
             font=("Segoe UI", 8)).pack(side=tk.LEFT)
    cc_var = tk.StringVar()
    cc_box = tk.Spinbox(meta, from_=0, to=5, width=3, textvariable=cc_var,
                        bg=EVE["bg_input"], fg=EVE["fg_bright"],
                        relief=tk.FLAT, font=("Consolas", 10),
                        command=lambda: apply_meta())
    cc_box.pack(side=tk.LEFT, padx=(4, 12))

    tk.Label(meta, text="Name", bg=EVE["bg_deep"], fg=EVE["fg_dim"],
             font=("Segoe UI", 8)).pack(side=tk.LEFT)
    name_var = tk.StringVar()
    name_entry = tk.Entry(meta, textvariable=name_var,
                          bg=EVE["bg_input"], fg=EVE["fg_bright"],
                          relief=tk.FLAT, font=("Segoe UI", 9))
    name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
    name_entry.bind("<KeyRelease>", lambda _e: state.update(name_touched=True))

    def apply_meta(_event=None):
        m = state["model"]
        if m is None:
            return
        try:
            m = cm.set_radius_km(m, float(radius_var.get()))
        except (ValueError, TypeError):
            pass
        try:
            m = cm.set_cc_level(m, int(cc_var.get()))
        except (ValueError, TypeError):
            pass
        m = cm.set_comment(m, name_var.get())
        state["model"] = m
        refresh()

    radius_entry.bind("<Return>", apply_meta)
    radius_entry.bind("<FocusOut>", apply_meta)
    cc_box.bind("<Return>", apply_meta)
    cc_box.bind("<FocusOut>", apply_meta)
    name_entry.bind("<FocusOut>", apply_meta)

    # ── Bandeau de validation ────────────────────────────────────────────
    strip = tk.Canvas(win, bg=EVE["bg_deep"], highlightthickness=0, height=56)
    strip.pack(fill=tk.X, padx=10, pady=(4, 2))

    def draw_strip(analysis):
        c = strip
        c.delete("all")
        right = max(300, c.winfo_width() - 8)
        y = 6

        def bar(label, used, cap, x0, x1):
            pct = used / cap if cap else 0
            colour = (EVE["green"] if pct <= 0.9
                      else EVE["yellow"] if pct <= 1.0 else EVE["red"])
            c.create_text(x0, y, anchor=tk.NW, text=label,
                          fill=EVE["fg_dim"], font=("Segoe UI", 8))
            c.create_text(x1, y, anchor=tk.NE, text=f"{used:,} / {cap:,}",
                          fill=colour, font=("Consolas", 8))
            ty = y + 14
            c.create_rectangle(x0, ty, x1, ty + 3, outline="", fill=EVE["bg_input"])
            c.create_rectangle(x0, ty, x0 + (x1 - x0) * min(pct, 1.0), ty + 3,
                               outline="", fill=colour)

        mid = 8 + (right - 8) // 2
        bar("CPU", analysis["cpu_used"], analysis["cpu_max"], 8, mid - 10)
        bar("PWR", analysis["power_used"], analysis["power_max"], mid + 10, right)
        y += 26

        # Runs line — mirrors PI._refresh_layout_panel, minus an "asked"
        # target: the editor has no interval setting to compare against.
        runs = analysis["buffer_hours"]
        if runs == float("inf"):
            runs_txt, runs_col = "nothing accumulates — collect whenever", EVE["green"]
        else:
            runs_txt = f"runs {runs:.0f}h untended"
            runs_col = EVE["green"] if runs >= 24 else EVE["orange"]
        c.create_text(8, y, anchor=tk.NW, text=runs_txt, fill=runs_col,
                      font=("Segoe UI", 9, "bold"))
        y += 16

        if analysis["p0_supply_h"]:
            fed = analysis["p0_supply_h"] >= analysis["p0_demand_h"]
            c.create_text(8, y, anchor=tk.NW,
                          text=f"extract {analysis['p0_supply_h']:,.0f}/h   ·   factories use "
                               f"{analysis['p0_demand_h']:,.0f}/h",
                          fill=EVE["green"] if fed else EVE["red"], font=("Consolas", 8))
            y += 16

        # Only real budget overruns get the hard-red ⚠ treatment; storage and
        # extractor-balance warnings are already conveyed by the softer lines
        # above and depend on assumed options this template doesn't carry.
        budget_warnings = [w for w in analysis["warnings"]
                           if w.startswith("CPU over budget")
                           or w.startswith("Power over budget")]
        for warn in budget_warnings:
            c.create_text(8, y, anchor=tk.NW, text=f"⚠ {warn}",
                          fill=EVE["red"], font=("Segoe UI", 8), width=right - 16)
            y += 14 * (1 + len(warn) // 60)
        c.config(height=max(56, y + 2))

    # ── Boutons ──────────────────────────────────────────────────────────
    btns = ttk.Frame(win)
    btns.pack(fill=tk.X, padx=10, pady=(2, 4))

    def styled(parent, text, cmd, strong=False):
        return tk.Button(parent, text=text, command=cmd,
                         font=("Segoe UI", 9, "bold"),
                         bg=EVE["accent_dim"] if strong else EVE["bg_card"],
                         fg=EVE["fg_bright"] if strong else EVE["fg"],
                         activebackground=EVE["accent"] if strong else EVE["border_hi"],
                         activeforeground="white" if strong else EVE["fg_bright"],
                         relief=tk.FLAT, cursor="hand2")

    def do_fit():
        m = state["model"]
        if m is None:
            return
        try:
            fitted, removed, fits = cm.fit_to_planet(m)
        except (cm.EditError, cm.ParseError) as e:
            messagebox.showwarning("Cannot apply", str(e), parent=win)
            return
        state["model"] = fitted
        refresh()
        if removed == 0 and fits:
            msg = "Already inside the budget — nothing removed."
        elif fits:
            msg = f"Removed {removed} factor{'y' if removed == 1 else 'ies'} to fit."
        else:
            msg = (f"Removed {removed} — still over budget at one factory. "
                   "This planet needs a higher CC level or a smaller layout.")
        messagebox.showinfo("Fit to planet", msg, parent=win)

    def do_copy():
        win.clipboard_clear()
        win.clipboard_append(json.dumps(current_template(), default=str))
        messagebox.showinfo("Copied", "Template JSON copied to clipboard!\n\n"
                            "Paste into EVE Online PI import.", parent=win)

    styled(btns, "🧲 Fit to planet", do_fit, strong=True).pack(side=tk.LEFT,
                                                              ipady=3, ipadx=8)
    styled(btns, "📋 Copy JSON", do_copy).pack(side=tk.LEFT, padx=(8, 0),
                                               ipady=3, ipadx=8)
    styled(btns, "💾 Save to Library", lambda: _save_library(win, state, name_var)
           ).pack(side=tk.LEFT, padx=(8, 0), ipady=3, ipadx=8)
    styled(btns, "⬇ Save to EVE Folder", lambda: _save_eve(win, state, name_var)
           ).pack(side=tk.LEFT, padx=(8, 0), ipady=3, ipadx=8)

    # ── JSON + carte ─────────────────────────────────────────────────────
    json_text = scrolledtext.ScrolledText(win, height=7, wrap=tk.WORD,
                                          bg=EVE["bg_input"], fg=EVE["json_fg"],
                                          font=("Consolas", 9), relief=tk.FLAT,
                                          insertbackground=EVE["json_fg"])
    json_text.pack(fill=tk.X, padx=10, pady=(2, 4))

    map_canvas = tk.Canvas(win, bg=EVE["bg_deep"], highlightthickness=0,
                           cursor="fleur")
    map_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
    view_state = {"zoom": 1.0, "pan_x": 0, "pan_y": 0,
                  "drag_start_x": 0, "drag_start_y": 0, "redraw_job": None}

    def on_scroll(event):
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        new_zoom = max(0.3, min(3.0, view_state["zoom"] * factor))
        factor = new_zoom / view_state["zoom"]
        if factor == 1.0:
            return
        view_state["zoom"] = new_zoom
        view_state["pan_x"] *= factor
        view_state["pan_y"] *= factor
        cw = map_canvas.winfo_width() or 700
        ch = map_canvas.winfo_height() or 500
        map_canvas.scale("map", cw / 2, ch / 2, factor, factor)
        if view_state["redraw_job"]:
            win.after_cancel(view_state["redraw_job"])
        view_state["redraw_job"] = win.after(
            120, lambda: (view_state.update(redraw_job=None),
                          app._draw_map(map_canvas, current_template(), view_state)))

    def on_drag_start(event):
        map_canvas.delete("tooltip")
        view_state["drag_start_x"], view_state["drag_start_y"] = event.x, event.y

    def on_drag(event):
        dx = event.x - view_state["drag_start_x"]
        dy = event.y - view_state["drag_start_y"]
        view_state["drag_start_x"], view_state["drag_start_y"] = event.x, event.y
        view_state["pan_x"] += dx
        view_state["pan_y"] += dy
        map_canvas.move("map", dx, dy)

    map_canvas.bind("<MouseWheel>", on_scroll)
    map_canvas.bind("<Button-1>", on_drag_start)
    map_canvas.bind("<B1-Motion>", on_drag)

    # ── Rafraîchissement ─────────────────────────────────────────────────
    def current_template():
        m = state["model"]
        return m.to_template() if m is not None else state["template"]

    def refresh():
        tpl = current_template()
        analysis = analyze_template(tpl)
        state["analysis"] = analysis
        draw_strip(analysis)
        json_text.delete("1.0", tk.END)
        json_text.insert("1.0", json.dumps(tpl, default=str))
        app._draw_map(map_canvas, tpl, view_state)

        m = state["model"]
        if m is None:
            for box in counter_boxes.values():
                box.config(state=tk.DISABLED)
            return
        counts = current_counts()
        flags = cm.editability(m)
        for key, _label in COUNTERS:
            counter_vars[key].set(str(counts[key]))
            counter_boxes[key].config(
                state=tk.NORMAL if flags[key] is None else tk.DISABLED)
        radius_var.set(f"{cm.radius_km(m):.0f}")
        cc_var.set(str(m.cc_level))
        if not state["name_touched"]:
            name_var.set(m.comment)

    if parse_reason:
        tk.Label(win, text=f"⚠ Read-only: {parse_reason}",
                 bg=EVE["bg_deep"], fg=EVE["red"],
                 font=("Segoe UI", 9, "bold")).pack(fill=tk.X, padx=10,
                                                    before=ctr_frame)
    win.update_idletasks()
    refresh()
    win.lift()
    win.focus_force()


# ── Sauvegardes ──────────────────────────────────────────────────────────

def _clean_name(raw):
    return "".join(ch for ch in raw.strip() if ch not in '\\/:*?"<>|')


def _write_json(path, template):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(template, fh, default=str)


def _save_library(win, state, name_var):
    """data/templates/Custom - <nom>.json — jamais par-dessus un fichier fourni.

    Pas de git ici : écraser un template DalShooth serait définitif, d'où le
    refus pur et simple hors du préfixe Custom.
    """
    import os
    import PI
    name = _clean_name(name_var.get()) or "Unnamed"
    if not state.get("name_touched"):
        name_var.set(name)
    m = state["model"]
    if m is not None:
        state["model"] = cm.set_comment(m, name_var.get() or name)
    fname = f"Custom - {name}.json"
    lib_dir = os.path.join(PI.get_base_path(), "data", "templates")
    path = os.path.join(lib_dir, fname)
    if os.path.exists(path):
        if not messagebox.askyesno("Overwrite?",
                f"{fname} already exists in the library. Replace it?",
                parent=win):
            return
    tpl = (state["model"].to_template() if state["model"] is not None
           else state["template"])
    try:
        _write_json(path, tpl)
    except OSError as e:
        messagebox.showerror("Save failed", str(e), parent=win)
        return
    messagebox.showinfo("Saved", f"Saved to the library as:\n{fname}", parent=win)


def _save_eve(win, state, name_var):
    import os
    name = _clean_name(name_var.get()) or "Unnamed"
    target = os.path.join(os.path.expanduser("~"), "Documents",
                          "EVE", "PlanetaryInteractionTemplates")
    path = os.path.join(target, f"{name}.json")
    if os.path.exists(path):
        if not messagebox.askyesno("Overwrite?",
                f"{name}.json already exists in the EVE folder. Replace it?",
                parent=win):
            return
    tpl = (state["model"].to_template() if state["model"] is not None
           else state["template"])
    try:
        os.makedirs(target, exist_ok=True)
        _write_json(path, tpl)
    except OSError as e:
        messagebox.showerror("Save failed", str(e), parent=win)
        return
    messagebox.showinfo("Saved",
        f"Saved to your EVE folder.\n\nRestart the EVE client (or relog) "
        "to see it in PI import.", parent=win)
