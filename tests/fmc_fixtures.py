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
