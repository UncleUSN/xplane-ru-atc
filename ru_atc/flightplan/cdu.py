"""Разбор экрана CDU Zibo 737 (строковые datarefs laminar/B738/fmc1/LineNN_*).

ПРОВЕРЕНО (B738_Datarefs.txt rel. 2.35 + форум Zibo): строки по 24 символа,
  Line00_L / Line00_S — заголовок страницы; LineNN_X — мелкая подпись над строкой NN (NN=01..06);
  LineNN_L — крупный шрифт, LineNN_S — мелкий, LineNN_I — инверсный; Line_entry — блокнот.
ПО ФОРУМУ (не в официальном списке): цветовые слои LineNN_M (magenta), _G (green), _C (cyan), _GX, _LX, _SI.
Слои накладываются посимвольно: в каждой позиции берём первый непустой символ.

Раскладка страниц — стандартная Boeing 737 (ПРЕДПОЛОЖЕНИЕ, что Zibo пишет подписи именно так:
ORIGIN/DEST, RUNWAY/FLT NO., VIA/TO, SIDS/RUNWAYS/TRANS, STARS/APPROACHES, CRZ ALT, <SEL>/<ACT>).
Парсер нечувствителен к точным позициям: делит строку на левую и правую половины.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import (AIRWAY_RE, FLTNO_RE, PROC_RE, FlightPlan, Waypoint, approach_runway, norm_icao,
                    norm_proc, norm_rwy, parse_cruise_fl)

WIDTH = 24
DATA_LAYERS = ("L", "I", "M", "G", "C", "S", "SI")
LABEL_LAYERS = ("X", "LX", "GX")
TITLE_LAYERS = ("L", "S", "I", "M", "G", "C")


def cdu_dataref_names(side: int = 1) -> List[str]:
    pfx = f"laminar/B738/fmc{side}/"
    names = [pfx + f"Line00_{l}" for l in TITLE_LAYERS]
    for n in range(1, 7):
        for l in DATA_LAYERS + LABEL_LAYERS:
            names.append(pfx + f"Line{n:02d}_{l}")
    names += [pfx + "Line_entry", pfx + "Line_entry_I"]
    return names


def overlay(parts: List[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    n = max(len(p) for p in parts)
    out = []
    for i in range(n):
        ch = " "
        for p in parts:
            if i < len(p) and p[i] not in " \x00":
                ch = p[i]
                break
        out.append(ch)
    return "".join(out).rstrip()


@dataclass
class Screen:
    title: str = ""
    rows: List[Tuple[str, str]] = field(default_factory=list)   # 6 x (подпись, данные)
    scratch: str = ""

    @classmethod
    def from_values(cls, values: Dict[str, str], side: int = 1) -> "Screen":
        pfx = f"laminar/B738/fmc{side}/"

        def g(k):
            v = values.get(pfx + k, "")
            return v if isinstance(v, str) else ""
        title = overlay([g(f"Line00_{l}") for l in TITLE_LAYERS])
        rows = []
        for n in range(1, 7):
            lab = overlay([g(f"Line{n:02d}_{l}") for l in LABEL_LAYERS])
            dat = overlay([g(f"Line{n:02d}_{l}") for l in DATA_LAYERS])
            rows.append((lab, dat))
        return cls(title=title, rows=rows, scratch=overlay([g("Line_entry"), g("Line_entry_I")]))

    @classmethod
    def from_text(cls, title: str, rows: List[Tuple[str, str]]) -> "Screen":
        return cls(title=title, rows=list(rows) + [("", "")] * (6 - len(rows)))

    def text(self) -> str:
        out = [f"[{self.title:<24}]"]
        for lab, dat in self.rows:
            out.append(f" {lab:<24} ")
            out.append(f" {dat:<24} ")
        out.append(f" {self.scratch:<24} ")
        return "\n".join(out)


SEG_RE = re.compile(r"\S+(?: \S+)*")
LEFT_SEL_RE = re.compile(r"([A-Z0-9\-\.]{2,8})\s*<(?:SEL|ACT)>")
RIGHT_SEL_RE = re.compile(r"<(SEL|ACT)>\s*([A-Z0-9\-\.]{2,8})")


def split_lr(row: str, width: int = WIDTH) -> Tuple[str, str]:
    """Левая и правая половины строки CDU (по позиции начала фрагмента)."""
    left, right = [], []
    half = width // 2
    for m in SEG_RE.finditer(row or ""):
        seg = m.group(0)
        if re.fullmatch(r"RTE ?\d", seg):     # «RTE 1» по центру страниц DEP/ARR
            continue
        (left if m.start() < half else right).append(seg)
    return " ".join(left).strip(), " ".join(right).strip()


def selected(seg: str) -> Optional[str]:
    if "<SEL>" in seg or "<ACT>" in seg:
        return seg.replace("<SEL>", "").replace("<ACT>", "").strip()
    return None


def page_no(title: str) -> Tuple[int, int]:
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*$", title)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


def page_kind(title: str) -> str:
    t = re.sub(r"\s+", " ", title.upper())
    if "DEPARTURES" in t:
        return "dep"
    if "ARRIVALS" in t:
        return "arr"
    if "PERF INIT" in t:
        return "perf"
    if "LEGS" in t and "RTE" in t:
        return "legs"
    if re.search(r"\bRTE\s?\d?\b", t) and not any(x in t for x in ("DATA", "HOLD", "WIND", "LEGS")):
        return "rte"
    return ""


def _section(label: str, current: str, names: Dict[str, str]) -> str:
    lab = label.upper()
    for k, v in names.items():
        if k in lab:
            return v
    return current


def is_placeholder(v: str) -> bool:
    return not v or set(v) <= set("-_.*□ ") or v.startswith("<") or v.endswith(">")


class CduCollector:
    """Копит данные плана по мере того, как пилот листает страницы CDU."""

    def __init__(self) -> None:
        self.fields: Dict[str, Tuple[str, object]] = {}   # поле -> (источник, значение)
        self.rte_pages: Dict[int, List[Tuple[str, str]]] = {}
        self.rte_total = 0
        self.legs_pages: Dict[int, List[str]] = {}
        self.legs_total = 0
        self.last_kind = ""
        self.seen_pages: List[str] = []

    def reset_route(self) -> None:
        self.rte_pages.clear()
        self.legs_pages.clear()
        for k in [k for k in self.fields if k not in ("origin", "dest", "flight_no", "cruise_fl")]:
            self.fields.pop(k, None)

    def _set(self, name: str, value, src: str) -> bool:
        if value in (None, ""):
            return False
        old = self.fields.get(name)
        if old and old[1] == value:
            return False
        self.fields[name] = (src, value)
        return True

    def feed(self, sc: Screen) -> bool:
        kind = page_kind(sc.title)
        self.last_kind = kind
        if not kind:
            return False
        if kind not in self.seen_pages:
            self.seen_pages.append(kind)
        return getattr(self, f"_feed_{kind}")(sc)

    # ---- RTE ----
    def _feed_rte(self, sc: Screen) -> bool:
        pg, total = page_no(sc.title)
        lab1 = sc.rows[0][0].upper()
        if "ORIGIN" in lab1 or ("DEST" in lab1 and pg == 1):
            changed = False
            o, d = split_lr(sc.rows[0][1])
            o, d = norm_icao(o), norm_icao(d)
            old_o = self.fields.get("origin", ("", ""))[1]
            old_d = self.fields.get("dest", ("", ""))[1]
            if (old_o and o and o != old_o) or (old_d and d and d != old_d):
                self.reset_route()      # новый маршрут — старые страницы недействительны
                changed = True
            changed |= self._set("origin", o, "CDU RTE")
            changed |= self._set("dest", d, "CDU RTE")
            for lab, dat in sc.rows[1:3]:
                ll, lr = split_lr(lab.upper())
                dl, dr = split_lr(dat)
                if "RUNWAY" in ll:
                    changed |= self._set("dep_rwy", norm_rwy(dl), "CDU RTE")
                if "FLT" in lr:
                    v = dr.replace(" ", "").upper()
                    changed |= self._set("flight_no", v if FLTNO_RE.match(v) else "", "CDU RTE")
            self.rte_total = max(self.rte_total, total)
            return changed
        # страницы VIA / TO
        entries = []
        for lab, dat in sc.rows:
            via, to = split_lr(dat)
            via, to = via.upper(), to.upper()
            if is_placeholder(via) and is_placeholder(to):
                continue
            if "-----" in dat or "THEN" in via:
                continue
            entries.append((via, to))
        old = self.rte_pages.get(pg)
        self.rte_total = total
        for k in [k for k in self.rte_pages if k > total]:
            self.rte_pages.pop(k)
        if old == entries:
            return False
        self.rte_pages[pg] = entries
        return True

    # ---- DEP / ARR ----
    def _proc_page(self, sc: Screen, left_names, right_names, src) -> Dict[str, str]:
        """Страницы DEP/ARR: слева пункты с суффиксом «<SEL>/<ACT>», справа — с префиксом.
        Колонки определяем по маркеру, а не по позиции (строки бывают «слипшимися»)."""
        lsec = rsec = ""
        out: Dict[str, str] = {}
        for lab, dat in sc.rows:
            ll, lr = split_lr(lab.upper())
            lsec = _section(ll, lsec, left_names) if ll else lsec
            rsec = _section(lr, rsec, right_names) if lr else rsec
            d = dat.upper()
            m = LEFT_SEL_RE.search(d)
            if m and lsec and m.start(1) < WIDTH // 2:
                out[lsec] = m.group(1)
            m = RIGHT_SEL_RE.search(d)
            if m and rsec and m.start() >= WIDTH // 2 - 2:
                out[rsec] = m.group(2)
        return out

    def _feed_dep(self, sc: Screen) -> bool:
        apt = norm_icao(sc.title.split()[0] if sc.title.split() else "")
        org = self.fields.get("origin", ("", ""))[1]
        if org and apt and apt != org:
            return False
        got = self._proc_page(sc, {"SID": "sid", "TRANS": "sid_trans"},
                              {"RUNWAY": "dep_rwy", "TRANS": "sid_trans"}, "CDU DEP")
        ch = self._set("origin", apt, "CDU DEP") if apt and not org else False
        for k, v in got.items():
            v = norm_rwy(v) if k == "dep_rwy" else norm_proc(v)
            ch |= self._set(k, v, "CDU DEP")
        return ch

    def _feed_arr(self, sc: Screen) -> bool:
        apt = norm_icao(sc.title.split()[0] if sc.title.split() else "")
        dst = self.fields.get("dest", ("", ""))[1]
        if dst and apt and apt != dst:
            return False
        got = self._proc_page(sc, {"STAR": "star", "TRANS": "star_trans"},
                              {"APPR": "approach", "RUNWAY": "arr_rwy", "TRANS": "app_trans"}, "CDU ARR")
        ch = self._set("dest", apt, "CDU ARR") if apt and not dst else False
        for k, v in got.items():
            v = norm_rwy(v) if k == "arr_rwy" else norm_proc(v)
            ch |= self._set(k, v, "CDU ARR")
        if "approach" in got and "arr_rwy" not in got:
            ch |= self._set("arr_rwy", approach_runway(got["approach"]), "CDU ARR")
        return ch

    # ---- PERF INIT ----
    def _feed_perf(self, sc: Screen) -> bool:
        for lab, dat in sc.rows:
            ll, lr = split_lr(lab.upper())
            dl, dr = split_lr(dat.upper())
            for l, d in ((lr, dr), (ll, dl)):
                if "CRZ ALT" in l:
                    fl = parse_cruise_fl(d)
                    if fl:
                        return self._set("cruise_fl", fl, "CDU PERF INIT")
        return False

    # ---- LEGS ----
    def _feed_legs(self, sc: Screen) -> bool:
        pg, total = page_no(sc.title)
        ids = []
        for lab, dat in sc.rows:
            left, _ = split_lr(dat.upper())
            tok = left.split()[0] if left.split() else ""
            if not tok or tok.startswith("(") or "-" in tok or "THEN" in tok or is_placeholder(tok):
                continue
            if re.fullmatch(r"[A-Z0-9]{2,7}", tok):
                ids.append(tok)
        self.legs_total = total
        for k in [k for k in self.legs_pages if k > total]:
            self.legs_pages.pop(k)
        if self.legs_pages.get(pg) == ids:
            return False
        self.legs_pages[pg] = ids
        return True

    # ---- результат ----
    def route_entries(self) -> List[Tuple[str, str]]:
        out = []
        for pg in sorted(self.rte_pages):
            out.extend(self.rte_pages[pg])
        return out

    def plan(self) -> FlightPlan:
        fp = FlightPlan()
        for k, (src, v) in self.fields.items():
            fp.set(k, v, src)
        ents = self.route_entries()
        # SID/STAR по странице RTE (VIA «LAKI1G» TO «LAKIB»), если не выбраны на DEP/ARR — менее надёжно
        if ents:
            v0, t0 = ents[0]
            if PROC_RE.match(v0) and not AIRWAY_RE.match(v0):
                fp.set("sid", v0, "CDU RTE(VIA)")
            vl, tl = ents[-1]
            if len(ents) > 1 and PROC_RE.match(vl) and not AIRWAY_RE.match(vl):
                fp.set("star", vl, "CDU RTE(VIA)")
        legs = []
        for pg in sorted(self.legs_pages):
            legs.extend(self.legs_pages[pg])
        if legs and len(self.legs_pages) >= max(1, self.legs_total):
            fp.waypoints = [Waypoint(i) for i in legs if i not in (fp.origin, fp.dest)]
            fp.sources["waypoints"] = "CDU LEGS"
        elif ents:
            fp.waypoints = [Waypoint(t, via=v) for v, t in ents if t and not is_placeholder(t)]
            fp.sources["waypoints"] = "CDU RTE"
        return fp.finalize()
