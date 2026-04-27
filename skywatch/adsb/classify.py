"""Aircraft classification (military / helicopter / mil-helo). Mirrors classify.go."""
from __future__ import annotations


# Military ICAO hex ranges (inclusive).
_MIL_RANGES: list[tuple[int, int]] = [
    (int("ADF7C8", 16), int("AFF7C7", 16)),  # US
    (int("43C000", 16), int("43CFFF", 16)),  # UK
    (int("3F0000", 16), int("3FFFFF", 16)),  # Germany
]

_MIL_TYPECODES = {
    "F16", "F18", "F22", "F35", "F15", "F14", "C130", "C17", "C5", "C5M",
    "KC10", "KC46", "KC35", "B1", "B2", "B52", "B1B", "B2A", "V22",
    "E3", "E6", "E8", "P3", "P8", "P8A", "A10", "A10C", "T38", "T6", "T45",
    "U2", "U2S", "RQ4", "MQ9", "MQ1",
}

_MIL_KEYWORDS = [
    "AIR FORCE", "NAVY", "ARMY", "MARINE", "MILITARY",
    "USAF", "USN", "USCG", "COAST GUARD", "NATL GUARD", "NATIONAL GUARD",
    "DEPT OF DEFENSE", "DEPARTMENT OF DEFENSE", "DOD",
    "RAF", "ROYAL AIR FORCE", "LUFTWAFFE",
]

_HELO_TYPECODES = {
    "B06", "B06T", "B204", "B205", "B206", "B212", "B214", "B222", "B230",
    "B407", "B412", "B427", "B429", "B430", "B505",
    "EC20", "EC25", "EC30", "EC35", "EC45", "EC55", "EC75",
    "AS32", "AS50", "AS55", "AS65", "SA34", "SA36",
    "H125", "H130", "H135", "H145", "H155", "H160", "H175", "H215", "H225",
    "S61", "S70", "S76", "S92", "S300",
    "R22", "R44", "R66",
    "A109", "A119", "A139", "A149", "A169",
    "AW09", "H500", "EXPL", "MD52", "MD60", "MD90",
    "CH47", "AH64", "V22", "UH60", "MH60", "SH60", "HH60",
    "CH53", "MH53", "UH1", "AH1", "OH58", "EN28", "EN48",
    "S269", "S333", "BK17", "K32", "KA32",
    "MI8", "MI17", "MI24", "MI26", "MI28",
    "LYNX", "PUMA", "GLZL",
}


def classify(icao_hex: str, typecode: str, operator: str, owner: str, type_name: str) -> str:
    """Return one of: 'mil-helo', 'military', 'helicopter', or '' (unknown)."""
    is_mil = False
    is_helo = False

    try:
        n = int(icao_hex.strip(), 16)
        for lo, hi in _MIL_RANGES:
            if lo <= n <= hi:
                is_mil = True
                break
    except (ValueError, AttributeError):
        pass

    tc = (typecode or "").strip().upper()
    if tc in _MIL_TYPECODES:
        is_mil = True
    if tc in _HELO_TYPECODES:
        is_helo = True

    blob = " ".join(s.upper() for s in (operator or "", owner or "", type_name or ""))
    for kw in _MIL_KEYWORDS:
        if kw in blob:
            is_mil = True
            break

    if is_mil and is_helo:
        return "mil-helo"
    if is_mil:
        return "military"
    if is_helo:
        return "helicopter"
    return ""
