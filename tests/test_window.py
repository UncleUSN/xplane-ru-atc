"""Поведение окна (always-on-top, компактный режим, показ/скрытие, горячие клавиши) на поддельном Tk."""
from ru_atc.config import DEFAULTS, deep_merge, normalize_user
from ru_atc.window import WindowController, clamp_alpha, parse_geometry, register_hotkeys


class FakeRoot:
    def __init__(self):
        self.attrs = {}
        self.geom = "1100x680+100+50"
        self.st = "normal"
        self.borderless = False
        self.calls = []
        self.after_q = []

    def attributes(self, k, v=None):
        self.calls.append(("attr", k, v))
        self.attrs[k] = v

    def geometry(self, g=None):
        if g is None:
            return self.geom
        self.calls.append(("geom", g))
        self.geom = g

    def overrideredirect(self, v):
        self.borderless = v

    def state(self):
        return self.st

    def withdraw(self):
        self.st = "withdrawn"

    def deiconify(self):
        self.st = "normal"
        self.calls.append(("deiconify",))

    def lift(self):
        self.calls.append(("lift",))

    def focus_force(self):
        self.calls.append(("focus",))

    def after(self, ms, fn):
        self.after_q.append((ms, fn))

    def wm_frame(self):
        return "0x1234"


class FakeWin32:
    def __init__(self, ok=True):
        self.ok = ok
        self.top = []
        self.fg = []

    def foreground(self):
        return 777 if self.ok else 0

    def set_foreground(self, h):
        self.fg.append(h)

    def make_topmost(self, h):
        self.top.append(h)


def ui(**kw):
    return deep_merge(DEFAULTS["ui"], kw)


def test_old_string_ui_config_still_works():
    cfg = deep_merge(DEFAULTS, normalize_user({"ui": "console"}))
    assert cfg["ui"]["mode"] == "console" and cfg["ui"]["hotkey_toggle"] == "ctrl+shift+a"


def test_geometry_and_alpha_helpers():
    assert parse_geometry("560x150-20+40") == (560, 150, "-20", "+40")
    assert parse_geometry("1100x680") == (1100, 680, None, None) and parse_geometry("big") is None
    assert clamp_alpha(0.05) == 0.2 and clamp_alpha("x") == 1.0 and clamp_alpha(0.85) == 0.85


def test_topmost_and_periodic_reassert():
    r, w32 = FakeRoot(), FakeWin32()
    w = WindowController(r, ui(), win32=w32)
    w.apply_initial()
    assert r.attrs["-topmost"] is True and w32.top == [0x1234]
    ms, fn = r.after_q[-1]
    assert ms == 2000
    fn()                                   # таймер: снова поверх, без активации окна
    assert len(w32.top) == 2 and len(r.after_q) == 2 and ("focus",) not in r.calls
    w.hide()
    assert not w.reassert_topmost()        # спрятанное окно не поднимаем
    w.set_topmost(False)
    assert r.attrs["-topmost"] is False


def test_compact_mode_restores_full_geometry():
    r, modes = FakeRoot(), []
    w = WindowController(r, ui(compact_alpha=0.7), on_mode=modes.append, win32=FakeWin32(False))
    w.apply_initial()
    r.geom = "1100x680+100+50"             # пользователь подвинул окно
    w.toggle_compact()
    assert w.compact and modes == [True] and r.borderless and r.geom == "560x180-20+40"
    assert r.attrs["-alpha"] == 0.7 and r.attrs["-topmost"] is True
    w.toggle_compact()
    assert not w.compact and not r.borderless and r.geom == "1100x680+100+50" and r.attrs["-alpha"] == 1.0


def test_start_compact():
    r = FakeRoot()
    w = WindowController(r, ui(start_compact=True), win32=FakeWin32(False))
    w.apply_initial()
    assert w.compact and r.geom == "560x180-20+40"


def test_toggle_visible_returns_focus_to_sim():
    r, w32 = FakeRoot(), FakeWin32()
    w = WindowController(r, ui(), win32=w32)
    w.command("toggle")
    assert r.st == "withdrawn" and w.hidden
    r.st = "iconic"                        # свернули — тоже «не видно»
    w.hidden = False
    w.command("toggle")
    assert r.st == "normal" and ("lift",) in r.calls and ("focus",) not in r.calls
    r.after_q[-1][1]()                     # вернуть фокус X-Plane
    assert w32.fg == [777]


def test_show_with_focus_option():
    r = FakeRoot()
    w = WindowController(r, ui(focus_on_show=True), win32=FakeWin32())
    w.hide()
    w.show()
    assert ("focus",) in r.calls


class FakeKb:
    def __init__(self, bad=()):
        self.reg = {}
        self.bad = bad

    def add_hotkey(self, key, fn, suppress=False):
        if key in self.bad:
            raise ValueError("unknown key")
        self.reg[key] = fn


def test_hotkeys_post_commands():
    kb, posted = FakeKb(), []
    errs = register_hotkeys(ui(), posted.append, kb=kb)
    assert errs == [] and set(kb.reg) == {"ctrl+shift+a", "ctrl+shift+z"}
    kb.reg["ctrl+shift+a"]()
    kb.reg["ctrl+shift+z"]()
    assert posted == ["toggle", "compact"]
    errs = register_hotkeys(ui(hotkey_toggle="hyper+q", hotkey_compact=""), posted.append, kb=FakeKb(bad=("hyper+q",)))
    assert len(errs) == 1 and "hyper+q" in errs[0]
