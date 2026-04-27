"""AIS lookup tables: ship types, nav status, MMSI → country (MID).

Mirrors internal/ais/lookups.go. Tables are kept verbose on purpose so they
match the Go source 1:1 — AIS reference data is stable and worth duplicating
for offline use.
"""
from __future__ import annotations


# Ship type codes 0-99 (per ITU-R M.1371-5).
SHIP_TYPES: dict[int, str] = {
    0: "Not available", 1: "Reserved", 2: "Reserved", 3: "Reserved",
    4: "High speed craft", 5: "Reserved", 6: "Passenger",
    7: "Cargo", 8: "Tanker", 9: "Other",
    20: "Wing in ground", 21: "Wing in ground (Hazard A)", 22: "Wing in ground (Hazard B)",
    23: "Wing in ground (Hazard C)", 24: "Wing in ground (Hazard D)", 25: "WIG Reserved",
    26: "WIG Reserved", 27: "WIG Reserved", 28: "WIG Reserved", 29: "WIG Reserved",
    30: "Fishing", 31: "Towing", 32: "Towing (large)",
    33: "Dredging or underwater ops", 34: "Diving ops", 35: "Military ops",
    36: "Sailing", 37: "Pleasure craft", 38: "Reserved", 39: "Reserved",
    40: "High speed craft", 41: "HSC (Hazard A)", 42: "HSC (Hazard B)",
    43: "HSC (Hazard C)", 44: "HSC (Hazard D)", 45: "HSC Reserved",
    46: "HSC Reserved", 47: "HSC Reserved", 48: "HSC Reserved", 49: "HSC No info",
    50: "Pilot vessel", 51: "Search and rescue", 52: "Tug", 53: "Port tender",
    54: "Anti-pollution", 55: "Law enforcement", 56: "Spare", 57: "Spare",
    58: "Medical transport", 59: "Special craft",
    60: "Passenger", 61: "Passenger (Hazard A)", 62: "Passenger (Hazard B)",
    63: "Passenger (Hazard C)", 64: "Passenger (Hazard D)", 65: "Passenger Reserved",
    66: "Passenger Reserved", 67: "Passenger Reserved", 68: "Passenger Reserved",
    69: "Passenger No info",
    70: "Cargo", 71: "Cargo (Hazard A)", 72: "Cargo (Hazard B)",
    73: "Cargo (Hazard C)", 74: "Cargo (Hazard D)", 75: "Cargo Reserved",
    76: "Cargo Reserved", 77: "Cargo Reserved", 78: "Cargo Reserved",
    79: "Cargo No info",
    80: "Tanker", 81: "Tanker (Hazard A)", 82: "Tanker (Hazard B)",
    83: "Tanker (Hazard C)", 84: "Tanker (Hazard D)", 85: "Tanker Reserved",
    86: "Tanker Reserved", 87: "Tanker Reserved", 88: "Tanker Reserved",
    89: "Tanker No info",
    90: "Other", 91: "Other (Hazard A)", 92: "Other (Hazard B)",
    93: "Other (Hazard C)", 94: "Other (Hazard D)", 95: "Other Reserved",
    96: "Other Reserved", 97: "Other Reserved", 98: "Other Reserved",
    99: "Other",
}


NAV_STATUS: list[str] = [
    "Under way using engine", "At anchor", "Not under command",
    "Restricted manoeuverability", "Constrained by her draught", "Moored",
    "Aground", "Engaged in fishing", "Under way sailing", "Reserved",
    "Reserved", "Reserved", "Reserved", "Reserved", "AIS-SART", "",  # 15 = undefined → empty
]


