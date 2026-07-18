from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable


HC_ACTION = 0
WH_KEYBOARD_LL = 13
CS_DBLCLKS = 0x0008
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_CONTEXTMENU = 0x007B
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_TRAY_SHOW = WM_APP + 2
WM_TRAY_HIDE = WM_APP + 3
WM_TRAY_EXIT = WM_APP + 4
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
IDI_APPLICATION = 32512
IMAGE_ICON = 1
NIF_MESSAGE = 0x0001
NIF_ICON = 0x0002
NIF_TIP = 0x0004
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIM_SETVERSION = 0x00000004
NOTIFYICON_VERSION_4 = 4
LR_LOADFROMFILE = 0x0010
MF_STRING = 0x00000000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
SM_CXSMICON = 49
SM_CYSMICON = 50
GA_ROOT = 2
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20

BYTE = ctypes.c_ubyte
UINT_PTR = ctypes.c_size_t
HINSTANCE = wintypes.HANDLE
HICON = wintypes.HANDLE
HCURSOR = wintypes.HANDLE
HBRUSH = wintypes.HANDLE
HMENU = wintypes.HANDLE
LPVOID = ctypes.c_void_p
LPCRECT = ctypes.POINTER(wintypes.RECT)
ULONG_PTR = wintypes.WPARAM
LRESULT = ctypes.c_ssize_t
HRESULT = ctypes.c_long
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", BYTE * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class PlatformError(RuntimeError):
    pass


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
except OSError:
    dwmapi = None

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    HINSTANCE,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = wintypes.HANDLE
user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = ctypes.c_ushort
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    HMENU,
    HINSTANCE,
    LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.LoadIconW.argtypes = [HINSTANCE, wintypes.LPCWSTR]
user32.LoadIconW.restype = HICON
user32.LoadImageW.argtypes = [
    HINSTANCE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.DestroyIcon.argtypes = [HICON]
user32.DestroyIcon.restype = wintypes.BOOL
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = HMENU
user32.AppendMenuW.argtypes = [HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    LPCRECT,
]
user32.TrackPopupMenu.restype = wintypes.UINT
user32.DestroyMenu.argtypes = [HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
if dwmapi is not None:
    dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, LPVOID, wintypes.DWORD]
    dwmapi.DwmSetWindowAttribute.restype = HRESULT


def win_error(message: str) -> OSError:
    error_code = ctypes.get_last_error()
    if error_code:
        return ctypes.WinError(error_code)
    return OSError(message)


def make_int_resource(value: int) -> wintypes.LPCWSTR:
    return ctypes.cast(ctypes.c_void_p(value), wintypes.LPCWSTR)


def set_window_dark_mode(hwnd: int, enabled: bool) -> bool:
    if dwmapi is None or not hwnd:
        return False

    value = wintypes.BOOL(1 if enabled else 0)
    for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1):
        result = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            attribute,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if result == 0:
            return True
    return False


def get_toplevel_window_handle(hwnd: int) -> int:
    if not hwnd:
        return 0

    top_level_hwnd = user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT)
    if top_level_hwnd:
        return int(top_level_hwnd)
    return int(hwnd)


