from ru_atc.model import SimState
from ru_atc.phases import Phase, PhaseTracker


def st(t, **kw):
    s = SimState(t=t, connected=True)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def run(tr, seq):
    for s in seq:
        tr.update(s)
    return tr.phase


def test_ground_sequence():
    tr = PhaseTracker(dep_runway_hdg=lambda: 244.0)
    tr.update(st(0))
    assert tr.phase == Phase.PARKED
    tr.pushback_cleared = True
    tr.update(st(1, gs_kt=2, parking_brake=0))
    assert tr.phase == Phase.PUSHBACK
    for t in range(2, 10):
        tr.update(st(t, gs_kt=0, parking_brake=0, n2=[60, 60]))
    assert tr.phase == Phase.STARTUP
    tr.update(st(11, gs_kt=12, parking_brake=0, n2=[60, 60], hdg_mag=100))
    assert tr.phase == Phase.TAXI_OUT
    tr.lineup_cleared = True
    tr.update(st(12, gs_kt=5, n2=[60, 60], hdg_mag=243))
    assert tr.phase == Phase.LINEUP
    tr.update(st(13, gs_kt=60, n2=[90, 90], hdg_mag=244))
    assert tr.phase == Phase.TAKEOFF
    tr.update(st(14, gs_kt=150, on_ground=False, agl_ft=100, vs_fpm=2000, n2=[90, 90]))
    assert tr.phase == Phase.CLIMB


def test_rejected_takeoff():
    tr = PhaseTracker()
    tr.update(st(0, n2=[60, 60], gs_kt=10))
    assert tr.phase == Phase.TAXI_OUT
    tr.update(st(1, n2=[90, 90], gs_kt=60))
    tr.update(st(2, n2=[90, 90], gs_kt=80))
    tr.update(st(3, n2=[60, 60], gs_kt=20))
    assert tr.phase == Phase.TAXI_OUT


def test_air_sequence_and_go_around():
    tr = PhaseTracker(dist_to_arrival_km=lambda s: 30.0 if s.t > 100 else 300.0,
                      cruise_ft=lambda: 33000, field_elev_ft=lambda: 0)
    tr.update(st(0, on_ground=False, vs_fpm=2000, alt_ind_ft=20000, n2=[90, 90]))
    assert tr.phase == Phase.CLIMB
    run(tr, [st(t, on_ground=False, vs_fpm=0, alt_ind_ft=33000, n2=[90, 90]) for t in range(1, 40)])
    assert tr.phase == Phase.CRUISE
    run(tr, [st(t, on_ground=False, vs_fpm=-2000, alt_ind_ft=30000, n2=[90, 90]) for t in range(40, 70)])
    assert tr.phase == Phase.DESCENT
    tr.update(st(101, on_ground=False, vs_fpm=-800, alt_ind_ft=3000, agl_ft=3000, n2=[90, 90]))
    assert tr.phase == Phase.APPROACH
    run(tr, [st(t, on_ground=False, vs_fpm=2000, alt_ind_ft=1500, agl_ft=900, n2=[90, 90]) for t in range(102, 110)])
    assert tr.phase == Phase.CLIMB and tr.go_around


def test_landing_and_arrival():
    tr = PhaseTracker(dist_to_arrival_km=lambda s: 10.0, field_elev_ft=lambda: 0)
    tr.update(st(0, on_ground=False, vs_fpm=-700, alt_ind_ft=2000, agl_ft=2000, n2=[60, 60]))
    tr.update(st(1, on_ground=False, vs_fpm=-700, alt_ind_ft=2000, agl_ft=2000, n2=[60, 60]))
    assert tr.phase == Phase.APPROACH
    tr.update(st(2, on_ground=True, gs_kt=130, n2=[60, 60]))
    assert tr.phase == Phase.LANDING
    tr.update(st(3, on_ground=True, gs_kt=30, n2=[60, 60]))
    assert tr.phase == Phase.TAXI_IN
    run(tr, [st(t, on_ground=True, gs_kt=0, parking_brake=1, n2=[60, 60]) for t in range(4, 10)])
    assert tr.phase == Phase.ARRIVED


def test_disconnected_ignored():
    tr = PhaseTracker()
    s = SimState(t=0, connected=False, on_ground=False, vs_fpm=3000)
    tr.update(s)
    assert tr.phase == Phase.PARKED