# Maritime Identification Digits (MMSI prefix → country). Stable list.
MID_TO_COUNTRY: dict[int, str] = {
    201: "Albania", 202: "Andorra", 203: "Austria", 204: "Azores", 205: "Belgium",
    206: "Belarus", 207: "Bulgaria", 208: "Vatican", 209: "Cyprus", 210: "Cyprus",
    211: "Germany", 212: "Cyprus", 213: "Georgia", 214: "Moldova", 215: "Malta",
    216: "Armenia", 218: "Germany", 219: "Denmark", 220: "Denmark", 224: "Spain",
    225: "Spain", 226: "France", 227: "France", 228: "France", 229: "Malta",
    230: "Finland", 231: "Faroe Islands", 232: "United Kingdom", 233: "United Kingdom",
    234: "United Kingdom", 235: "United Kingdom", 236: "Gibraltar", 237: "Greece",
    238: "Croatia", 239: "Greece", 240: "Greece", 241: "Greece", 242: "Morocco",
    243: "Hungary", 244: "Netherlands", 245: "Netherlands", 246: "Netherlands",
    247: "Italy", 248: "Malta", 249: "Malta", 250: "Ireland", 251: "Iceland",
    252: "Liechtenstein", 253: "Luxembourg", 254: "Monaco", 255: "Madeira",
    256: "Malta", 257: "Norway", 258: "Norway", 259: "Norway", 261: "Poland",
    262: "Montenegro", 263: "Portugal", 264: "Romania", 265: "Sweden",
    266: "Sweden", 267: "Slovakia", 268: "San Marino", 269: "Switzerland",
    270: "Czech Republic", 271: "Turkey", 272: "Ukraine", 273: "Russia",
    274: "North Macedonia", 275: "Latvia", 276: "Estonia", 277: "Lithuania",
    278: "Slovenia", 279: "Serbia",
    301: "Anguilla", 303: "Alaska (USA)", 304: "Antigua and Barbuda",
    305: "Antigua and Barbuda", 306: "Curacao", 307: "Aruba", 308: "Bahamas",
    309: "Bahamas", 310: "Bermuda", 311: "Bahamas", 312: "Belize", 314: "Barbados",
    316: "Canada", 319: "Cayman Islands", 321: "Costa Rica", 323: "Cuba",
    325: "Dominica", 327: "Dominican Republic", 329: "Guadeloupe",
    330: "Grenada", 331: "Greenland", 332: "Guatemala", 334: "Honduras",
    336: "Haiti", 338: "United States", 339: "Jamaica", 341: "Saint Kitts and Nevis",
    343: "Saint Lucia", 345: "Mexico", 347: "Martinique", 348: "Montserrat",
    350: "Nicaragua", 351: "Panama", 352: "Panama", 353: "Panama", 354: "Panama",
    355: "Panama", 356: "Panama", 357: "Panama", 358: "Puerto Rico",
    359: "El Salvador", 361: "Saint Pierre and Miquelon",
    362: "Trinidad and Tobago", 364: "Turks and Caicos", 366: "United States",
    367: "United States", 368: "United States", 369: "United States",
    370: "Panama", 371: "Panama", 372: "Panama", 373: "Panama", 374: "Panama",
    375: "Saint Vincent and the Grenadines", 376: "Saint Vincent",
    377: "Saint Vincent",
    401: "Afghanistan", 403: "Saudi Arabia", 405: "Bangladesh", 408: "Bahrain",
    410: "Bhutan", 412: "China", 413: "China", 414: "China", 416: "Taiwan",
    417: "Sri Lanka", 419: "India", 422: "Iran", 423: "Azerbaijan", 425: "Iraq",
    428: "Israel", 431: "Japan", 432: "Japan", 434: "Turkmenistan",
    436: "Kazakhstan", 437: "Uzbekistan", 438: "Jordan", 440: "South Korea",
    441: "South Korea", 443: "Palestine", 445: "North Korea", 447: "Kuwait",
    450: "Lebanon", 451: "Kyrgyzstan", 453: "Macao", 455: "Maldives",
    457: "Mongolia", 459: "Nepal", 461: "Oman", 463: "Pakistan", 466: "Qatar",
    468: "Syria", 470: "United Arab Emirates", 472: "Tajikistan", 473: "Yemen",
    475: "Yemen", 477: "Hong Kong",
    501: "Adelie Land", 503: "Australia", 506: "Myanmar", 508: "Brunei",
    510: "Micronesia", 511: "Palau", 512: "New Zealand", 514: "Cambodia",
    515: "Cambodia", 516: "Christmas Island", 518: "Cook Islands", 520: "Fiji",
    523: "Cocos Islands", 525: "Indonesia", 529: "Kiribati", 531: "Laos",
    533: "Malaysia", 536: "Northern Mariana Islands", 538: "Marshall Islands",
    540: "New Caledonia", 542: "Niue", 544: "Nauru", 546: "French Polynesia",
    548: "Philippines", 550: "Timor-Leste", 553: "Papua New Guinea",
    555: "Pitcairn Islands", 557: "Solomon Islands", 559: "American Samoa",
    561: "Samoa", 563: "Singapore", 564: "Singapore", 565: "Singapore",
    566: "Singapore", 567: "Thailand", 570: "Tonga", 572: "Tuvalu",
    574: "Vietnam", 576: "Vanuatu", 577: "Vanuatu",
    601: "South Africa", 603: "Angola", 605: "Algeria", 607: "Saint Paul",
    608: "Ascension Island", 609: "Burundi", 610: "Benin", 611: "Botswana",
    612: "Central African Republic", 613: "Cameroon", 615: "Congo",
    616: "Comoros", 617: "Cape Verde", 618: "Crozet Archipelago",
    619: "Ivory Coast", 620: "Comoros", 621: "Djibouti", 622: "Egypt",
    624: "Ethiopia", 625: "Eritrea", 626: "Gabon", 627: "Ghana", 629: "Gambia",
    630: "Guinea-Bissau", 631: "Equatorial Guinea", 632: "Guinea",
    633: "Burkina Faso", 634: "Kenya", 635: "Kerguelen Islands", 636: "Liberia",
    637: "Liberia", 642: "Libya", 644: "Lesotho", 645: "Mauritius", 647: "Madagascar",
    649: "Mali", 650: "Mozambique", 654: "Mauritania", 655: "Malawi", 656: "Niger",
    657: "Nigeria", 659: "Namibia", 660: "Reunion", 661: "Rwanda", 662: "Sudan",
    663: "Senegal", 664: "Seychelles", 665: "Saint Helena", 666: "Somalia",
    667: "Sierra Leone", 668: "Sao Tome and Principe", 669: "Eswatini",
    670: "Chad", 671: "Togo", 672: "Tunisia", 674: "Tanzania", 675: "Uganda",
    676: "Democratic Republic of the Congo", 677: "Tanzania",
    701: "Argentina", 710: "Brazil", 720: "Bolivia", 725: "Chile", 730: "Colombia",
    735: "Ecuador", 740: "Falkland Islands", 745: "Guiana", 750: "Guyana",
    755: "Paraguay", 760: "Peru", 765: "Suriname", 770: "Uruguay", 775: "Venezuela",
}


def ship_type_str(code: int) -> str:
    return SHIP_TYPES.get(int(code), "")


def nav_status_str(code: int) -> str:
    if 0 <= int(code) < len(NAV_STATUS):
        return NAV_STATUS[int(code)]
    return ""


def country_for_mmsi(mmsi: int | str) -> str:
    try:
        m = int(mmsi)
    except (TypeError, ValueError):
        return ""
    return MID_TO_COUNTRY.get(m // 1_000_000, "")


def format_mmsi(mmsi: int | str) -> str:
    try:
        return f"{int(mmsi):09d}"
    except (TypeError, ValueError):
        return ""


def format_eta(month: int, day: int, hour: int, minute: int) -> str:
    """ETA from AIS fields → human string ('Jan 15 14:30'). Empty if not set."""
    if not month or not day:
        return ""
    months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if month < 1 or month > 12:
        return ""
    return f"{months[month]} {day:02d} {hour:02d}:{minute:02d}"
