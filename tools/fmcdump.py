"""Диагностика импорта плана полёта из FMC Zibo 737.

Показывает, что нашёл каждый источник:
  1) Web API: версия, строковые datarefs экрана CDU (laminar/B738/fmc1/LineNN_*) и текущий экран;
  2) все datarefs с префиксом laminar/B738/fms/ (и FMS/), похожие на данные плана, с ЗНАЧЕНИЯМИ;
  3) файлы .fms в <X-Plane>/Output/FMS plans (5 самых свежих) и их разбор;
  4) итоговый объединённый план.
Отчёт дублируется в logs/fmcdump_<дата>.txt — пришлите его, чтобы закрепить точные имена datarefs.

  python tools/fmcdump.py                         # настройки из config.yaml
  python tools/fmcdump.py --xplane "D:/X-Plane 12" --watch 30   # 30 с следить за листанием страниц CDU
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ru_atc.config import load_config, resolve_path  # noqa: E402
from ru_atc.flightplan.cdu import Screen, page_kind  # noqa: E402
from ru_atc.flightplan.fms_file import fms_dir, fms_dir_missing_message, list_fms, load_fms  # noqa: E402
from ru_atc.flightplan.provider import FlightPlanProvider  # noqa: E402


def show_plan(fp, indent="  "):
    print(f"{indent}Сводка: {fp.summary()}")
    for k, v in fp.to_dict().items():
        if k in ("sources",):
            continue
        if k == "waypoints":
            v = " ".join(v) if v else "-"
        src = fp.sources.get(k, "")
        print(f"{indent}{k:<11} {v!s:<40} {('← ' + src) if src else ''}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--xplane", help="папка X-Plane 12 (для Output/FMS plans)")
    ap.add_argument("--side", type=int, choices=[1, 2], help="CDU: 1 — КВС, 2 — второй пилот")
    ap.add_argument("--watch", type=float, default=0, help="секунд следить за экраном CDU (листайте RTE/DEP/ARR/PERF INIT)")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    cfg["sim"]["source"] = "webapi"
    if a.host:
        cfg["sim"]["host"] = a.host
    if a.port:
        cfg["sim"]["webapi_port"] = a.port
    if a.xplane:
        cfg["flight_plan_import"]["xplane_path"] = a.xplane
    if a.side:
        cfg["flight_plan_import"]["fmc_side"] = a.side
    cfg["flight_plan_import"]["source"] = "auto"

    buf = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            buf.write(s)
            return len(s)

    with redirect_stdout(Tee()):
        run(cfg, a.watch)
    out = resolve_path(cfg.get("log_dir", "logs"))
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"fmcdump_{datetime.now():%Y%m%d_%H%M%S}.txt"
    f.write_text(buf.getvalue(), encoding="utf-8")
    print(f"\nОтчёт сохранён: {f}")


def run(cfg, watch: float):
    print(f"=== fmcdump {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    p = FlightPlanProvider(cfg)
    r = p.rest
    print(f"\n[1] Web API {r.host}:{r.port}")
    if not p.connect():
        print("  НЕ ПОДКЛЮЧЕНО:", "; ".join(p.errors[-3:]))
    else:
        print(f"  версия API: {r.ver}; строк CDU найдено: {len(p.cdu_names)}; datarefs FMS Zibo: {len(p.zibo_names)}")
        missing = [n.split('/')[-1] for n in __import__('ru_atc.flightplan.cdu', fromlist=['x']).cdu_dataref_names(p.side)
                   if n not in p.cdu_names]
        if missing:
            print(f"  (нет слоёв: {', '.join(missing[:20])}{' …' if len(missing) > 20 else ''})")
        try:
            sc = p.read_cdu()
            # для диагностики читаем все строки, даже если страница «неинтересная»
            for n in p.cdu_names:
                if n not in p.cdu_values:
                    p.cdu_values[n] = r.value(n)
            sc = Screen.from_values(p.cdu_values, p.side)
            print(f"  Текущий экран CDU (тип страницы: {page_kind(sc.title) or 'не используется'}):")
            print("  +" + "-" * 26 + "+")
            for line in sc.text().split("\n"):
                print("  |" + line[:26].ljust(26) + "|")
            print("  +" + "-" * 26 + "+")
            print("  Сырые строки:")
            for n in p.cdu_names:
                v = p.cdu_values.get(n, "")
                if v.strip():
                    print(f"    {n.split('/')[-1]:<14} {v!r}")
        except Exception as e:
            print(f"  ошибка чтения CDU: {e}")
        print(f"\n[2] datarefs laminar/B738/fms/* (похожие на план), значения:")
        p.read_zibo()
        for n in p.zibo_names:
            v = p.zibo_values.get(n)
            if isinstance(v, list) and len(v) > 12:
                v = f"{v[:12]} … (всего {len(v)})"
            print(f"    {n:<48} [{r.info.get(n, ('', '?'))[1]}] {v!r}")
        if watch > 0:
            print(f"\n  Слежу {watch:.0f} с — пролистайте на CDU: RTE (все страницы), DEP/ARR, PERF INIT, LEGS…")
            t_end = time.time() + watch
            last = ""
            while time.time() < t_end:
                try:
                    sc = p.read_cdu()
                    if sc and sc.title != last:
                        last = sc.title
                        print(f"    экран: {sc.title.strip()!r} -> {page_kind(sc.title) or '-'}")
                    if sc:
                        p.collector.feed(sc)
                except Exception as e:
                    print(f"    ошибка: {e}")
                time.sleep(0.7)
        else:
            sc2 = Screen.from_values(p.cdu_values, p.side)
            p.collector.feed(sc2)
        print("\n  Собрано с экрана CDU:")
        show_plan(p.collector.plan(), "    ")

    print(f"\n[3] Файлы .fms")
    xp = cfg["flight_plan_import"].get("xplane_path") or ""
    d = fms_dir(xp)
    if d is None:
        print("  " + fms_dir_missing_message(xp))
    else:
        print(f"  {d}")
        files = list_fms(d, 5)
        if not files:
            print("  .fms файлов нет (сохраните маршрут в FMC: RTE -> имя в блокнот -> SAVE ROUTE)")
        for f, mt in files:
            print(f"  - {f.name}  ({datetime.fromtimestamp(mt):%Y-%m-%d %H:%M})")
        if files:
            try:
                print(f"  Разбор самого свежего ({files[0][0].name}):")
                show_plan(load_fms(files[0][0]), "    ")
            except Exception as e:
                print(f"    ошибка разбора: {e}")

    print("\n[4] Итоговый план (как его увидит диспетчер):")
    p.poll_once()
    if p.fms_path:
        print(f"  использован файл: {p.fms_path.name}")
    show_plan(p.plan)
    if p.plan.is_empty():
        print("  План пуст — диспетчер будет работать по flight_plan из config.yaml.")


if __name__ == "__main__":
    main()
