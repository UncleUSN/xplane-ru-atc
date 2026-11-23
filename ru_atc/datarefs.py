"""Список datarefs, на которые подписывается программа.

verified:
  "xp12"    — найден в официальном DataRefs.txt X-Plane 12 (XPlane2Blender, версия файла Aug 2023)
  "zibo-pub"— Zibo, из публичных источников (B738_Datarefs.txt rel.2.35, форум x-plane.org,
               скрипты FlyWithLua). Имя может измениться в новых версиях Zibo.
  "unverified" — не подтверждено, используйте осторожно.
Zibo-datarefs необязательны: если X-Plane их не знает, программа их пропускает.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DatarefSpec:
    key: str                  # поле SimState (или служебный ключ)
    name: str                 # имя dataref
    index: Optional[int] = None
    verified: str = "xp12"
    optional: bool = False


CORE = [
    DatarefSpec("lat", "sim/flightmodel/position/latitude"),
    DatarefSpec("lon", "sim/flightmodel/position/longitude"),
    DatarefSpec("elev_m", "sim/flightmodel/position/elevation"),
    DatarefSpec("alt_ind_ft", "sim/cockpit2/gauges/indicators/altitude_ft_pilot"),
    DatarefSpec("agl_m", "sim/flightmodel/position/y_agl"),
    DatarefSpec("ias_kt", "sim/flightmodel/position/indicated_airspeed"),
    DatarefSpec("gs_ms", "sim/flightmodel/position/groundspeed"),
    DatarefSpec("vs_fpm", "sim/flightmodel/position/vh_ind_fpm"),
    DatarefSpec("hdg_mag", "sim/flightmodel/position/mag_psi"),
    DatarefSpec("on_ground", "sim/flightmodel/failures/onground_any"),
    DatarefSpec("parking_brake", "sim/flightmodel/controls/parkbrake"),
    DatarefSpec("gear_down", "sim/cockpit2/controls/gear_handle_down"),
    DatarefSpec("flaps", "sim/cockpit2/controls/flap_handle_deploy_ratio"),
    DatarefSpec("xpdr_code", "sim/cockpit2/radios/actuators/transponder_code"),
    DatarefSpec("xpdr_mode", "sim/cockpit2/radios/actuators/transponder_mode"),
    DatarefSpec("com1_raw", "sim/cockpit2/radios/actuators/com1_frequency_hz_833"),
    DatarefSpec("com1_stby_raw", "sim/cockpit2/radios/actuators/com1_standby_frequency_hz_833"),
    DatarefSpec("beacon", "sim/cockpit2/switches/beacon_on"),
    DatarefSpec("strobe", "sim/cockpit2/switches/strobe_lights_on"),
    DatarefSpec("landing_lights", "sim/cockpit2/switches/landing_lights_on"),
    DatarefSpec("taxi_light", "sim/cockpit2/switches/taxi_light_on"),
    DatarefSpec("nav_lights", "sim/cockpit2/switches/navigation_lights_on"),
    DatarefSpec("n1_0", "sim/cockpit2/engine/indicators/N1_percent", 0),
    DatarefSpec("n1_1", "sim/cockpit2/engine/indicators/N1_percent", 1),
    DatarefSpec("n2_0", "sim/cockpit2/engine/indicators/N2_percent", 0),
    DatarefSpec("n2_1", "sim/cockpit2/engine/indicators/N2_percent", 1),
    DatarefSpec("baro_set_inhg", "sim/cockpit2/gauges/actuators/barometer_setting_in_hg_pilot"),
    DatarefSpec("qnh_pas", "sim/weather/aircraft/qnh_pas", optional=True),          # XP12
    DatarefSpec("wind_dir", "sim/weather/aircraft/wind_now_direction_degt", optional=True),
    DatarefSpec("wind_ms", "sim/weather/aircraft/wind_now_speed_msc", optional=True),
    DatarefSpec("mcp_alt_ft", "sim/cockpit2/autopilot/altitude_dial_ft", optional=True),
    # Секунды от местной полуночи. Нет dataref — приветствие берёт часы компьютера.
    DatarefSpec("local_time_sec", "sim/time/local_time_sec", optional=True),
]

ZIBO = [
    # 0 TEST? 1 STBY, 2 ALT RPTG OFF, 3 XPNDR, 4 TA ONLY, 5 TA/RA (1 и 5 подтверждены clist.txt; прочие — предположение)
    DatarefSpec("zibo_xpdr_pos", "laminar/B738/knob/transponder_pos", verified="zibo-pub", optional=True),
    DatarefSpec("zibo_mcp_alt", "laminar/B738/autopilot/mcp_alt_dial", verified="zibo-pub", optional=True),
    DatarefSpec("zibo_baro_inhg", "laminar/B738/EFIS/baro_sel_in_hg_pilot", verified="zibo-pub", optional=True),
    DatarefSpec("zibo_baro_std", "laminar/B738/EFIS/baro_set_std_pilot", verified="zibo-pub", optional=True),
    DatarefSpec("zibo_gear_lever", "laminar/B738/switches/landing_gear", verified="zibo-pub", optional=True),  # 0 up 1 off 2 down
    DatarefSpec("zibo_air_ground", "laminar/B738/air_ground_sensor", verified="zibo-pub", optional=True),     # 1 = на земле
    DatarefSpec("zibo_chocks", "laminar/B738/fms/chock_status", verified="zibo-pub", optional=True),
]


def all_specs(use_zibo: bool = True):
    return CORE + (ZIBO if use_zibo else [])
