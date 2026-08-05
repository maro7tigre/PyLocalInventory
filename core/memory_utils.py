"""Process memory measurement helpers used for performance diagnostics."""
from __future__ import annotations

import os
import sys

_PAGE_SIZE = 4096
_CACHED_RSS_MB = None


def process_memory_mb(refresh: bool = False) -> float:
    """Current resident memory of this process in MiB.

    Uses the Windows GetProcessMemoryInfo API when available and psutil
    otherwise, with a graceful fallback that returns 0.0 so logging callers
    never crash on an exotic platform.

    ``refresh=True`` forces a fresh sample instead of the cached value - used
    by diagnostics so log records report live RAM rather than the first sample.
    """
    global _CACHED_RSS_MB
    if _CACHED_RSS_MB is not None and not refresh:
        return _CACHED_RSS_MB

    if sys.platform == "win32":
        value = _windows_rss_bytes()
        if value is not None:
            _CACHED_RSS_MB = value / (1024 * 1024)
            return _CACHED_RSS_MB

    try:
        import psutil
        _CACHED_RSS_MB = psutil.Process().memory_info().rss / (1024 * 1024)
        return _CACHED_RSS_MB
    except Exception:
        return 0.0


def _windows_rss_bytes():
    """Resident set size on Windows via ctypes (no third-party dependency)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = kernel32.GetCurrentProcess()
        if kernel32.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
    except Exception:
        return None
    return None
