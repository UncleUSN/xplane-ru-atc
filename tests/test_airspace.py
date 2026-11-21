from ru_atc.airspace import haversine_km


def test_samples_present(airspace):
    for icao in ("UUEE", "UUDD", "UUWW", "ULLI"):
        ap = airspace.airports[icao]
        assert ap.unit("tower") and ap.unit("ground") and ap.unit("delivery")
    assert airspace.airports["ULLI"].unit("approach").callsign == "Петербург-Подход"


def test_transition_level_moscow(airspace):
    ap = airspace.airports["UUEE"]
    assert ap.transition_altitude_ft == 10000
    assert ap.transition_level(1020) == 110
    assert ap.transition_level(990) == 120
    assert ap.transition_level(970) == 130


def test_squawk_is_octal_in_range(airspace):
    import random
    ap = airspace.airports["ULLI"]
    rng = random.Random(1)
    for _ in range(200):
        sq = ap.assign_squawk(rng)
        assert all(c in "01234567" for c in sq)
        assert int("0701", 8) <= int(sq, 8) <= int("0777", 8)


def test_runway_selection(airspace):
    ap = airspace.airports["UUEE"]
    assert ap.select_runway(250, 15).id.startswith("24")
    assert ap.select_runway(60, 15).id.startswith("06")
    assert ap.select_runway(60, 2).id == "24C"     # штиль -> предпочтительная
    assert ap.select_runway(0, 0, forced="06R").id == "06R"


def test_sectors(airspace):
    uuee = airspace.airports["UUEE"]
    ulli = airspace.airports["ULLI"]
    assert airspace.sector_at(uuee.lat, uuee.lon).callsign == "Москва-Контроль"
    assert airspace.sector_at(ulli.lat, ulli.lon).callsign == "Санкт-Петербург Контроль"


def test_units_on_shared_freq(airspace):
    # 121.7 — и Внуково-Руление, и Пулково-Руление
    names = {u.callsign for u in airspace.units_on_freq(121700)}
    assert {"Внуково-Руление", "Пулково-Руление"} <= names


def test_distance():
    d = haversine_km(55.9728, 37.4146, 59.8003, 30.2625)
    assert 590 < d < 610
