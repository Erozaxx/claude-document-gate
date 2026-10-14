"""Transport only: NDJSON bytes from message_format -> UDS (WSL) / pipe (Windows).

The JSON schema intentionally lives ONLY in session_message.json/message_format.py.
This is an EXPERIMENTAL, undocumented Claude Code interface.
"""
from __future__ import annotations
import ctypes
import os
import socket
from urllib.parse import unquote



def _write_unix(address: str, payload: bytes):
    if address.startswith("uds:"):
        address = unquote(address[4:])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.connect(address)
        conn.sendall(payload)
        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _write_win_pipe(address: str, payload: bytes):
    """Windows named pipe client (no pywin32 needed)."""
    from ctypes import wintypes
    if not address.startswith("\\\\.\\pipe\\"):
        raise RuntimeError("Expected Windows named-pipe path from Claude Code")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel.WaitNamedPipeW.restype = wintypes.BOOL
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    if not kernel.WaitNamedPipeW(address, 5000):
        raise OSError(ctypes.get_last_error(), "Timed out waiting for Claude pipe")
    # GENERIC_WRITE, OPEN_EXISTING
    handle = kernel.CreateFileW(address, 0x40000000, 0, None, 3, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "Cannot connect to Claude pipe")
    try:
        buf = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD()
        if not kernel.WriteFile(handle, buf, len(payload), ctypes.byref(written), None):
            raise OSError(ctypes.get_last_error(), "Named-pipe write failed")
        if written.value != len(payload):
            raise OSError("Short Windows named-pipe write")
    finally:
        kernel.CloseHandle(handle)


def send_frames(address: str, payload: bytes):
    if os.name == "nt":
        return _write_win_pipe(address, payload)
    return _write_unix(address, payload)

