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
from PIL import Image, ImageDraw, ImageFont, ImageWin

logger = logging.getLogger(__name__)

_WINDOW_NAME = "WWA Story Debug"
_OVERLAY_CLASS = "WWAStoryDebugOverlay"
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_ULW_ALPHA = 0x02
_CLICK_MARKER_RADIUS = 8
_STATUS_BAR_HEIGHT = 28
_OVERLAY_FONT_PATHS = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/leelawui.ttf",
    "C:/Windows/Fonts/msyh.ttc",
)
_overlay_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _get_overlay_font(size: int = 14) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size not in _overlay_font_cache:
        for path in _OVERLAY_FONT_PATHS:
            try:
                _overlay_font_cache[size] = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        else:
            _overlay_font_cache[size] = ImageFont.load_default()
    return _overlay_font_cache[size]


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
    click_xy: tuple[int, int] | None = None


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
        *,
        status: str = "",
    ):
        if self._mode == "preview":
            self._show_preview(src_img, boxes, client_rect_screen, status=status)
        else:
            self._show_overlay(
                boxes,
                client_rect_screen,
                src_img.shape[1],
                src_img.shape[0],
                status=status,
            )

    @staticmethod
    def _pump_messages():
        try:
            win32gui.PumpWaitingMessages()
        except Exception:
            logger.debug("Overlay message pump failed", exc_info=True)

    @staticmethod
    def _draw_text_label(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        text: str,
        color: tuple[int, int, int, int],
        *,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
    ):
        if not text:
            return
        label_font = font or _get_overlay_font(14)
        bbox = draw.textbbox((x, y), text, font=label_font)
        pad = 2
        draw.rectangle(
            [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
            fill=(0, 0, 0, 170),
        )
        draw.text((x, y), text, fill=color, font=label_font)

    @staticmethod
    def _draw_click_marker_pil(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple[int, int, int, int]):
        r = _CLICK_MARKER_RADIUS
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
        draw.line([cx - r - 2, cy, cx + r + 2, cy], fill=color, width=2)
        draw.line([cx, cy - r - 2, cx, cy + r + 2], fill=color, width=2)

    @staticmethod
    def _draw_click_marker_cv2(frame: np.ndarray, cx: int, cy: int, color: tuple[int, int, int]):
        r = _CLICK_MARKER_RADIUS
        cv2.circle(frame, (cx, cy), r, color, 2, cv2.LINE_AA)
        cv2.line(frame, (cx - r - 2, cy), (cx + r + 2, cy), color, 2, cv2.LINE_AA)
        cv2.line(frame, (cx, cy - r - 2), (cx, cy + r + 2), color, 2, cv2.LINE_AA)

    def _show_preview(
        self,
        src_img: np.ndarray,
        boxes: Sequence[OverlayBox],
        client_rect_screen: tuple[int, int, int, int] | None,
        *,
        status: str = "",
    ):
        frame = src_img.copy()
        if status:
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 28), (32, 32, 32), -1)
            cv2.putText(
                frame,
                status[:120],
                (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
        for box in boxes:
            color = (0, 0, 255) if box.is_hit else box.color_bgr
            thickness = 3 if box.is_hit else 2
            cv2.rectangle(frame, (box.x1, box.y1), (box.x2, box.y2), color, thickness)
            if box.label:
                label_y = max(box.y1 - 6, 34 if status else 14)
                cv2.putText(
                    frame,
                    box.label,
                    (box.x1, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                    cv2.LINE_AA,
                )
            if box.click_xy is not None:
                self._draw_click_marker_cv2(frame, box.click_xy[0], box.click_xy[1], color)
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
        *,
        status: str = "",
    ):
        if not client_rect_screen:
            if not self._warned_missing_rect:
                logger.warning(
                    "Story debug overlay: no game capture rect; overlay hidden",
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
        label_font = _get_overlay_font(14)
        status_font = _get_overlay_font(13)
        status_offset = _STATUS_BAR_HEIGHT if status else 0

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
            if box.is_hit:
                draw.rectangle([bx1, by1, bx2, by2], fill=(r, g, b, 45), outline=outline, width=width)
            else:
                draw.rectangle([bx1, by1, bx2, by2], outline=outline, width=width)
            if box.label:
                label_y = max(by1 - 18, status_offset + 2 if status else 2)
                self._draw_text_label(
                    draw,
                    bx1 + 2,
                    label_y,
                    box.label,
                    outline,
                    font=label_font,
                )
            if box.click_xy is not None:
                cx = int(box.click_xy[0] * scale_x)
                cy = int(box.click_xy[1] * scale_y)
                self._draw_click_marker_pil(draw, cx, cy, outline)

        if status:
            draw.rectangle(
                [0, 0, w, _STATUS_BAR_HEIGHT],
                fill=(32, 32, 32, 210),
            )
            draw.text((8, 6), status[:120], fill=(0, 255, 255, 255), font=status_font)

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
        hdc_mem = None
        bmp = None
        try:
            screen_dc = win32ui.CreateDCFromHandle(hdc_screen)
            hdc_mem = screen_dc.CreateCompatibleDC()
            width, height = image.size
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(screen_dc, width, height)
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
        finally:
            if bmp is not None:
                win32gui.DeleteObject(bmp.GetHandle())
            if hdc_mem is not None:
                hdc_mem.DeleteDC()
            win32gui.ReleaseDC(0, hdc_screen)
