"""Файлы планов X-Plane .fms (v1100 и устаревший v3) из <X-Plane>/Output/FMS plans.

Формат v1100: https://developer.x-plane.com/article/flightplan-files-v11-fms-file-format/
Zibo: RTE стр.1 -> имя в блокнот -> SAVE ROUTE (RSK3) записывает <имя>.fms в Output/FMS plans
(формат FMS/FMX выбирается в EFB). Через CO ROUTE Zibo загружает .fms оттуда же (напр. из SimBrief).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .model import FlightPlan, Waypoint, norm_icao, norm_proc, norm_rwy

SRC = "fms-файл"


def parse_fms(text: str, source: str = SRC) -> FlightPlan:
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln]
    fp = FlightPlan()
    if len(lines) < 2:
        raise ValueError("слишком короткий файл .fms")
    ver_tokens = lines[1].split()
    version = ver_tokens[0] if ver_tokens else ""
    if version not in ("1100", "3"):
        raise ValueError(f"неизвестная версия .fms: {lines[1]!r}")
    keys = {"ADEP": ("origin", norm_icao), "ADES": ("dest", norm_icao),
            "DEPRWY": ("dep_rwy", norm_rwy), "DESRWY": ("arr_rwy", norm_rwy),
            "SID": ("sid", norm_proc), "SIDTRANS": ("sid_trans", norm_proc),
            "STAR": ("star", norm_proc), "STARTRANS": ("star_trans", norm_proc),
            "APP": ("approach", norm_proc), "APPTRANS": ("app_trans", norm_proc)}
    wpts: List[Waypoint] = []
    max_alt = 0.0
    if version == "1100":
        for ln in lines[2:]:
            tok = ln.split()
            k = tok[0].upper()
            if k in keys and len(tok) >= 2:
                f, norm = keys[k]
                fp.set(f, norm(tok[1]), source)
            elif k in ("NUMENR", "CYCLE", "DEP", "DES"):
                continue
            elif tok[0].isdigit() and len(tok) >= 6:
                try:
                    w = Waypoint(ident=tok[1].upper(), via=tok[2].upper(), alt_ft=float(tok[3]),
                                 lat=float(tok[4]), lon=float(tok[5]), kind=int(tok[0]))
                except ValueError:
                    continue
                wpts.append(w)
    else:   # v3: "3 version", "1", "N", затем "type ident alt lat lon"
        body = lines[2:]
        if len(body) >= 2 and body[1].split()[0].isdigit() and len(body[1].split()) == 1:
            body = body[2:]
        for ln in body:
            tok = ln.split()
            if len(tok) >= 5 and tok[0].isdigit():
                try:
                    wpts.append(Waypoint(ident=tok[1].upper(), alt_ft=float(tok[2]), lat=float(tok[3]),
                                         lon=float(tok[4]), kind=int(tok[0])))
                except ValueError:
                    continue
        if wpts and wpts[0].kind == 1:
            fp.set("origin", norm_icao(wpts[0].ident), source)
        if wpts and wpts[-1].kind == 1:
            fp.set("dest", norm_icao(wpts[-1].ident), source)
    for w in wpts:
        if w.kind == 1 and w.has_pos and w.ident == fp.origin and fp.origin_pos is None:
            fp.origin_pos = (w.lat, w.lon, w.alt_ft)
        if w.kind == 1 and w.has_pos and w.ident == fp.dest:
            fp.dest_pos = (w.lat, w.lon, w.alt_ft)
    # аэропорты в начале/конце — не точки маршрута
    route = [w for w in wpts if not (w.kind == 1 and w.ident in (fp.origin, fp.dest))]
    for w in route:
        max_alt = max(max_alt, w.alt_ft)
    fp.waypoints = route
    if route:
        fp.sources["waypoints"] = source
    # Высота в точках .fms — это ограничения/расчёт, не эшелон крейсерского полёта; берём только явно большую
    if max_alt >= 10000:
        fp.set("cruise_fl", int(round(max_alt / 1000.0)) * 10, source + "(макс. высота точек)")
    return fp


def guess_xplane_paths() -> List[Path]:
    """Возможные папки X-Plane 12. ПРЕДПОЛОЖЕНИЕ: установщик X-Plane пишет список установок
    в %LOCALAPPDATA%\\x-plane_install_12.txt (Windows) / ~/.x-plane/x-plane_install_12.txt."""
    out: List[Path] = []
    cands = []
    if sys.platform.startswith("win"):
        la = os.environ.get("LOCALAPPDATA")
        if la:
            cands.append(Path(la) / "x-plane_install_12.txt")
    cands.append(Path.home() / ".x-plane" / "x-plane_install_12.txt")
    cands.append(Path.home() / "Library" / "Preferences" / "x-plane_install_12.txt")
    for c in cands:
        try:
            for ln in c.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if ln:
                    out.append(Path(ln))
        except OSError:
            pass
    for p in ("C:/X-Plane 12", "D:/X-Plane 12", "E:/X-Plane 12",
              "C:/Program Files (x86)/Steam/steamapps/common/X-Plane 12",
              "D:/SteamLibrary/steamapps/common/X-Plane 12"):
        out.append(Path(p))
    seen, res = set(), []
    for p in out:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            res.append(p)
    return res


def fms_dir_missing_message(xplane_path: str = "") -> str:
    """Пояснение, если Output/FMS plans не найдена: какой путь смотрели и куда писать настройку."""
    if xplane_path:
        tried = str(Path(xplane_path) / "Output" / "FMS plans")
        where = f"проверен путь {tried}"
    else:
        cands = [str(p / "Output" / "FMS plans") for p in guess_xplane_paths()[:6]]
        where = ("автопоиск, проверены: " + "; ".join(cands)) if cands else "автопоиск ничего не дал"
    return (f"папка Output/FMS plans не найдена ({where}). "
            "Укажите flight_plan_import.xplane_path в config.yaml — папка установки X-Plane 12, "
            "например \"D:/X-Plane 12\" (внутри неё должна быть Output/FMS plans), "
            "или запустите python tools/fmcdump.py --xplane \"D:/X-Plane 12\".")


def fms_dir(xplane_path: str = "") -> Optional[Path]:
    """Папка Output/FMS plans: из настройки или автопоиском. None — не найдена."""
    paths = [Path(xplane_path)] if xplane_path else guess_xplane_paths()
    for p in paths:
        if p.name.lower() == "fms plans" and p.is_dir():
            return p
        d = p / "Output" / "FMS plans"
        if d.is_dir():
            return d
    return None


def list_fms(directory: Path, limit: int = 10) -> List[Tuple[Path, float]]:
    files = []
    try:
        for f in directory.iterdir():
            if f.is_file() and f.suffix.lower() == ".fms":
                files.append((f, f.stat().st_mtime))
    except OSError:
        return []
    files.sort(key=lambda x: x[1], reverse=True)
    return files[:limit]


def latest_fms(directory: Path, origin: str = "", dest: str = "", max_age_h: float = 0,
               now: Optional[float] = None) -> Optional[Path]:
    """Самый свежий .fms. Если известны origin/dest (из FMC) — самый свежий с совпадающими ADEP/ADES.
    max_age_h > 0 — файлы старше не берём, если нет совпадения по аэропортам."""
    now = now or time.time()
    files = list_fms(directory, limit=50)
    if origin or dest:
        for f, _ in files:
            try:
                fp = parse_fms(f.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError):
                continue
            if (not origin or fp.origin == origin) and (not dest or fp.dest == dest):
                return f
        return None
    for f, mt in files:
        if max_age_h and now - mt > max_age_h * 3600:
            return None
        return f
    return None


def load_fms(path: Path) -> FlightPlan:
    fp = parse_fms(path.read_text(encoding="utf-8", errors="replace"), source=f"{SRC} {path.name}")
    return fp
