"""APRS position / message parser. Mirrors internal/aprs/parser.go.

Supports the most common Data Type Identifiers:
  !, =, /, @  — uncompressed and compressed position reports
  ;, )         — object / item
  :            — message
  >            — status
Mic-E (`/'`) is not decoded for position; the raw text is preserved on the
station record under .comment. This matches the Go implementation's TODO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedPacket:
    src_call: str = ""
    dst_call: str = ""
    digi_path: list[str] = field(default_factory=list)
    raw: str = ""
    info: str = ""
    data_type: str = ""
    lat: float = 0.0
    lon: float = 0.0
    has_position: bool = False
    symbol_table: str = ""
    symbol_code: str = ""
    course: int = 0
    speed: float = 0.0
    altitude: int = 0
    comment: str = ""
    msg_dest: str = ""
    msg_text: str = ""
    msg_id: str = ""


_TNC2_RE = re.compile(r"^([A-Z0-9\-]+)>([A-Z0-9\-]+)((?:,[A-Z0-9\-\*]+)*):(.+)$", re.IGNORECASE)


def _decode_lat(raw: str) -> Optional[float]:
    # DDMM.SS{N|S}
    if len(raw) < 8:
        return None
    try:
        deg = int(raw[0:2])
        minutes = float(raw[2:7])
    except ValueError:
        return None
    h = raw[7].upper()
    val = deg + minutes / 60.0
    if h == "S":
        val = -val
    elif h != "N":
        return None
    return val


def _decode_lon(raw: str) -> Optional[float]:
    # DDDMM.SS{E|W}
    if len(raw) < 9:
        return None
    try:
        deg = int(raw[0:3])
        minutes = float(raw[3:8])
    except ValueError:
        return None
    h = raw[8].upper()
    val = deg + minutes / 60.0
    if h == "W":
        val = -val
    elif h != "E":
        return None
    return val


def _base91(s: str) -> int:
    val = 0
    for c in s:
        if not (33 <= ord(c) <= 124):
            return 0
        val = val * 91 + (ord(c) - 33)
    return val


def _parse_compressed(body: str) -> tuple[Optional[float], Optional[float], str, str, str]:
    """Returns (lat, lon, sym_table, sym_code, remainder)."""
    if len(body) < 13:
        return None, None, "", "", body
    sym_table = body[0]
    lat_raw = body[1:5]
    lon_raw = body[5:9]
    sym_code = body[9]
    # Compressed course/speed in bytes 10–12 (cs + type) — accepted but not parsed deeply here.
    rest = body[13:]
    lat = 90.0 - _base91(lat_raw) / 380926.0
    lon = -180.0 + _base91(lon_raw) / 190463.0
    return lat, lon, sym_table, sym_code, rest


_CSE_SPD_RE = re.compile(r"^(\d{3})/(\d{3})")
_ALT_RE = re.compile(r"/A=(-?\d{6})")


def _parse_uncompressed(body: str) -> tuple[Optional[float], Optional[float], str, str, str]:
    if len(body) < 19:
        return None, None, "", "", body
    lat = _decode_lat(body[0:8])
    sym_table = body[8]
    lon = _decode_lon(body[9:18])
    sym_code = body[18]
    return lat, lon, sym_table, sym_code, body[19:]


def parse_aprs_packet(raw: str) -> Optional[ParsedPacket]:
    raw = raw.strip()
    m = _TNC2_RE.match(raw)
    if not m:
        return None
    src_call, dst_call, path_csv, info = m.group(1), m.group(2), m.group(3), m.group(4)
    p = ParsedPacket(
        src_call=src_call.upper(), dst_call=dst_call.upper(),
        digi_path=[s for s in path_csv.lstrip(",").split(",") if s],
        raw=raw, info=info,
    )
    if not info:
        return p
    dti = info[0]
    p.data_type = dti
    body = info[1:]

    if dti in ("!", "="):
        # Optional position with no timestamp.
        first = body[0] if body else ""
        if first == "/" or first == "\\":
            lat, lon, st, sc, rest = _parse_compressed(body)
        else:
            lat, lon, st, sc, rest = _parse_uncompressed(body)
        _maybe_apply_position(p, lat, lon, st, sc, rest)
    elif dti in ("/", "@"):
        # 7-byte timestamp then position
        if len(body) < 7:
            p.comment = body
            return p
        rest = body[7:]
        first = rest[0] if rest else ""
        if first == "/" or first == "\\":
            lat, lon, st, sc, rest2 = _parse_compressed(rest)
        else:
            lat, lon, st, sc, rest2 = _parse_uncompressed(rest)
        _maybe_apply_position(p, lat, lon, st, sc, rest2)
    elif dti == ";":
        # Object: 9-char name + * or _ + 7-char timestamp + position
        if len(body) < 18:
            p.comment = body
            return p
        rest = body[17:]
        first = rest[0] if rest else ""
        if first == "/" or first == "\\":
            lat, lon, st, sc, rest2 = _parse_compressed(rest)
        else:
            lat, lon, st, sc, rest2 = _parse_uncompressed(rest)
        _maybe_apply_position(p, lat, lon, st, sc, rest2)
    elif dti == ")":
        # Item: name until ! or _
        idx = -1
        for term in ("!", "_"):
            i = body.find(term)
            if i > 0:
                idx = i
                break
        if idx < 0:
            p.comment = body
            return p
        rest = body[idx + 1:]
        first = rest[0] if rest else ""
        if first == "/" or first == "\\":
            lat, lon, st, sc, rest2 = _parse_compressed(rest)
        else:
            lat, lon, st, sc, rest2 = _parse_uncompressed(rest)
        _maybe_apply_position(p, lat, lon, st, sc, rest2)
    elif dti == ":":
        # Message: dest padded to 9 chars + ":" + text + optional "{id"
        if len(body) < 10 or body[9] != ":":
            p.comment = body
            return p
        p.msg_dest = body[:9].strip()
        msg = body[10:]
        if "{" in msg:
            head, _, tail = msg.partition("{")
            p.msg_text = head
            p.msg_id = tail
        else:
            p.msg_text = msg
    elif dti == ">":
        p.comment = body
    else:
        # Mic-E or unsupported — keep raw text as comment
        p.comment = body
    return p


def _maybe_apply_position(p: ParsedPacket, lat, lon, sym_table, sym_code, rest):
    if lat is None or lon is None:
        p.comment = rest
        return
    p.lat = lat
    p.lon = lon
    p.has_position = True
    p.symbol_table = sym_table
    p.symbol_code = sym_code
    if rest:
        m = _CSE_SPD_RE.match(rest)
        if m:
            p.course = int(m.group(1))
            p.speed = float(m.group(2))
            rest = rest[7:]
        a = _ALT_RE.search(rest)
        if a:
            try:
                p.altitude = int(a.group(1))
            except ValueError:
                pass
            rest = (rest[:a.start()] + rest[a.end():]).strip()
        p.comment = rest
