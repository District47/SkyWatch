"""Idempotent post-install patcher for pyrtlsdr.

Older librtlsdr.dll builds (including the rtl-sdr-blog Windows release we
ship in tools/win64/) lack newer symbols like ``rtlsdr_set_dithering`` and
``rtlsdr_set_bias_tee``. pyrtlsdr's ``librtlsdr.py`` blindly binds those
symbols at import time, which raises ``AttributeError`` and leaves the
module half-initialised. The next ``import rtlsdr`` then fails with
``deadlock detected by _ModuleLock`` because Python sees a partially-loaded
entry in ``sys.modules``.

Fix: rewrite the line that loads the C library so we wrap it in a small
``_LibWrapper`` that returns a no-op stub for missing symbols. Run from
``start.bat`` / ``start.sh`` immediately after ``pip install``.

Idempotent — leaves a marker comment so re-running is a no-op.
"""
from __future__ import annotations

import sys
from pathlib import Path

PATCH_MARKER = "# SkyWatch pyrtlsdr-missing-symbol shim v1"

PROLOGUE = '''
{marker}
class _MissingFuncStub:
    """Stand-in for a librtlsdr export that the loaded DLL doesn't provide.
    Returns 0 (success) so pyrtlsdr's bookkeeping accepts the call."""
    def __init__(self, name): self._name = name
    def __call__(self, *a, **kw): return 0
    @property
    def argtypes(self): return []
    @argtypes.setter
    def argtypes(self, _): pass
    @property
    def restype(self): return None
    @restype.setter
    def restype(self, _): pass

class _LibWrapper:
    def __init__(self, lib): self.__dict__["_lib"] = lib
    def __getattr__(self, name):
        try: return getattr(self._lib, name)
        except (AttributeError, OSError): return _MissingFuncStub(name)
    def __setattr__(self, name, value):
        try: setattr(self._lib, name, value)
        except (AttributeError, OSError): pass
'''.lstrip()


def find_pyrtlsdr_librtlsdr() -> Path | None:
    try:
        import rtlsdr  # noqa: F401
    except Exception as e:
        # Even if the import is currently broken, the on-disk file still
        # exists — locate it via the package spec.
        import importlib.util
        spec = importlib.util.find_spec("rtlsdr")
        if not spec or not spec.submodule_search_locations:
            print(f"[skip] pyrtlsdr not installed: {e}")
            return None
        return Path(list(spec.submodule_search_locations)[0]) / "librtlsdr.py"
    import rtlsdr
    return Path(rtlsdr.__file__).parent / "librtlsdr.py"


def patch(verbose: bool = False) -> str:
    """Apply the patch. Returns one of: 'patched', 'already', 'skip', 'error'.
    Never raises — bootstrap calls this and must not crash on it."""
    try:
        src = find_pyrtlsdr_librtlsdr()
        if src is None or not src.is_file():
            if verbose: print("[skip] could not locate rtlsdr/librtlsdr.py")
            return "skip"
        text = src.read_text(encoding="utf-8")
        if PATCH_MARKER in text:
            if verbose: print(f"[ok]   {src} already patched")
            return "already"

        target = "librtlsdr = load_librtlsdr()"
        if target not in text:
            if verbose: print(f"[warn] assignment not found in {src}")
            return "skip"
        new_text = text.replace(
            target,
            target + "\nlibrtlsdr = _LibWrapper(librtlsdr)",
            1,
        )
        new_text = PROLOGUE.format(marker=PATCH_MARKER) + new_text
        src.write_text(new_text, encoding="utf-8")
        if verbose: print(f"[ok]   patched {src}")
        return "patched"
    except Exception as e:
        if verbose: print(f"[err]  {e}")
        return "error"


if __name__ == "__main__":
    result = patch(verbose=True)
    sys.exit(0 if result in ("patched", "already", "skip") else 1)
