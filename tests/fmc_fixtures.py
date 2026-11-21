"""Поддельные экраны CDU Zibo и файлы .fms для тестов (раскладка Boeing 737, 24 символа)."""
import base64

W = 24


def ln(left="", right=""):
    return (left + " " * (W - len(left) - len(right)) + right)[:W]


SIDE = 1
PFX = f"laminar/B738/fmc{SIDE}/"


def screen_values(title, rows, scratch=""):
    """rows: список (label_row, data_row) крупным шрифтом; возвращает {dataref: str}."""
    v = {PFX + "Line00_L": title}
    for i, (lab, dat) in enumerate(rows, start=1):
        v[PFX + f"Line{i:02d}_X"] = lab
        v[PFX + f"Line{i:02d}_L"] = dat
    v[PFX + "Line_entry"] = scratch
    return v


RTE1 = screen_values(ln("      ACT RTE 1", "1/3"), [
    (ln(" ORIGIN", "DEST"), ln("UUEE", "ULLI")),
    (ln(" RUNWAY", "FLT NO."), ln("RW24C", "AFL1234")),
    (ln(" CO ROUTE", ""), ln("UUEEULLI01", "")),
])
RTE2 = screen_values(ln("      ACT RTE 1", "2/3"), [
    (ln(" VIA", "TO"), ln("LAKI1G", "LAKIB")),
    (ln("", ""), ln("R22", "TOPLA")),
    (ln("", ""), ln("DIRECT", "SOGMA")),
])
RTE3 = screen_values(ln("      ACT RTE 1", "3/3"), [
    (ln("", ""), ln("DIRECT", "BEMAN")),
    (ln("", ""), ln("BEMA2E", "RIMET")),
    (ln("", ""), ln("-----", "-----")),
])
DEP = screen_values(ln(" UUEE DEPARTURES", "1/2"), [
    (ln(" SIDS", "RUNWAYS"), ln("LAKI1G <ACT>", "<ACT> RW24C")),
    (ln(" TRANS", ""), ln("LAKIB  <ACT>", "")),
])
ARR = screen_values(ln("  ULLI ARRIVALS", "1/1"), [
    (ln(" STARS", "APPROACHES"), ln("BEMA2E <SEL>", "<SEL> ILS28R")),
    (ln(" TRANS", "TRANS"), ln("RIMET  <SEL>", "<SEL>  SOVIN")),
])
PERF = screen_values(ln("     ACT PERF INIT", ""), [
    (ln(" GW/CRZ CG", "TRIP/CRZ ALT"), ln("142.5/ 25.0%", "--- /FL350")),
])
OTHER = screen_values(ln("        IDENT", "1/2"), [(ln(" MODEL", "ENG RATING"), ln("737-800W", "26K"))])

FMS_1100 = """I
1100 Version
CYCLE 2410
ADEP UUEE
DEPRWY RW24C
SID LAKI1G
SIDTRANS LAKIB
ADES ULLI
DESRWY RW28R
STAR BEMA2E
STARTRANS RIMET
APP I28R
NUMENR 6
1 UUEE ADEP 622.000000 55.972800 37.414600
11 LAKIB DRCT 35000.000000 56.400000 36.800000
11 TOPLA R22 35000.000000 57.200000 35.000000
11 SOGMA DRCT 35000.000000 58.300000 33.000000
11 BEMAN DRCT 35000.000000 59.300000 31.200000
1 ULLI ADES 78.000000 59.800300 30.262500
"""

FMS_V3 = """I
3 version
1
4
1 UUDD 588.000000 55.408800 37.906300
11 AKERA 0.000000 56.000000 37.000000
3 MR 0.000000 57.000000 36.000000
1 UUWW 685.000000 55.591500 37.261500
"""

FMS_UNKNOWN_DEST = """I
1100 Version
CYCLE 2410
ADEP UUEE
DEPRWY RW06R
ADES UUMO
DESRWY RW08
NUMENR 3
1 UUEE ADEP 622.000000 55.972800 37.414600
11 XAXAX DRCT 9000.000000 55.900000 37.000000
1 UUMO ADES 590.000000 55.509400 37.507200
"""


def b64(s):
    return base64.b64encode(s.encode("latin-1")).decode()


# --- реальный дамп fmcdump 2026-11-22, рейс UUEE RWY 24C → ULLI RWY 28L, FL330 ---

UUEE_ULLI_LEGS = (
    "UUEE RW24C KUSIP DUFAR EE242 BEGEZ TOKNU UNASI INBAP GENPA LI753 LI754 "
    "LI749 LI750 LI751 LI752 OBARI BIPRI FF28L RW28L (INTC) D268J (INTC) D245S D245S ULLI "
)
UUEE_ULLI_PTH = "TFTFDFTFTFTFTFTFTFIFTFTFTFTFTFTFTFIFCFCFCICFCICFHMTF"
UUEE_ULLI_LATS = [55.970165, 55.972256, 55.9098, 55.99389, 56.08603, 56.220276, 56.361668,
                  57.7, 58.970554, 59.10611, 59.263695, 59.516945]