class TrayIconController:
    ICON_ID = 1
    MENU_RESTORE = 1001
    MENU_EXIT = 1002

    def __init__(
        self,
        tooltip: str,
        on_restore: Callable[[], None],
        on_exit: Callable[[], None],
        on_error: Callable[[Exception], None],
        icon_path: Path | None = None,
    ) -> None:
        self.tooltip = tooltip[:127]
        self.on_restore = on_restore
        self.on_exit = on_exit
        self.on_error = on_error
        self._icon_path = str(icon_path) if icon_path is not None else None
        self._instance = kernel32.GetModuleHandleW(None)
        self._class_name = f"MonitorVolumeTrayWindow_{os.getpid()}_{id(self)}"
        self._wndproc = WNDPROC(self._window_proc)
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._message_loop, name="tray-icon", daemon=True)
        self._start_error: Exception | None = None
        self._hwnd: wintypes.HWND | None = None
        self._icon_visible = False
        self._icon_handle: HICON | None = None
        self._owns_icon_handle = False

    @property
    def is_visible(self) -> bool:
        return self._icon_visible

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()
        if self._start_error is not None:
            raise PlatformError(f"Failed to initialize tray icon: {self._start_error}") from self._start_error
        if self._hwnd is None:
            raise PlatformError("Failed to initialize tray icon.")

    def show(self) -> None:
        if self._hwnd is not None:
            user32.PostMessageW(self._hwnd, WM_TRAY_SHOW, 0, 0)

    def hide(self) -> None:
        if self._hwnd is not None:
            user32.PostMessageW(self._hwnd, WM_TRAY_HIDE, 0, 0)

    def stop(self) -> None:
        if self._hwnd is not None:
            user32.PostMessageW(self._hwnd, WM_TRAY_EXIT, 0, 0)
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _message_loop(self) -> None:
        class_registered = False
        window_class = WNDCLASSW()
        window_class.style = CS_DBLCLKS
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = self._instance
        window_class.lpszClassName = self._class_name
        self._icon_handle = self._load_icon_handle()
        window_class.hIcon = self._icon_handle

        if not user32.RegisterClassW(ctypes.byref(window_class)):
            self._start_error = win_error("RegisterClassW failed")
            self._release_icon_handle()
            self._ready.set()
            return
        class_registered = True

        hwnd = user32.CreateWindowExW(
            0,
            self._class_name,
            self._class_name,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._instance,
            None,
        )
        if not hwnd:
            self._start_error = win_error("CreateWindowExW failed")
            if class_registered:
                user32.UnregisterClassW(self._class_name, self._instance)
            self._release_icon_handle()
            self._ready.set()
            return

        self._hwnd = hwnd
        self._ready.set()

        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == -1:
                self.on_error(win_error("Tray GetMessageW failed"))
                break
            if result == 0:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

        self._hwnd = None
        if class_registered:
            user32.UnregisterClassW(self._class_name, self._instance)
        self._release_icon_handle()

    def _window_proc(self, hwnd: wintypes.HWND, msg: int, w_param: int, l_param: int) -> int:
        if msg == WM_TRAY_SHOW:
            self._show_icon(hwnd)
            return 0
        if msg == WM_TRAY_HIDE:
            self._hide_icon(hwnd)
            return 0
        if msg == WM_TRAY_EXIT:
            self._hide_icon(hwnd)
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_COMMAND:
            command_id = w_param & 0xFFFF
            if command_id == self.MENU_RESTORE:
                self.on_restore()
                return 0
            if command_id == self.MENU_EXIT:
                self.on_exit()
                return 0
        if msg == WM_TRAYICON:
            tray_event = l_param & 0xFFFF
            if tray_event == WM_LBUTTONDBLCLK:
                self.on_restore()
                return 0
            if tray_event in (WM_CONTEXTMENU, WM_RBUTTONUP):
                self._show_context_menu(hwnd)
                return 0
        if msg == WM_DESTROY:
            self._hide_icon(hwnd)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    def _make_notify_icon_data(self, hwnd: wintypes.HWND) -> NOTIFYICONDATAW:
        notify_data = NOTIFYICONDATAW()
        notify_data.cbSize = ctypes.sizeof(notify_data)
        notify_data.hWnd = hwnd
        notify_data.uID = self.ICON_ID
        notify_data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        notify_data.uCallbackMessage = WM_TRAYICON
        notify_data.hIcon = self._icon_handle or user32.LoadIconW(None, make_int_resource(IDI_APPLICATION))
        notify_data.szTip = self.tooltip
        notify_data.uVersion = NOTIFYICON_VERSION_4
        return notify_data

    def _load_icon_handle(self) -> HICON:
        if self._icon_path:
            icon_handle = user32.LoadImageW(
                None,
                self._icon_path,
                IMAGE_ICON,
                user32.GetSystemMetrics(SM_CXSMICON),
                user32.GetSystemMetrics(SM_CYSMICON),
                LR_LOADFROMFILE,
            )
            if icon_handle:
                self._owns_icon_handle = True
                return ctypes.cast(icon_handle, HICON)

        self._owns_icon_handle = False
        return user32.LoadIconW(None, make_int_resource(IDI_APPLICATION))

    def _release_icon_handle(self) -> None:
        if self._icon_handle is not None and self._owns_icon_handle:
            user32.DestroyIcon(self._icon_handle)
        self._icon_handle = None
        self._owns_icon_handle = False

    def _show_icon(self, hwnd: wintypes.HWND) -> None:
        notify_data = self._make_notify_icon_data(hwnd)
        message = NIM_MODIFY if self._icon_visible else NIM_ADD
        if not shell32.Shell_NotifyIconW(message, ctypes.byref(notify_data)):
            self.on_error(win_error("Shell_NotifyIconW failed"))
            return
        if message == NIM_ADD:
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(notify_data))
        self._icon_visible = True

    def _hide_icon(self, hwnd: wintypes.HWND) -> None:
        if not self._icon_visible:
            return
        notify_data = self._make_notify_icon_data(hwnd)
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(notify_data))
        self._icon_visible = False

    def _show_context_menu(self, hwnd: wintypes.HWND) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            self.on_error(win_error("CreatePopupMenu failed"))
            return

        try:
            if not user32.AppendMenuW(menu, MF_STRING, self.MENU_RESTORE, "Restore"):
                self.on_error(win_error("AppendMenuW failed"))
                return
            if not user32.AppendMenuW(menu, MF_STRING, self.MENU_EXIT, "Exit"):
                self.on_error(win_error("AppendMenuW failed"))
                return

            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                self.on_error(win_error("GetCursorPos failed"))
                return

            user32.SetForegroundWindow(hwnd)
            command_id = user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                hwnd,
                None,
            )
            user32.PostMessageW(hwnd, WM_NULL, 0, 0)

            if command_id == self.MENU_RESTORE:
                self.on_restore()
            elif command_id == self.MENU_EXIT:
                self.on_exit()
        finally:
            user32.DestroyMenu(menu)


