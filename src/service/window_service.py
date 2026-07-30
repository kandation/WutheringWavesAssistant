import logging
from threading import RLock

from src.core.contexts import Context
from src.core.exceptions import HwndError, raise_as
from src.core.geometry import Scaler, BBox
from src.core.i18n import I18nTr, I18N_TEXT, I18nText, Language

_OCR_SUPPORTED_LANGUAGES = frozenset({Language.ZH, Language.EN})
from src.core.interface import WindowService
from src.util import hwnd_util

logger = logging.getLogger(__name__)


class HwndServiceImpl(WindowService):
    """"Windows Handle to a Window"（窗口句柄）"""

    def __init__(self, context: Context):
        hwnd_util.enable_dpi_awareness()
        super().__init__()
        self._context: Context = context
        if context.spec and context.spec.game_path:
            # 从gui提交的任务game_path必不为空（task monitor会为其赋值），选择强制模式用于兼容多游戏，
            # 当指定的那个游戏异常退出后，因为运行中优先原则，将会误选另一个，强制必须是这个路径的
            self.game_path = context.spec.game_path
            self._handle = hwnd_util.get_hwnd(self.game_path, bool(self.game_path))
        else:
            # 其他情况
            # pytest时，ctx参数不完整，场景也简单，直接取当前运行中的游戏
            hwnds = hwnd_util.get_hwnds()
            if hwnds and len(hwnds) == 1:
                self._handle = hwnds[0]
            else:
                # 要是没有或者有多个，从注册表拿一个
                from src.util import winreg_util
                self.game_path = winreg_util.get_install_path()
                self._handle = hwnd_util.get_hwnd(self.game_path, bool(self.game_path))
        logger.debug(f"WindowService hwnd: {self._handle}")
        self._game_lang = None
        if context.spec and context.spec.game_lang:
            self._game_lang = context.spec.game_lang
        self._rlock: RLock = RLock()

        # runtime
        self._client_wh = None
        self._lang = None
        self._dpt = None

    @property
    def window(self):
        return self.handle

    @property
    def handle(self):
        with self._rlock:
            if not self._handle:
                raise HwndError("handle is None")
            return self._handle

    @property
    def scaler(self) -> Scaler:
        return Scaler(self.get_client_wh())

    @property
    def tr(self) -> I18nTr:
        return I18nTr(self.get_lang())

    @raise_as(HwndError)
    def get_client_wh(self) -> tuple[int, int]:
        if self._client_wh is None:
            self._client_wh = hwnd_util.get_client_wh(self.handle)
        return self._client_wh

    @raise_as(HwndError)
    def window_bbox(self) -> BBox:
        if self._client_wh is None:
            self._client_wh = hwnd_util.get_client_wh(self.handle)
        return BBox(0, 0, *self.get_client_wh())

    def refresh(self) -> bool:
        with self._rlock:
            try:
                self._handle = hwnd_util.get_hwnd(self.game_path, bool(self.game_path))
                if self._handle:
                    self._client_wh = None
                    return True
                return False
            except Exception:
                logger.exception("Get hwnd error!")
                return False

    def _lang_from_runtime_config(self) -> Language | None:
        runtime = getattr(self._context, "runtime", None)
        if runtime and runtime.cfg and runtime.cfg.game:
            return runtime.cfg.game.gameLanguage
        return None

    @staticmethod
    def _normalize_ocr_lang(lang: Language | str | None) -> Language | None:
        if lang is None:
            return None
        if isinstance(lang, str):
            try:
                lang = Language(lang)
            except ValueError:
                logger.warning("Invalid game language code: '%s'", lang)
                return None
        if lang not in _OCR_SUPPORTED_LANGUAGES:
            logger.warning(
                "Game language '%s' is not supported for OCR matching (use zh-CN or en)",
                lang.value,
            )
            return None
        return lang

    @raise_as(HwndError)
    def get_lang(self) -> Language:
        if self._lang is None:
            if self._game_lang:
                self._lang = self._normalize_ocr_lang(self._game_lang)
            if self._lang is None:
                self._lang = self._normalize_ocr_lang(self._lang_from_runtime_config())
            if self._lang is None:
                titles = I18N_TEXT.get(I18nText.WutheringWaves)
                game_title = hwnd_util.get_hwnd_title(self.handle)
                for lang, title in titles.items():
                    if title == game_title:
                        self._lang = self._normalize_ocr_lang(lang)
                        if self._lang:
                            logger.info("Detected game language from window title: '%s'", self._lang.value)
                        break
            if self._lang is None:
                logger.error("Failed to resolve game language; defaulting OCR matching to zh-CN")
                self._lang = Language.ZH
        return self._lang

    def set_lang(self, lang: Language | str | None):
        normalized = self._normalize_ocr_lang(lang)
        if normalized is None:
            logger.warning("Ignoring unsupported OCR language setting: %r", lang)
            return
        if self._lang != normalized:
            if self._lang is not None:
                logger.warning(
                    "OCR/i18n language changed: '%s' -> '%s' (must match in-game text language)",
                    self._lang.value,
                    normalized.value,
                )
            else:
                logger.info("OCR/i18n matching language: '%s' (game text setting)", normalized.value)
        self._lang = normalized

    @raise_as(HwndError)
    def get_ratio(self):
        """窗口大小与1280px的比例"""
        return 1280 / self.get_client_wh()[0]

    @raise_as(HwndError)
    def get_client_rect_on_screen(self) -> tuple[int, int, int, int]:
        return hwnd_util.get_client_rect_on_screen(self.handle)

    @raise_as(HwndError)
    def get_window_rect(self) -> tuple[int, int, int, int]:
        return hwnd_util.get_window_rect(self.handle)

    @raise_as(HwndError)
    def get_focus_rect_on_screen(self, region: tuple[float, float, float, float] | None = None) -> tuple[
        int, int, int, int]:
        return hwnd_util.get_focus_rect_on_screen(self.handle, region)

    @raise_as(HwndError)
    def is_foreground_window(self) -> bool:
        return hwnd_util.is_foreground_window(self.handle)

    @raise_as(HwndError)
    def close_window(self):
        hwnd_util.force_close_process(self.handle)

# class NSWindowServiceImpl(WindowService):
#     pass
