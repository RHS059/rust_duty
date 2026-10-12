"""Desktop input drivers for the opt-in real-game matrix. No rendering or readback.

These drivers use an existing dedicated desktop; they never provision a display,
install software, change display settings, or silently fall back to another GPU.
"""
import ctypes
from ctypes import wintypes
import os
import shutil
import subprocess
import sys
import time


class DriverError(RuntimeError):
    pass


def exit_snapshot(driver, process, *, probe_responsiveness=False):
    """Best-effort status only; diagnostic failures must not mask exit failures."""
    try:
        return driver.exit_status(process, probe_responsiveness=probe_responsiveness)
    except Exception as error:
        return {'unavailable': type(error).__name__}


class TrackedDriver:
    """Release only inputs this controller injected, including failed attempts."""
    def __init__(self, driver):
        self.driver = driver
        self.held_keys = set()
        self.aim_held = False

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def key(self, name, down):
        if down:
            self.held_keys.add(name)
        self.driver.key(name, down)
        if not down:
            self.held_keys.discard(name)

    def aim(self, down):
        if down:
            self.aim_held = True
        self.driver.aim(down)
        if not down:
            self.aim_held = False

    def close(self):
        # Use the application's own normal exit on both desktop backends. A
        # queued Windows WM_CLOSE did not finish the first CI surface smoke.
        tap(self, 'F10')

    def release_inputs(self):
        errors = []
        for key in sorted(self.held_keys.copy()):
            try:
                self.key(key, False)
            except (OSError, DriverError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        if self.aim_held:
            try:
                self.aim(False)
            except (OSError, DriverError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        return errors


def wait_until(check, timeout=15, label='desktop condition'):
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise DriverError('Timed out waiting for ' + label)
        time.sleep(0.05)


class X11Driver:
    def __init__(self):
        if not os.environ.get('DISPLAY') or not shutil.which('xdotool'):
            raise DriverError('x11 requires an existing DISPLAY and installed xdotool')
        self.window = None

    def command(self, *args, optional=False):
        result = subprocess.run(['xdotool', *map(str, args)], text=True,
                                capture_output=True, timeout=5, check=False)
        if result.returncode and not optional:
            raise DriverError('xdotool failed: ' + result.stderr.strip())
        return result.stdout.strip() if result.returncode == 0 else ''

    def bind(self, pid):
        def find():
            candidates = self.command('search', '--all', '--onlyvisible', '--pid', pid,
                                      '--name', '^VECTOR RANGE', optional=True).splitlines()
            if len(candidates) > 1:
                raise DriverError('Multiple visible game windows for the launched PID')
            if candidates:
                if self.command('getwindowpid', candidates[0]) != str(pid):
                    raise DriverError('Window PID differs from launched game process')
                return candidates[0]
            return None
        self.window = wait_until(find, label='PID-owned game window')

    def geometry(self):
        values = dict(line.split('=', 1) for line in
                      self.command('getwindowgeometry', '--shell', self.window).splitlines())
        return [int(values['WIDTH']), int(values['HEIGHT'])]

    def configure(self, size):
        self.command('windowsize', '--sync', self.window, *size)
        wait_until(lambda: self.geometry() == size, label='exact physical client extent')
        self.command('windowfocus', '--sync', self.window)
        self.check(size)

    def check(self, size):
        if self.command('getwindowfocus') != self.window or self.geometry() != size:
            raise DriverError('Game focus or client extent changed; run is invalid')

    def key(self, name, down):
        self.command('keydown' if down else 'keyup', name)

    def aim(self, down):
        self.command('mousedown' if down else 'mouseup', '3')

    def close(self):
        # xdotool windowclose calls XDestroyWindow, not WM_DELETE_WINDOW. Use
        # the game's own F10 exit after the controller verifies its focus.
        tap(self, 'F10')


class WindowsDriver:
    KEYS = {'Return': 0x0D, 'F1': 0x70, 'F2': 0x71, 'F8': 0x77, 'F10': 0x79,
            'w': 0x57, 's': 0x53}

    def __init__(self):
        if sys.platform != 'win32':
            raise DriverError('win32 requires Windows with an interactive desktop')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.window = None
        self._bind_api()
        # Only this controller process becomes DPI aware. No OS setting changes.
        if hasattr(self.user, 'SetProcessDpiAwarenessContext'):
            self.user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            self.user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
            self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

    def _bind_api(self):
        u = self.user
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback, wintypes.LPARAM], wintypes.BOOL),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'IsWindow': ([wintypes.HWND], wintypes.BOOL),
            'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'GetWindowTextW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetClientRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'SetWindowPos': ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
            'SetForegroundWindow': ([wintypes.HWND], wintypes.BOOL),
            'GetForegroundWindow': ([], wintypes.HWND),
            'PostMessageW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            'SendInput': ([wintypes.UINT, ctypes.c_void_p, ctypes.c_int], wintypes.UINT),
            'GetGUIThreadInfo': ([wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            'SendMessageTimeoutW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
        }
        for name, (args, result) in signatures.items():
            getattr(u, name).argtypes = args
            getattr(u, name).restype = result
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.GetProcessTimes.restype = wintypes.BOOL

    def exit_status(self, process, *, probe_responsiveness=False):
        """Read only the launched process and its previously bound window.

        Call outside recording, before exit and after an exit timeout. WM_NULL
        is bounded and only sent after rechecking that this HWND still belongs
        to the launched PID. A response is message-pump evidence, not evidence
        that F10 was handled or that another frame reached the screen.
        """
        code = process.poll()
        result = {'observed_unix_ns': time.time_ns(), 'pid': process.pid,
                  'process_alive': code is None, 'returncode': code,
                  'cpu_time_100ns': None, 'window': {'hwnd': self.window},
                  'errors': []}
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if self.kernel.GetProcessTimes(process._handle, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kernel), ctypes.byref(user)):
            ticks = lambda value: (value.dwHighDateTime << 32) | value.dwLowDateTime
            result['cpu_time_100ns'] = {'kernel': ticks(kernel), 'user': ticks(user)}
        else:
            result['errors'].append({'operation': 'GetProcessTimes',
                                     'winerror': ctypes.get_last_error()})

        window = result['window']
        window['exists'] = bool(self.window and self.user.IsWindow(self.window))
        window['owned_by_launched_process'] = False
        window['responsiveness'] = {'attempted': False}
        if not window['exists']:
            return result
        owner = wintypes.DWORD()
        thread = self.user.GetWindowThreadProcessId(self.window, ctypes.byref(owner))
        if not thread or owner.value != process.pid:
            # A stale/reused handle must not expand this probe to another process.
            window['responsiveness']['reason'] = 'window_owner_unverified'
            return result
        window.update(owned_by_launched_process=True, owner_pid=owner.value,
                      owner_thread_id=thread,
                      visible=bool(self.user.IsWindowVisible(self.window)),
                      foreground=self.user.GetForegroundWindow() == self.window)
        rect = wintypes.RECT()
        if self.user.GetClientRect(self.window, ctypes.byref(rect)):
            window['client_extent'] = [rect.right - rect.left, rect.bottom - rect.top]
        else:
            result['errors'].append({'operation': 'GetClientRect',
                                     'winerror': ctypes.get_last_error()})

        class GuiThreadInfo(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                        ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                        ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                        ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                        ('rcCaret', wintypes.RECT)]
        gui = GuiThreadInfo()
        gui.cbSize = ctypes.sizeof(gui)
        if self.user.GetGUIThreadInfo(thread, ctypes.byref(gui)):
            window['gui_thread'] = {'flags': gui.flags, 'in_move_size': bool(gui.flags & 0x02),
                                    'in_menu_mode': bool(gui.flags & 0x04),
                                    'system_menu_mode': bool(gui.flags & 0x08),
                                    'popup_menu_mode': bool(gui.flags & 0x10)}
        else:
            result['errors'].append({'operation': 'GetGUIThreadInfo',
                                     'winerror': ctypes.get_last_error()})
        if probe_responsiveness and code is None:
            reply = ctypes.c_size_t()
            # WM_NULL; SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT.
            # Never SMTO_NOTIMEOUTIFNOTHUNG, which could exceed this bound.
            ctypes.set_last_error(0)
            started = time.monotonic_ns()
            responded = self.user.SendMessageTimeoutW(
                self.window, 0, 0, 0, 0x01 | 0x02 | 0x20, 2000, ctypes.byref(reply))
            window['responsiveness'] = {
                'attempted': True, 'message': 'WM_NULL', 'timeout_ms': 2000,
                'responded': bool(responded),
                'winerror': None if responded else ctypes.get_last_error(),
                'elapsed_ns': time.monotonic_ns() - started}
        return result

    def bind(self, pid):
        def find():
            windows = []
            @self.callback
            def visit(hwnd, unused):
                owner = wintypes.DWORD()
                self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                name = ctypes.create_unicode_buffer(256)
                self.user.GetWindowTextW(hwnd, name, len(name))
                if owner.value == pid and self.user.IsWindowVisible(hwnd) and name.value.startswith('VECTOR RANGE'):
                    windows.append(hwnd)
                return True
            if not self.user.EnumWindows(visit, 0):
                raise DriverError('Could not enumerate desktop windows')
            if len(windows) > 1:
                raise DriverError('Multiple visible game windows for the launched PID')
            return windows[0] if windows else None
        self.window = wait_until(find, label='PID-owned game window')

    def rect(self, client):
        value = wintypes.RECT()
        method = self.user.GetClientRect if client else self.user.GetWindowRect
        if not method(self.window, ctypes.byref(value)):
            raise DriverError('Could not read game window dimensions')
        return value

    def geometry(self):
        value = self.rect(True)
        return [value.right - value.left, value.bottom - value.top]

    def configure(self, size):
        client, outer = self.rect(True), self.rect(False)
        width = size[0] + outer.right - outer.left - client.right + client.left
        height = size[1] + outer.bottom - outer.top - client.bottom + client.top
        if not self.user.SetWindowPos(self.window, None, 0, 0, width, height, 0x0004):
            raise DriverError('Could not resize game client area')
        wait_until(lambda: self.geometry() == size, label='exact physical client extent')
        if not self.user.SetForegroundWindow(self.window):
            raise DriverError('Windows refused game focus; use a dedicated interactive desktop')
        self.check(size)

    def check(self, size):
        if self.user.GetForegroundWindow() != self.window or self.geometry() != size:
            raise DriverError('Game focus or client extent changed; run is invalid')

    def send_input(self, keyboard=None, mouse_flags=None):
        class Mouse(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                        ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]
        class Key(ctypes.Structure):
            _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                        ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]
        class Hardware(ctypes.Structure):
            _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]
        class Payload(ctypes.Union):
            _fields_ = [('mi', Mouse), ('ki', Key), ('hi', Hardware)]
        class Input(ctypes.Structure):
            _fields_ = [('type', wintypes.DWORD), ('payload', Payload)]
        value = Input()
        if keyboard is not None:
            value.type = 1
            value.payload.ki = Key(keyboard[0], 0, 0 if keyboard[1] else 0x0002, 0, 0)
        else:
            value.type = 0
            value.payload.mi.dwFlags = mouse_flags
        if self.user.SendInput(1, ctypes.byref(value), ctypes.sizeof(value)) != 1:
            raise DriverError('Windows refused input injection')

    def key(self, name, down):
        self.send_input(keyboard=(self.KEYS[name], down))

    def aim(self, down):
        self.send_input(mouse_flags=0x0008 if down else 0x0010)

    def close(self):
        tap(self, 'F10')


