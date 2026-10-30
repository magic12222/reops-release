"""UTC wall time with native Windows precision; never synthesize or advance timestamps."""
import ctypes
from datetime import datetime, timedelta, timezone
import sys

_precise_filetime = None
if sys.platform == "win32":
    _precise_filetime = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemTimePreciseAsFileTime
    _precise_filetime.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    _precise_filetime.restype = None


def utc_now():
    if _precise_filetime is None:
        return datetime.now(timezone.utc)
    value = ctypes.c_uint64()
    _precise_filetime(ctypes.byref(value))
    # Windows FILETIME counts actual 100ns intervals since 1601-01-01 UTC.
    seconds, remainder = divmod(value.value - 116444736000000000, 10_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc) + timedelta(microseconds=remainder // 10)


def wall_time():
    return utc_now().timestamp()
