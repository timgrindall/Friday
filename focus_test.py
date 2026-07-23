"""
focus_test.py — test console focus detection via process tree walk.

Works with both classic PowerShell windows and Windows Terminal tabs.

Run this script, then click in and out of the terminal window and press
Enter each time to see if the focus state is detected correctly.
"""

import ctypes
import ctypes.wintypes
import os

TH32CS_SNAPPROCESS = 0x00000002

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize",              ctypes.wintypes.DWORD),
        ("cntUsage",            ctypes.wintypes.DWORD),
        ("th32ProcessID",       ctypes.wintypes.DWORD),
        ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID",        ctypes.wintypes.DWORD),
        ("cntThreads",          ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase",      ctypes.c_long),
        ("dwFlags",             ctypes.wintypes.DWORD),
        ("szExeFile",           ctypes.c_char * 260),
    ]


def _build_parent_map():
    """Return a dict of {pid: parent_pid} for all running processes."""
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.wintypes.HANDLE(-1).value:
        return {}

    parent_map = {}
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

    try:
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                parent_map[entry.th32ProcessID] = entry.th32ParentProcessID
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    return parent_map


def _get_foreground_pid():
    """Return the PID of the process that owns the foreground window."""
    user32   = ctypes.windll.user32
    hwnd     = user32.GetForegroundWindow()
    pid      = ctypes.wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_console_focused():
    """
    Return True if the foreground window belongs to this process or any
    ancestor process (handles Windows Terminal where the terminal host is a
    parent of the Python process, not the process itself).
    """
    foreground_pid = _get_foreground_pid()
    parent_map     = _build_parent_map()
    our_pid        = os.getpid()

    # Walk up the process tree from our PID
    visited = set()
    pid = our_pid
    while pid and pid not in visited:
        if pid == foreground_pid:
            return True
        visited.add(pid)
        pid = parent_map.get(pid)

    return False


if __name__ == "__main__":
    print("Focus detection test.")
    print("Click in/out of this window and press Enter each time.\n")
    print("Ctrl+C to quit.\n")
    try:
        while True:
            input("Press Enter to check focus... ")
            focused = is_console_focused()
            fg_pid  = _get_foreground_pid()
            our_pid = os.getpid()
            print(f"  Our PID:        {our_pid}")
            print(f"  Foreground PID: {fg_pid}")
            print(f"  Focused:        {focused}\n")
    except KeyboardInterrupt:
        print("\nDone.")