class GlobalVolumeKeyListener:
    def __init__(
        self,
        on_delta: Callable[[int], None],
        should_consume: Callable[[], bool],
        on_error: Callable[[Exception], None],
        step: int,
    ) -> None:
        self.on_delta = on_delta
        self.should_consume = should_consume
        self.on_error = on_error
        self.step = step
        self._hook_ready = threading.Event()
        self._hook_active = threading.Event()
        self._stop_event = threading.Event()
        self._hook_thread_id = 0
        self._hook_handle: wintypes.HANDLE | None = None
        self._start_error: Exception | None = None
        self._thread = threading.Thread(target=self._hook_loop, name="volume-key-hook", daemon=True)
        self._hook_callback = HOOKPROC(self._keyboard_proc)
        self._volume_key_consumption: dict[int, bool] = {}

    @property
    def is_active(self) -> bool:
        return self._hook_active.is_set()

    def start(self) -> None:
        self._thread.start()
        self._hook_ready.wait()
        if self._start_error is not None:
            raise PlatformError(f"Failed to install keyboard hook: {self._start_error}") from self._start_error
        if self._hook_handle is None:
            raise PlatformError("Failed to install keyboard hook.")

    def stop(self) -> None:
        self._stop_event.set()
        self._hook_active.clear()
        if self._hook_thread_id:
            user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _hook_loop(self) -> None:
        self._hook_thread_id = kernel32.GetCurrentThreadId()
        module_handle = kernel32.GetModuleHandleW(None)
        hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_callback, module_handle, 0)
        if not hook_handle:
            self._start_error = win_error("SetWindowsHookExW failed")
            self._hook_ready.set()
            return

        self._hook_handle = hook_handle
        self._hook_active.set()
        self._hook_ready.set()

        message = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise win_error("GetMessageW failed")
                if result == 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self._hook_active.clear()
            if not self._stop_event.is_set():
                self.on_error(exc)
        finally:
            self._hook_active.clear()
            self._volume_key_consumption.clear()
            if self._hook_handle:
                user32.UnhookWindowsHookEx(self._hook_handle)
                self._hook_handle = None

    def _resolve_volume_key_event(self, vk_code: int, message: int) -> tuple[bool, int | None]:
        if message in (WM_KEYDOWN, WM_SYSKEYDOWN):
            if vk_code not in self._volume_key_consumption:
                self._volume_key_consumption[vk_code] = self.should_consume()

            consume = self._volume_key_consumption[vk_code]
            if not consume or not self.should_consume():
                return consume, None

            delta = self.step if vk_code == VK_VOLUME_UP else -self.step
            return True, delta

        if message in (WM_KEYUP, WM_SYSKEYUP):
            return self._volume_key_consumption.pop(vk_code, False), None

        return False, None

    def _keyboard_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code != HC_ACTION:
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        key_info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if key_info.vkCode not in (VK_VOLUME_DOWN, VK_VOLUME_UP):
            return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        consume, delta = self._resolve_volume_key_event(key_info.vkCode, w_param)
        if delta is not None:
            self.on_delta(delta)

        if consume:
            return 1

        return user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)