UUEE_ULLI_LONS = [37.407833, 37.403404, 37.00689, 36.9025, 36.847473, 36.622776, 36.383335,
                  34.13778, 31.608612, 31.811945, 31.512638, 31.022472]
# Маршрут без аэропортов, ВПП, FF28L, (INTC) и ухода на второй круг после RW28L.
UUEE_ULLI_ENROUTE = [
    "KUSIP", "DUFAR", "EE242", "BEGEZ", "TOKNU", "UNASI", "INBAP", "GENPA",
    "LI753", "LI754", "LI749", "LI750", "LI751", "LI752", "OBARI", "BIPRI",
]

ZIBO_UUEE_ULLI = {
    "laminar/B738/fms/legs": UUEE_ULLI_LEGS,
    "laminar/B738/fms/legs_lat": UUEE_ULLI_LATS,
    "laminar/B738/fms/legs_lon": UUEE_ULLI_LONS,
    "laminar/B738/fms/num_of_wpts": 26.0,
    "laminar/B738/fms/legs_pth": UUEE_ULLI_PTH,
    "laminar/B738/fms/ref_icao": "UUEE",
    "laminar/B738/fms/ref_runway": "24C",
    "laminar/B738/fms/dest_icao": "ULLI",
    "laminar/B738/fms/dest_runway": "28L",
    "laminar/B738/fms/des_list_rwy": "10L10R28L28R",
    "laminar/B738/fms/ref_list_rwy": "06C06L06R24C24L24R",
    "laminar/B738/fms/flight09": "UUEE - ULLI",
    "laminar/B738/fms/flight09b": "TO KUSIP  1100FT",
    "laminar/B738/FMS/dist_dest": 356.9414219856262,
    "laminar/B738/FMS/fpln_dist": 396.603533744812,
    "laminar/B738/FMS/fpln_dist2": 356.5618968009949,
    "laminar/B738/FMS/fmc_gw_app": 117.0,
    "laminar/B738/FMS/approach_flaps": 0.0,
    "laminar/B738/FMS/approach_speed": 0.0,
    "laminar/B738/FMS/approach_wind_corr": 5.0,
    "laminar/B738/FMS/time_dest": "0953",
    "laminar/B738/fms/des_icao_alt": 79.0,
}

# Экран ACT PERF INIT 1/2 как в дампе: слои L/S/X, ZFW разрезан между L и S, ` = градус.
PERF_REAL = {
    PFX + "Line00_L": "  ACT PERF INIT         ",
    PFX + "Line00_S": "                    1/2 ",
    PFX + "Line01_L": " 53.1/ 8.0%  FL410/FL330",
    PFX + "Line01_X": " GW/CRZ CG  TRIP/CRZ ALT",
    PFX + "Line02_L": " 10.0/14.4      ---`/---",
    PFX + "Line02_X": " PLAN/FUEL      CRZ WIND",
    PFX + "Line03_L": "            ----   ---",
    PFX + "Line03_S": " 43.1           `F    `C",
    PFX + "Line03_X": " ZFW             T/C OAT",
    PFX + "Line04_L": " 4.0                3936",
    PFX + "Line04_X": " RESERVES      TRANS ALT",
    PFX + "Line05_L": " 15             REQUEST>",
    PFX + "Line05_X": " COST INDEX    PERF INIT",
    PFX + "Line06_L": "<INDEX         N1 LIMIT>",
    PFX + "Line06_X": "------------------------",
}

# Список SID без <SEL>/<ACT> у схемы; <ACT> только у ВПП справа — так дамп брал чужой SID.
DEP_LIST = screen_values(ln(" UUEE DEPARTURES", "1/10"), [
    (ln(" SIDS", "RUNWAYS"), ln("EMGA3H", "<ACT> RW24C")),
    (ln("", ""), ln("TOKN3H", "06L")),
    (ln("", ""), ln("BEST2B", "06C")),
])

# Обрывки страницы RTE, похожие на то, что собрал старый разбор (дубли, ВПП, уход).
RTE_DUMP_P1 = screen_values(ln("      ACT RTE 1", "1/3"), [
    (ln(" ORIGIN", "DEST"), ln("UUEE", "ULLI")),
    (ln(" RUNWAY", "FLT NO."), ln("RW24C", "")),
])
RTE_DUMP_P2 = screen_values(ln("      ACT RTE 1", "2/3"), [
    (ln(" VIA", "TO"), ln("EMGA3H", "TOKNU")),
    (ln("", ""), ln("DIRECT", "UNASI")),
    (ln("", ""), ln("DIRECT", "INBAP")),
    (ln("", ""), ln("DIRECT", "GENPA")),
    (ln("", ""), ln("DIRECT", "OBARI")),
])
RTE_DUMP_P3 = screen_values(ln("      ACT RTE 1", "3/3"), [
    (ln("", ""), ln("DIRECT", "TOKNU")),
    (ln("", ""), ln("DIRECT", "D245S")),
    (ln("", ""), ln("DIRECT", "RW28L")),
    (ln("", ""), ln("DIRECT", "D245S")),
])