def create_driver(name):
    return TrackedDriver({'x11': X11Driver, 'win32': WindowsDriver}[name]())


def tap(driver, key):
    driver.key(key, True)
    try:
        time.sleep(0.10)
    finally:
        driver.key(key, False)


def replay(driver, process, size, action, duration):
    """Replay wall-clock inputs. Simulation outcomes are checked separately.

    No framebuffer capture is performed. Extent/focus polling is the same in
    every case; this external-controller cost is part of the protocol.
    """
    started = time.monotonic()
    held = None
    events = []
    try:
        driver.aim(action == 'ads')
        while (elapsed := time.monotonic() - started) < duration:
            if process.poll() is not None:
                raise DriverError('Game exited during timed input replay')
            driver.check(size)
            desired = ('w' if int(elapsed / 2) % 2 == 0 else 's') if action == 'movement' else None
            if desired != held:
                if held:
                    driver.key(held, False)
                if desired:
                    driver.key(desired, True)
                held = desired
                events.append({'elapsed_seconds': elapsed, 'key_down': held})
            time.sleep(min(0.10, max(0, duration - elapsed)))
    finally:
        try:
            if held:
                driver.key(held, False)
        finally:
            driver.aim(False)
    return {'elapsed_seconds': time.monotonic() - started, 'input_transitions': events,
            'replay_basis': 'wall-clock W/S alternation every two seconds; not fixed simulation replay'}
