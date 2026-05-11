"""RTL-SDR device enumeration. Mirrors internal/sdr/devices.go.

Uses pyrtlsdr's low-level `librtlsdr` ctypes binding so we work with any
pyrtlsdr version (the high-level RtlSdr class signature changed between
0.2.x and 0.4.x and is not portable).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("skywatch.sdr")


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
    """Enumerate connected RTL-SDR dongles."""
    try:
        from rtlsdr.librtlsdr import librtlsdr  # type: ignore
    except Exception as e:
        log.debug("librtlsdr unavailable: %s", e)
        return []
    try:
        n = int(librtlsdr.rtlsdr_get_device_count())
    except Exception as e:
        log.debug("rtlsdr_get_device_count failed: %s", e)
        return []

    from ctypes import create_string_buffer

    devices: list[Device] = []
    for i in range(n):
        try:
            raw_name = librtlsdr.rtlsdr_get_device_name(i)
            name = raw_name.decode("utf-8", errors="replace") if raw_name else ""
        except Exception as e:
            log.exception(f"Failed to set name of device: {e}")
            name = ""
        manuf = create_string_buffer(256)
        product = create_string_buffer(256)
        serial = create_string_buffer(256)
        mfr = prod = sn = ""
        try:
            librtlsdr.rtlsdr_get_device_usb_strings(i, manuf, product, serial)
            mfr = manuf.value.decode("utf-8", errors="replace")
            prod = product.value.decode("utf-8", errors="replace")
            sn = serial.value.decode("utf-8", errors="replace")
        except Exception as e:
            log.exception(f"Failed to decode rtlsdr values: {e}")

        devices.append(Device(
            index=i,
            manufacturer=mfr,
            product=prod or name,
            serial=sn,
        ))
    return devices
