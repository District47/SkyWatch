"""RTL-SDR device enumeration. Mirrors internal/sdr/devices.go."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Device:
    index: int
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    in_use: bool = False
    assigned_to: str = ""

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "manufacturer": self.manufacturer,
            "product": self.product,
            "serial": self.serial,
            "in_use": self.in_use,
            "assigned_to": self.assigned_to,
        }


def list_devices() -> list[Device]:
    """Enumerate connected RTL-SDR dongles via pyrtlsdr."""
    try:
        from rtlsdr import RtlSdr  # type: ignore
    except Exception:
        return []
    try:
        count = RtlSdr.get_device_count()
    except Exception:
        return []
    devices: list[Device] = []
    for i in range(count):
        try:
            name = RtlSdr.get_device_name(i)
        except Exception:
            name = ""
        try:
            usb = RtlSdr.get_device_usb_strings(i)
            mfr, prod, serial = usb if isinstance(usb, tuple) else ("", "", "")
        except Exception:
            mfr, prod, serial = "", "", ""
        devices.append(Device(
            index=i,
            manufacturer=mfr or "",
            product=prod or name or "",
            serial=serial or "",
        ))
    return devices
