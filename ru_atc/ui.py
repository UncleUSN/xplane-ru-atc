"""Минимальное окно tkinter: фаза, частоты, разрешения, последние передачи, ввод текстом, кнопка тангенты."""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import scrolledtext

from .phases import PHASE_RU, Phase


def run_tk(app):
    root = tk.Tk()
    root.title("RU ATC — голосовой диспетчер X-Plane 12")
    root.geometry("1100x680")
    root.configure(bg="#1e1e1e")
    fg, bg = "#e0e0e0", "#1e1e1e"
    import sys
    font = ("Segoe UI", 10) if sys.platform == "win32" else ("DejaVu Sans", 10)

    top = tk.Frame(root, bg=bg)
    top.pack(fill="x", padx=8, pady=6)
    vars_ = {k: tk.StringVar(value="-") for k in
             ("phase", "conn", "com", "alt", "spd", "sq", "cleared", "ctrl", "handoff", "rwy", "pending")}
    rows = [("Фаза", "phase"), ("Связь с X-Plane", "conn"), ("COM1 акт/рез", "com"), ("Высота / VS", "alt"),
            ("IAS / GS", "spd"), ("Ответчик", "sq"), ("Разрешено", "cleared"), ("Работаете с", "ctrl"),
            ("Передан на", "handoff"), ("ВПП выл/пос", "rwy"), ("Ждём readback", "pending")]
    for i, (lbl, key) in enumerate(rows):
        tk.Label(top, text=lbl + ":", fg="#9cdcfe", bg=bg, font=font, anchor="w").grid(row=i % 6, column=(i // 6) * 2, sticky="w", padx=4)
        tk.Label(top, textvariable=vars_[key], fg=fg, bg=bg, font=font, anchor="w", width=36).grid(row=i % 6, column=(i // 6) * 2 + 1, sticky="w")

    log = scrolledtext.ScrolledText(root, bg="#111", fg=fg, font=font, wrap="word", height=20)
    log.pack(fill="both", expand=True, padx=8, pady=4)
    log.tag_config("atc", foreground="#4ec9b0")
    log.tag_config("pilot", foreground="#dcdcaa")
    log.tag_config("hint", foreground="#ce9178")
    log.tag_config("info", foreground="#808080")

    bottom = tk.Frame(root, bg=bg)
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

    def add(text, tag):
        log.insert("end", text + "\n", tag)
        log.see("end")

    def poll():
        try:
            while True:
                kind, p = app.ui_q.get_nowait()
                if kind == "atc":
                    add(f"▶ [{p.unit.callsign} {p.unit.freq:.3f}] {p.display}", "atc")
                elif kind == "pilot":
                    add(f"◀ ПИЛОТ: {p.text}   [{p.intent}]", "pilot")
                elif kind == "hint":
                    add(f"· {p.text}" if p.key == "phase" else f"⚠ {p.text}", "info" if p.key == "phase" else "hint")
                elif kind == "info":
                    add(f"ℹ {p}", "info")
                elif kind == "hint_text":
                    add(f"⚠ {p}", "hint")
                elif kind == "ptt":
                    ptt_btn.configure(bg="#a33" if p else "#3a3a3a")
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
        except queue.Empty:
            pass
        root.after(200, poll)

    app.start()
    poll()
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop(), root.destroy()))
    root.mainloop()
