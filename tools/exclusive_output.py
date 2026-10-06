"""Create a new file without following an existing leaf link.

Windows CRT x-mode followed dangling symlinks in native CI. Inspect the directory
entry with lstat, then use CreateFileW(CREATE_NEW, OPEN_REPARSE_POINT) rather than
relying on CRT O_EXCL semantics. POSIX uses O_EXCL plus O_NOFOLLOW where available.
A write failure can leave a partial *new* file; existing entries are never removed.

Windows API contract:
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
"""

import ctypes
from ctypes import wintypes
import errno
import os
from pathlib import Path
import sys
from types import SimpleNamespace


_WINDOWS = sys.platform == 'win32'
GENERIC_WRITE = 0x40000000
CREATE_NEW = 1
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _existing(path):
    return FileExistsError(errno.EEXIST, 'refusing existing output, including symbolic links', str(path))


def _windows_api():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return SimpleNamespace(create=kernel.CreateFileW, write=kernel.WriteFile,
                           flush=kernel.FlushFileBuffers, close=kernel.CloseHandle,
                           error=ctypes.get_last_error)


def _windows_error(code, path):
    if code in (80, 183):  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
        error = _existing(path)
    else:
        # The fourth argument lets Windows select the native errno and subclass.
        # Assigning winerror afterward does not change an existing OSError's type.
        # This fallback supports API doubles on hosts that ignore that argument.
        fallback_errno = {2: errno.ENOENT, 3: errno.ENOENT, 5: errno.EACCES}.get(code, errno.EIO)
        error = OSError(fallback_errno,
                        f'Windows output operation failed with error {code}', str(path), code)
    error.winerror = code
    return error


def _write_windows(path, data):
    api = _windows_api()
    handle = api.create(str(path.absolute()), GENERIC_WRITE, 0, None, CREATE_NEW,
                        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, None)
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise _windows_error(api.error(), path)
    try:
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 1024 * 1024]
            buffer = ctypes.create_string_buffer(chunk)
            written = wintypes.DWORD()
            if not api.write(handle, buffer, len(chunk), ctypes.byref(written), None):
                raise _windows_error(api.error(), path)
            if not 0 < written.value <= len(chunk):
                raise OSError(errno.EIO, 'invalid byte count while writing new output', str(path))
            offset += written.value
        if not api.flush(handle):
            raise _windows_error(api.error(), path)
    finally:
        closed = api.close(handle)
        if not closed and sys.exc_info()[0] is None:
            raise _windows_error(api.error(), path)


def _write_posix(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        output = os.fdopen(descriptor, 'wb')
    except BaseException:
        os.close(descriptor)
        raise
    with output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def write_text_exclusive(path, text, *, create_parents=False):
    """Write only to a new directory entry, preserving existing links and targets."""
    data = text.encode('utf-8')  # Encode before creating any filesystem entry.
    write_bytes_exclusive(path, data, create_parents=create_parents)


def write_bytes_exclusive(path, data, *, create_parents=False):
    """Write exact bytes to a new entry, using the same link guards as reports."""
    if not isinstance(data, bytes):
        raise TypeError('exclusive binary output requires bytes')
    path = Path(path)
    try:
        path.lstat()  # exists() follows links and misses dangling ones.
    except FileNotFoundError:
        pass
    else:
        raise _existing(path)
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    if _WINDOWS:
        _write_windows(path, data)
    else:
        _write_posix(path, data)
