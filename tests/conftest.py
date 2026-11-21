import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ru_atc.airspace import Airspace  # noqa: E402
from ru_atc.config import load_config  # noqa: E402
from ru_atc.controller import Controller  # noqa: E402


@pytest.fixture
def cfg():
    c = load_config("/nonexistent/config.yaml")
    return c


@pytest.fixture
def airspace(cfg):
    return Airspace.load(cfg["airports_file"], cfg["airspace_file"])


def make_ctl(cfg, airspace, dep="UUEE", arr="ULLI", **atc):
    cfg["flight_plan"].update(departure=dep, arrival=arr)
    cfg["atc"].update(atc)
    return Controller(cfg, airspace, random.Random(42))
