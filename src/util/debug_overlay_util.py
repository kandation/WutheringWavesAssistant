"""Screenshot-based debug overlay for story skip detection.

Draws ROI rectangles on a transparent always-on-top window (Discord-style) or on a
separate annotated preview window. Does not inject into or read game process memory.
"""

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np
import win32api
import win32con
import win32gui
import win32ui
from PIL import Image, ImageDraw, ImageWin

logger = logging.getLogger(__name__)

_WINDOW_NAME = "WWA Story Debug"
_OVERLAY_CLASS = "WWAStoryDebugOverlay"
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_ULW_ALPHA = 0x02


@dataclass(frozen=True)
class OverlayBox:
    """Rectangle in client screenshot pixel coordinates (src_img space)."""

    x1: int
    y1: int
    x2: int
    y2: int
    label: str = ""
    color_bgr: tuple[int, int, int] = (0, 255, 255)
    is_hit: bool = False


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class StoryDebugOverlay:
    """Discord-style transparent ROI overlay or annotated preview window."""

    def __init__(self, mode: str = "overlay"):
        self._mode = mode.lower()
        self._hwnd: int | None = None
        self._class_registered = False
        self._warned_missing_rect = False

    @staticmethod
    def from_config(enabled: bool, mode: str = "overlay") -> "StoryDebugOverlay | None":
        if not enabled:
            return None
        return StoryDebugOverlay(mode=mode)

    def close(self):
        if self._hwnd:
            try:
                win32gui.DestroyWindow(self._hwnd)
            except Exception:
                logger.debug("Failed to destroy overlay hwnd", exc_info=True)
            self._hwnd = None
        try:
            cv2.destroyWindow(_WINDOW_NAME)
        except Exception:
            pass

    def update(
        self,
        src_img: np.ndarray,
        boxes: Sequence[OverlayBox],
        client_rect_screen: tuple[int, int, int, int] | None = None,
    ):
        if self._mode == "preview":
            self._show_preview(src_img, boxes, client_rect_screen)
        else:
            self._show_overlay(boxes, client_rect_screen, src_img.shape[1], src_img.shape[0])

    @staticmethod
    def _pump_messages():
        try:
            win32gui.PumpWaitingMessages()
        except Exception:
            logger.debug("Overlay message pump failed", exc_info=True)

    def _show_preview(
        self,
        src_img: np.ndarray,
        boxes: Sequence[OverlayBox],
        client_rect_screen: tuple[int, int, int, int] | None,
    ):
        frame = src_img.copy()
        for box in boxes:
            color = (0, 0, 255) if box.is_hit else box.color_bgr
            thickness = 3 if box.is_hit else 2
            cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, thickness)
            if box.label:
                cv2.putText(
                    frame,
                    box.label,
                    (box.x1, max(box.y1 - 6, 14)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                    cv2.LINE_AA,
                )
        cv2.namedWindow(_WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        cv2.imshow(_WINDOW_NAME, frame)
        cv2.setWindowProperty(_WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1)
        cv2.waitKey(1)
        self._pump_messages()
        if client_rect_screen:
            hwnd = win32gui.FindWindow(None, _WINDOW_NAME)
            if hwnd:
                x1, y1, x2, y2 = client_rect_screen
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOPMOST,
                    x1,
                    y1,
                    x2 - x1,
                    y2 - y1,
                    win32con.SWP_SHOWWINDOW,
                )

    def _register_overlay_class(self):
        if self._class_registered:
            return
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = _OVERLAY_CLASS
        wc.lpfnWndProc = win32gui.DefWindowProc
        wc.hbrBackground = win32gui.GetStockObject(win32con.NULL_BRUSH)
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass
        self._class_registered = True

    def _ensure_overlay_hwnd(self, x: int, y: int, w: int, h: int):
        self._register_overlay_class()
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            win32gui.SetWindowPos(
                self._hwnd,
                win32con.HWND_TOPMOST,
                x,
                y,
                w,
                h,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )
            return
        ex_style = (
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TOOLWINDOW
            | win32con.WS_EX_NOACTIVATE
        )
        self._hwnd = win32gui.CreateWindowEx(
            ex_style,
            _OVERLAY_CLASS,
            "WWA Story Overlay",
            win32con.WS_POPUP,
            x,
            y,
            w,
            h,
            0,
            0,
            win32api.GetModuleHandle(None),
            None,
        )
        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.SetWindowPos(
            self._hwnd,
            win32con.HWND_TOPMOST,
            x,
            y,
            w,
            h,
            win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
        )

    def _show_overlay(
        self,
        boxes: Sequence[OverlayBox],
        client_rect_screen: tuple[int, int, int, int] | None,
        img_w: int,
        img_h: int,
    ):
        if not client_rect_screen:
            if not self._warned_missing_rect:
                logger.warning(
                    "Story debug overlay: no game client rect; overlay hidden "
                    "(set StoryDebugOverlayMode: preview to use a separate window)",
                )
                self._warned_missing_rect = True
            return
        self._warned_missing_rect = False
        sx1, sy1, sx2, sy2 = client_rect_screen
        w, h = sx2 - sx1, sy2 - sy1
        if w <= 0 or h <= 0:
            return

        scale_x = w / img_w
        scale_y = h / img_h
        image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        for box in boxes:
            bx1 = int(box.x1 * scale_x)
            by1 = int(box.y1 * scale_y)
            bx2 = int(box.x2 * scale_x)
            by2 = int(box.y2 * scale_y)
            b, g, r = box.color_bgr
            if box.is_hit:
                r, g, b = 255, 64, 64
            alpha = 255 if box.is_hit else 210
            outline = (r, g, b, alpha)
            width = 3 if box.is_hit else 2
            draw.rectangle([bx1, by1, bx2, by2], outline=outline, width=width)
            if box.label:
                draw.text((bx1 + 2, max(by1 - 14, 0)), box.label, fill=outline)

        self._ensure_overlay_hwnd(sx1, sy1, w, h)
        self._blit_layered(self._hwnd, image, sx1, sy1)
        if self._hwnd:
            win32gui.SetWindowPos(
                self._hwnd,
                win32con.HWND_TOPMOST,
                sx1,
                sy1,
                w,
                h,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )
        self._pump_messages()

    def _blit_layered(self, hwnd: int, image: Image.Image, screen_x: int, screen_y: int):
        hdc_screen = win32gui.GetDC(0)
        hdc_mem = win32ui.CreateCompatibleDC(hdc_screen)
        width, height = image.size
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(hdc_screen, width, height)
        hdc_mem.SelectObject(bmp)
        ImageWin.Dib(image).draw(hdc_mem.GetHandleOutput(), (0, 0, width, height))

        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
        pos = wintypes.POINT(screen_x, screen_y)
        size = wintypes.SIZE(width, height)
        src_point = wintypes.POINT(0, 0)
        ctypes.windll.user32.UpdateLayeredWindow(
            hwnd,
            hdc_screen,
            ctypes.byref(pos),
            ctypes.byref(size),
            hdc_mem.GetSafeHdc(),
            ctypes.byref(src_point),
            0,
            ctypes.byref(blend),
            _ULW_ALPHA,
        )
        win32gui.ReleaseDC(0, hdc_screen)
        hdc_mem.DeleteDC()
