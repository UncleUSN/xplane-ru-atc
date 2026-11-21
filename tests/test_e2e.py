"""Сквозные тесты: модель полёта + автоматический пилот + диспетчер, без X-Plane."""
import random

import pytest

from ru_atc.controller import Controller
from ru_atc.events import Hint, Transmission
from ru_atc.phases import Phase
from ru_atc.sources.mock import MockFlight, ScriptedPilot


def fly(cfg, airspace, dep, arr, faults=None, max_t=20000):
    cfg["flight_plan"].update(departure=dep, arrival=arr)
    ctl = Controller(cfg, airspace, random.Random(7))
    f = MockFlight(airspace.airports[dep], airspace.airports[arr], ctl, faults=faults or set())
    pilot = ScriptedPilot(ctl, f)
    log = []
    s = None
    for _ in range(max_t):
        s = f.step(1.0)
        evs = ctl.update(s)
        for t in pilot.step(s):
            evs += ctl.on_pilot(t, s)
        log += evs
        if f.done and s.t - f.t_mode > 10:
            break
    return ctl, f, log


def atc_lines(log):
    return [f"[{e.unit.callsign}] {e.display}" for e in log if isinstance(e, Transmission)]


def assert_in_order(lines, needles):
    pos = 0
    for n in needles:
        for i in range(pos, len(lines)):
            if n in lines[i]:
                pos = i
                break
        else:
            raise AssertionError(f"Не найдено по порядку: {n!r}\n" + "\n".join(lines))


def test_uuee_to_ulli_full_flight(cfg, airspace):
    ctl, f, log = fly(cfg, airspace, "UUEE", "ULLI")
    lines = atc_lines(log)
    assert ctl.phase == Phase.ARRIVED
    assert_in_order(lines, [
        "[Шереметьево-Деливери] Аэрофлот 1234, Шереметьево-Деливери, разрешено до Пулково",
        "работайте с Шереметьево-Руление",
        "[Шереметьево-Руление]", "буксировку и запуск разрешаю",
        "рулите к предварительному старту",
        "[Шереметьево-Старт]", "взлёт разрешаю",
        "работайте с Шереметьево-Круг",
        "[Шереметьево-Круг] Аэрофлот 1234, Шереметьево-Круг, наблюдаю, набирайте эшелон 150",
        "работайте с Москва-Контроль",
        "[Москва-Контроль] Аэрофлот 1234, Москва-Контроль, наблюдаю, набирайте эшелон 330",
        "работайте с Санкт-Петербург Контроль",
        "[Санкт-Петербург Контроль] Аэрофлот 1234, Санкт-Петербург Контроль, наблюдаю",
        "снижайтесь до эшелона 100",
        "работайте с Петербург-Подход",
        "[Петербург-Подход]", "ожидайте заход ILS ВПП 28",
        "работайте с Пулково-Круг",
        "[Пулково-Круг]", "разрешаю, доложите на посадочном",
        "работайте с Пулково-Вышка",
        "[Пулково-Вышка]", "посадку разрешаю",
        "работайте с Пулково-Руление",
        "[Пулково-Руление]", "рулите на стоянку",
    ])
    # никаких «неправильно»/повторных запросов в штатном полёте
    assert not [l for l in lines if "неправильно" in l or "подтвердите приём" in l]
    hints = [e.text for e in log if isinstance(e, Hint) and not e.text.startswith("Фаза")]
    assert not [h for h in hints if "Отклонение" in h or "Ответчик" in h], hints


def test_ulli_to_uudd_full_flight(cfg, airspace):
    ctl, f, log = fly(cfg, airspace, "ULLI", "UUDD")
    lines = atc_lines(log)
    assert ctl.phase == Phase.ARRIVED
    assert_in_order(lines, [
        "[Пулково-Деливери]", "разрешено до Домодедово", "ответчик 07",
        "[Пулково-Вышка]", "взлёт разрешаю",
        "работайте с Пулково-Круг", "набирайте эшелон 100",
        "работайте с Санкт-Петербург Контроль",
        "работайте с Москва-Контроль",
        "[Москва-Контроль] Аэрофлот 1234, Москва-Контроль, наблюдаю, сохраняйте эшелон 330",
        "снижайтесь до эшелона 150",
        "работайте с Домодедово-Круг",
        "[Домодедово-Круг]", "снижайтесь до высоты 5000",
        "заход ILS ВПП 32", "работайте с Домодедово-Вышка",
        "посадку разрешаю", "работайте с Домодедово-Перрон",
    ])


@pytest.mark.parametrize("dep,arr", [("UUWW", "ULLI"), ("ULLI", "UUEE"), ("UUDD", "ULLI"), ("ULLI", "UUWW")])
def test_other_pairs_complete(cfg, airspace, dep, arr):
    ctl, f, log = fly(cfg, airspace, dep, arr)
    lines = atc_lines(log)
    assert ctl.phase == Phase.ARRIVED, "\n".join(lines)
    assert any("посадку разрешаю" in l for l in lines)
    assert sum("Контроль" in l and "работайте с" in l for l in lines) >= 2


def test_monitor_no_squawk(cfg, airspace):
    ctl, f, log = fly(cfg, airspace, "UUEE", "ULLI", faults={"no_squawk"}, max_t=900)
    lines = atc_lines(log)
    assert any("проверьте код ответчика" in l for l in lines)


def test_monitor_xpdr_standby(cfg, airspace):
    ctl, f, log = fly(cfg, airspace, "UUEE", "ULLI", faults={"no_xpdr"}, max_t=900)
    assert any("ответчик не наблюдаю" in l for l in atc_lines(log))


def test_monitor_altitude_bust(cfg, airspace):
    ctl, f, log = fly(cfg, airspace, "UUEE", "ULLI", faults={"bust", "no_tune_air"}, max_t=900)
    assert any("проверьте высоту" in l and "6000" in l for l in atc_lines(log))


def test_monitor_taxi_without_clearance(cfg, airspace):
    cfg["flight_plan"].update(departure="UUEE", arrival="ULLI")
    ctl = Controller(cfg, airspace, random.Random(1))
    f = MockFlight(airspace.airports["UUEE"], airspace.airports["ULLI"], ctl, faults={"taxi_noclr"})
    log = []
    # пилот получает разрешение и запуск, но не запрашивает руление
    s = f.step(1.0)
    ctl.update(s)
    ctl.on_pilot("прошу разрешение до Пулково", s)
    ctl.on_pilot(f"6000 футов ответчик {ctl.squawk}", s)
    for _ in range(5):
        s = f.step(1.0); ctl.update(s)
    ctl.on_pilot("разрешите буксировку и запуск", s)
    for _ in range(300):
        s = f.step(1.0)
        log += ctl.update(s)
    assert any("руление не разрешено" in l for l in atc_lines(log))


def test_monitor_overspeed_and_baro_hints(cfg, airspace):
    ctl, f, log = fly(cfg, airspace, "UUEE", "ULLI", faults={"overspeed", "no_std"}, max_t=1500)
    hints = [e.text for e in log if isinstance(e, Hint)]
    assert any("Скорость" in h for h in hints)
    assert any("стандартное давление" in h for h in hints)
