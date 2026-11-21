"""Окно tkinter: фаза, частоты, разрешения, план FMC, последние передачи, ввод текстом, кнопка тангенты.
Режимы: полный и компактная полупрозрачная панель поверх X-Plane (см. ru_atc/window.py)."""
from __future__ import annotations

import queue
import sys
import tkinter as tk
from tkinter import scrolledtext

from .phases import PHASE_RU, Phase
from .window import WindowController, register_hotkeys


def run_tk(app):
    ui_cfg = app.cfg.get("ui") or {}
    root = tk.Tk()
    root.title("RU ATC — голосовой диспетчер X-Plane 12")
    root.configure(bg="#1e1e1e")
    fg, bg = "#e0e0e0", "#1e1e1e"
    font = ("Segoe UI", 10) if sys.platform == "win32" else ("DejaVu Sans", 10)
    small = (font[0], 9)

    # ------------------------------------------------------------ полный режим
    full = tk.Frame(root, bg=bg)
    top = tk.Frame(full, bg=bg)
    top.pack(fill="x", padx=8, pady=6)
    vars_ = {k: tk.StringVar(value="-") for k in
             ("phase", "conn", "com", "alt", "spd", "sq", "cleared", "ctrl", "handoff", "rwy", "pending")}
    rows = [("Фаза", "phase"), ("Связь с X-Plane", "conn"), ("COM1 акт/рез", "com"), ("Высота / VS", "alt"),
            ("IAS / GS", "spd"), ("Ответчик", "sq"), ("Разрешено", "cleared"), ("Работаете с", "ctrl"),
            ("Передан на", "handoff"), ("ВПП выл/пос", "rwy"), ("Ждём readback", "pending")]
    for i, (lbl, key) in enumerate(rows):
        tk.Label(top, text=lbl + ":", fg="#9cdcfe", bg=bg, font=font, anchor="w").grid(row=i % 6, column=(i // 6) * 2, sticky="w", padx=4)
        tk.Label(top, textvariable=vars_[key], fg=fg, bg=bg, font=font, anchor="w", width=36).grid(row=i % 6, column=(i // 6) * 2 + 1, sticky="w")

    plan_var = tk.StringVar(value="План: нет (config.yaml)")
    tk.Label(full, textvariable=plan_var, fg="#c586c0", bg=bg, font=font, anchor="w", justify="left",
             wraplength=1060).pack(fill="x", padx=12)

    log = scrolledtext.ScrolledText(full, bg="#111", fg=fg, font=font, wrap="word", height=20)
    log.pack(fill="both", expand=True, padx=8, pady=4)
    log.tag_config("atc", foreground="#4ec9b0")
    log.tag_config("pilot", foreground="#dcdcaa")
    log.tag_config("hint", foreground="#ce9178")
    log.tag_config("info", foreground="#808080")

    bottom = tk.Frame(full, bg=bg)
    bottom.pack(fill="x", padx=8, pady=6)
    entry = tk.Entry(bottom, font=font, bg="#2d2d2d", fg=fg, insertbackground=fg)
    entry.pack(side="left", fill="x", expand=True)

    def send(_=None):
        t = entry.get().strip()
        if t:
            entry.delete(0, "end")
            app.pilot_says(t)
    entry.bind("<Return>", send)
    tk.Button(bottom, text="Передать текст", command=send).pack(side="left", padx=4)
    ptt_btn = tk.Button(bottom, text="🎙 Тангента (удерживать)", bg="#3a3a3a", fg=fg)
    ptt_btn.pack(side="left", padx=4)
    ptt_btn.bind("<ButtonPress-1>", lambda e: app.ptt and app.ptt.ui_press())
    ptt_btn.bind("<ButtonRelease-1>", lambda e: app.ptt and app.ptt.ui_release())
    top_var = tk.BooleanVar(value=bool(ui_cfg.get("always_on_top", True)))
    tk.Checkbutton(bottom, text="Поверх всех", variable=top_var, bg=bg, fg=fg, selectcolor="#2d2d2d",
                   activebackground=bg, command=lambda: win.set_topmost(top_var.get())).pack(side="left", padx=4)
    tk.Button(bottom, text="Компактно", command=lambda: win.toggle_compact()).pack(side="left", padx=4)

    # ------------------------------------------------------------ компактная панель
    compact = tk.Frame(root, bg="#101010", highlightthickness=1, highlightbackground="#3a3a3a")
    c_head = tk.Frame(compact, bg="#101010")
    c_head.pack(fill="x")
    c_state = tk.StringVar(value="-")
    c_last = tk.StringVar(value="")
    c_plan = tk.StringVar(value="")
    c_state_lbl = tk.Label(c_head, textvariable=c_state, fg="#9cdcfe", bg="#101010", font=small, anchor="w")
    c_state_lbl.pack(side="left", fill="x", expand=True, padx=4)
    c_ptt = tk.Label(c_head, text="●", fg="#444", bg="#101010", font=small)
    c_ptt.pack(side="left")
    tk.Button(c_head, text="⤢", font=small, bd=0, bg="#101010", fg=fg, command=lambda: win.set_compact(False)).pack(side="left", padx=2)
    tk.Button(c_head, text="—", font=small, bd=0, bg="#101010", fg=fg, command=lambda: win.hide()).pack(side="left", padx=2)
    c_last_lbl = tk.Label(compact, textvariable=c_last, fg="#4ec9b0", bg="#101010", font=font, anchor="nw",
                          justify="left", wraplength=540)
    c_last_lbl.pack(fill="both", expand=True, padx=4)
    tk.Label(compact, textvariable=c_plan, fg="#c586c0", bg="#101010", font=small, anchor="w").pack(fill="x", padx=4)

    # перетаскивание безрамочной панели мышью
    drag = {"x": 0, "y": 0}

    def start_drag(e):
        drag["x"], drag["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def do_drag(e):
        root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")
    for w in (compact, c_head, c_state_lbl, c_last_lbl):
        w.bind("<ButtonPress-1>", start_drag)
        w.bind("<B1-Motion>", do_drag)
    compact.bind("<Double-Button-1>", lambda e: win.set_compact(False))

    def on_mode(is_compact: bool):
        if is_compact:
            full.pack_forget()
            compact.pack(fill="both", expand=True)
        else:
            compact.pack_forget()
            full.pack(fill="both", expand=True)

    full.pack(fill="both", expand=True)
    win = WindowController(root, ui_cfg, on_mode=on_mode)
    app.window = win

    def add(text, tag):
        log.insert("end", text + "\n", tag)
        log.see("end")

    def poll():
        try:
            while True:
                kind, p = app.ui_q.get_nowait()
                if kind == "atc":
                    add(f"▶ [{p.unit.callsign} {p.unit.freq:.3f}] {p.display}", "atc")
                    c_last.set(f"{p.unit.callsign}: {p.display}")
                elif kind == "pilot":
                    add(f"◀ ПИЛОТ: {p.text}   [{p.intent}]", "pilot")
                elif kind == "hint":
                    add(f"· {p.text}" if p.key == "phase" else f"⚠ {p.text}", "info" if p.key == "phase" else "hint")
                    if p.key != "phase":
                        c_last.set(f"⚠ {p.text}")
                elif kind == "info":
                    add(f"ℹ {p}", "info")
                elif kind == "hint_text":
                    add(f"⚠ {p}", "hint")
                elif kind == "ui_cmd":
                    win.command(p)
                elif kind == "ptt":
                    ptt_btn.configure(bg="#a33" if p else "#3a3a3a")
                    c_ptt.configure(fg="#f44" if p else "#444")
                elif kind == "state":
                    s, st, err = p
                    vars_["phase"].set(f"{st['phase']} — {PHASE_RU.get(Phase(st['phase']), '')}")
                    vars_["conn"].set("OK" if s.connected else f"нет данных {('— ' + err) if err else ''}"[:60])
                    vars_["com"].set(f"{s.com1_khz / 1000:.3f} / {s.com1_stby_khz / 1000:.3f}")
                    vars_["alt"].set(f"{s.alt_ind_ft:.0f} ft / {s.vs_fpm:+.0f} fpm")
                    vars_["spd"].set(f"{s.ias_kt:.0f} / {s.gs_kt:.0f} kt")
                    vars_["sq"].set(f"{s.xpdr_code:04d} режим {s.xpdr_mode} (назначен {st['squawk']})")
                    vars_["cleared"].set(st["cleared"])
                    vars_["ctrl"].set(st["controlling"])
                    vars_["handoff"].set(st["handoff"])
                    vars_["rwy"].set(f"{st['dep_rwy']} / {st['arr_rwy']}")
                    vars_["pending"].set(st["pending"])
                    plan_var.set(f"Маршрут: {st.get('route', '-')}   |   План FMC: {st.get('plan', '-')}")
                    c_state.set(f"{st['phase']} | {st['controlling']} | {st['cleared']} | SQ {st['squawk']}"
                                + ("" if s.connected else " | нет связи с X-Plane"))
                    c_plan.set("План: " + st.get("plan", "-"))
        except queue.Empty:
            pass
        root.after(200, poll)

    app.start()
    win.apply_initial()
    for m in register_hotkeys(ui_cfg, lambda cmd: app.ui_q.put(("ui_cmd", cmd))):
        app.ui_q.put(("hint_text", m))
    poll()
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop(), root.destroy()))
    root.mainloop()
