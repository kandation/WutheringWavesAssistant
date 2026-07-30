import logging
import os
import re
import threading
import time

import numpy as np
from pynput import keyboard

from src.core.contexts import Context
from src.core.i18n import Language
from src.core.interface import ControlService, OCRService, ImgService, WindowService, ODService, BossInfoService
from src.core.pages import Page, Position, TextMatch, ConditionalAction, ImageMatch
from src.core.regions import DynamicPosition, TextPosition
from src.service.page_event_service import PageEventAbstractService
from src.util.debug_overlay_util import OverlayBox, StoryDebugOverlay
from src.util.wrap_util import timeit

logger = logging.getLogger(__name__)

# ROIs normalized to 1280x720 reference coordinates.
# Bottom Skip pill — Thai/EN client often shows "ข้าม" / "Skip" on the lower-right.
_BOTTOM_SKIP_ROI_RATE = (680 / 1280, 470 / 720, 1080 / 1280, 580 / 720)
# Wider bottom strip (covers centered / left skip buttons on some layouts).
_BOTTOM_BAR_ROI_RATE = (0.30, 0.78, 0.98, 0.97)
_TOP_LEFT_SKIP_ROI_RATE = (0.0, 0.0, 200 / 1280, 150 / 720)
# Dialog / confirm popups after pressing skip.
_DIALOG_ROI_RATE = (0.10, 0.20, 0.90, 0.92)

_SKIP_SCAN_ROIS: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    ("bottom-right", _BOTTOM_SKIP_ROI_RATE),
    ("bottom-bar", _BOTTOM_BAR_ROI_RATE),
    ("top-left", _TOP_LEFT_SKIP_ROI_RATE),
)

# Flexible patterns — OCR may add spaces or misread Thai; avoid strict ^$.
_SKIP_BUTTON_RE = re.compile(
    r"(?:"
    r"ข\s*้\s*าม|ข้าม|"
    r"跳过|"
    r"[Ss][Kk][Ii][Pp]|Skip"
    r")",
    re.I,
)
_SKIP_STORY_RE = re.compile(
    r"(?:"
    r"ข\s*้\s*าม\s*เนื้อ\s*เรื่อง|ข้ามเนื้อเรื่อง|"
    r"跳过剧情|"
    r"[Ss][Kk][Ii][Pp]"
    r")",
    re.I,
)
_RESUME_RE = re.compile(r"(?:继续观看|ดูต่อ|Resume)", re.I)
_CONFIRM_RE = re.compile(r"(?:确认|ยืนยัน|Confirm)", re.I)
_DONT_SHOW_AGAIN_RE = re.compile(
    r"(?:本次登录不再提示|ไม่แสดงอีก|Do not show again)",
    re.I,
)
_SKIP_CONFIRM_BODY_RE = re.compile(
    r"(?:完整观看剧情.*是否确认跳过|ดูเนื้อเรื่อง.*ยืนยันที่จะข้าม|ยืนยันที่จะข้าม)",
    re.I,
)


class DynamicFpsLimit:

    def __init__(self):
        self.key_press_time = None

    def sleep(self, execute_use_seconds: float, fps_lock: float | None = None):
        """
        动态fps
        :param execute_use_seconds:
        :param fps_lock: 固定fps，即不使用动态fps
        :return:
        """
        if fps_lock is None:
            now = time.perf_counter_ns()
            if self.key_press_time is None:
                fps = 1
            else:
                idle_seconds = (now - self.key_press_time) / 1e9
                if idle_seconds < 3:
                    # logger.warning("3秒")
                    fps = 1 / 3  # 按键3秒内有动过，可能不在剧情对话中，检测频率为3秒一次
                elif idle_seconds < 5:
                    fps = 1 / 2  # 2秒一次
                else:  # idle_seconds >= 5
                    fps = 1  # 超过5秒按键没有动过，可能进入剧情，检测频率为1秒一次
        else:
            fps = fps_lock
        seconds = 1 / fps
        # logger.info(f"seconds: {seconds:.2f}")
        sleep_seconds = seconds - execute_use_seconds # 减去流程耗时
        if sleep_seconds > 0.0001:
            logger.debug("sleep: %s", sleep_seconds)
            time.sleep(sleep_seconds)

    def refresh(self):
        self.key_press_time = time.perf_counter_ns()


class AutoStoryServiceImpl(PageEventAbstractService):
    """自动过剧情"""

    def __init__(self, context: Context, window_service: WindowService, img_service: ImgService,
                 ocr_service: OCRService, control_service: ControlService, od_service: ODService,
                 boss_info_service: BossInfoService):
        logger.debug("Initializing %s", self.__class__.__name__)
        super().__init__(context, window_service, img_service, ocr_service, control_service, od_service, boss_info_service)
        self._img_service.set_capture_mode(ImgService.CaptureEnum.FG)

        self._story_pages: list[Page] = []
        self._build_story_pages()
        self._story_conditional_actions: list[ConditionalAction] = []

        # skip_page
        env_skip_is_open = context.spec.skip_is_open
        self.skip_is_open = env_skip_is_open is True # 跳过剧情 还是 沉浸式
        self.skip_btn_is_clicked = False # 是否点击了跳过按钮，用于开启不再提示和剧情梗概的识别
        self.skip_btn_is_clicked_start_time = time.time()
        self.skip_btn_is_clicked_timeout = 3 # 不再提示和剧情梗概识别的最大时间，避免万一clicked状态未变导致每次都识别占用资源

        # auto_play_page
        self._is_auto_play_enabled: bool = False

        # mouse move param
        self._mouse_idle_time = 2.5
        self._mouse_last_check_time = None
        self._listener_thread = None

        # fps limit
        self._dynamic_fps_limit = DynamicFpsLimit()

        app_cfg = context.config.app
        story_debug = bool(app_cfg.StoryDebugMode) or os.environ.get(
            "WWA_STORY_DEBUG", "").lower() in ("1", "true", "yes")
        try:
            if self._window_service.get_lang() == Language.TH:
                story_debug = True
        except Exception:
            pass
        overlay_mode = getattr(app_cfg, "StoryDebugOverlayMode", "overlay")
        self._debug_overlay = StoryDebugOverlay.from_config(story_debug, mode=overlay_mode)
        if story_debug:
            logger.info(
                "Story debug ON (mode=%s) — set StoryDebugMode: false in config.yaml to hide",
                overlay_mode,
            )

    @staticmethod
    def _clamp_roi(
            x1: int, y1: int, x2: int, y2: int, w: int, h: int,
    ) -> tuple[int, int, int, int]:
        """Clamp ROI to image bounds and guarantee at least 1px width/height."""
        if w <= 0 or h <= 0:
            return 0, 0, 0, 0
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        return x1, y1, x2, y2

    @classmethod
    def _roi_from_rate(
            cls,
            src_img: np.ndarray,
            rate: tuple[float, float, float, float],
    ) -> tuple[int, int, int, int]:
        h, w = src_img.shape[:2]
        return cls._clamp_roi(
            int(rate[0] * w),
            int(rate[1] * h),
            int(rate[2] * w),
            int(rate[3] * h),
            w,
            h,
        )

    @classmethod
    def _roi_position_from_rate(
            cls,
            img: np.ndarray,
            rate: tuple[float, float, float, float],
    ) -> Position | None:
        x1, y1, x2, y2 = cls._roi_from_rate(img, rate)
        if x2 <= x1 or y2 <= y1:
            return None
        return Position.build(x1, y1, x2, y2)

    @staticmethod
    def _map_ocr_match_to_src(
            src_img: np.ndarray,
            img: np.ndarray,
            roi_pos: Position,
            match: TextPosition,
    ) -> TextPosition:
        ratio = src_img.shape[0] / img.shape[0]
        return match.build(
            x1=int((match.x1 + roi_pos.x1) * ratio),
            y1=int((match.y1 + roi_pos.y1) * ratio),
            x2=int((match.x2 + roi_pos.x1) * ratio),
            y2=int((match.y2 + roi_pos.y1) * ratio),
            confidence=match.confidence,
            text=match.text,
        )

    @staticmethod
    def _normalize_ocr_text(text: str) -> str:
        return re.sub(r"\s+", "", (text or "").strip())

    @classmethod
    def _match_skip_button(cls, text: str) -> bool:
        raw = (text or "").strip()
        if not raw:
            return False
        if _SKIP_BUTTON_RE.search(raw):
            return True
        compact = cls._normalize_ocr_text(raw)
        return bool(compact and _SKIP_BUTTON_RE.search(compact))

    @staticmethod
    def _ocr_boxes_to_overlay(
            matches: list[TextPosition],
            *,
            hit: TextPosition | None = None,
    ) -> list[OverlayBox]:
        boxes: list[OverlayBox] = []
        for m in matches:
            is_hit = hit is not None and m is hit
            label = f"{'HIT ' if is_hit else ''}{m.text!r}"
            boxes.append(OverlayBox(
                m.x1, m.y1, m.x2, m.y2,
                label=label,
                color_bgr=(0, 0, 255) if is_hit else (160, 160, 160),
                is_hit=is_hit,
                click_xy=(int(m.center[0]), int(m.center[1])) if is_hit else None,
            ))
        return boxes

    def _ocr_roi(
            self,
            src_img: np.ndarray,
            img: np.ndarray,
            roi_rate: tuple[float, float, float, float],
    ) -> tuple[Position | None, list[TextPosition]]:
        """Run OCR inside ROI; return positions mapped to src_img coordinates."""
        roi_pos = self._roi_position_from_rate(img, roi_rate)
        if roi_pos is None:
            return None, []
        results = self._ocr_service.ocr(img, roi_pos)
        mapped: list[TextPosition] = []
        for item in results:
            mapped.append(self._map_ocr_match_to_src(src_img, img, roi_pos, item))
        return roi_pos, mapped

    def _find_skip_in_roi(
            self,
            src_img: np.ndarray,
            img: np.ndarray,
            roi_rate: tuple[float, float, float, float],
    ) -> TextPosition | None:
        _, mapped = self._ocr_roi(src_img, img, roi_rate)
        for item in mapped:
            if self._match_skip_button(item.text):
                return item
        return None

    def _find_skip_anywhere(
            self,
            src_img: np.ndarray,
            img: np.ndarray,
    ) -> tuple[TextPosition | None, list[TextPosition], str]:
        all_mapped: list[TextPosition] = []
        for region_name, roi_rate in _SKIP_SCAN_ROIS:
            _, mapped = self._ocr_roi(src_img, img, roi_rate)
            all_mapped.extend(mapped)
            for item in mapped:
                if self._match_skip_button(item.text):
                    return item, all_mapped, region_name
        return None, all_mapped, ""

    def _ocr_find_skip_in_roi(
            self,
            src_img: np.ndarray,
            img: np.ndarray,
            roi_rate: tuple[float, float, float, float],
    ) -> TextPosition | None:
        return self._find_skip_in_roi(src_img, img, roi_rate)

    def _click_position(self, position: Position, *, label: str) -> bool:
        x, y = position.center
        logger.info("Click %s at (%s, %s) text=%r", label, x, y, getattr(position, "text", ""))
        time.sleep(0.1)
        self._control_service.click(x, y)
        time.sleep(0.1)
        self._control_service.click(x, y)
        time.sleep(0.1)
        return True

    def _roi_overlay_box(
            self,
            src_img: np.ndarray,
            roi_rate: tuple[float, float, float, float],
            label: str,
            color_bgr: tuple[int, int, int],
            *,
            is_hit: bool = False,
    ) -> OverlayBox:
        x1, y1, x2, y2 = self._roi_from_rate(src_img, roi_rate)
        return OverlayBox(x1, y1, x2, y2, label=label, color_bgr=color_bgr, is_hit=is_hit)

    def _update_debug_overlay(
            self,
            src_img: np.ndarray,
            *,
            status: str = "",
            roi_boxes: list[OverlayBox] | None = None,
            ocr_hits: list[TextPosition] | None = None,
            skip_hit: TextPosition | None = None,
    ):
        if self._debug_overlay is None:
            return
        boxes: list[OverlayBox] = list(roi_boxes or [])
        if ocr_hits:
            boxes.extend(self._ocr_boxes_to_overlay(ocr_hits, hit=skip_hit))
        try:
            capture_rect = self._window_service.get_capture_rect_on_screen()
        except Exception:
            logger.warning("Story debug overlay: failed to get capture rect", exc_info=True)
            capture_rect = None
        self._debug_overlay.update(src_img, boxes, capture_rect, status=status)

    def _debug_roi_boxes(
            self,
            src_img: np.ndarray,
            *,
            active_region: str = "",
    ) -> list[OverlayBox]:
        boxes: list[OverlayBox] = []
        for name, rate in _SKIP_SCAN_ROIS:
            color = (0, 255, 255) if name == active_region else (0, 180, 180)
            boxes.append(self._roi_overlay_box(
                src_img, rate, f"roi:{name}", color, is_hit=name == active_region))
        boxes.append(self._roi_overlay_box(
            src_img, _DIALOG_ROI_RATE, "roi:dialog", (180, 0, 180), is_hit=False))
        return boxes

    def _find_skip_in_ocr_list(self, ocr_results: list[TextPosition] | None) -> TextPosition | None:
        if not ocr_results:
            return None
        for item in ocr_results:
            if self._match_skip_button(item.text):
                return item
        return None

    def _ocr_dialog(
            self,
            src_img: np.ndarray,
            img: np.ndarray,
    ) -> list[TextPosition]:
        _, mapped = self._ocr_roi(src_img, img, _DIALOG_ROI_RATE)
        return mapped

    def _try_skip_confirm(self, src_img: np.ndarray, img: np.ndarray) -> bool:
        dialog_ocr = self._ocr_dialog(src_img, img)
        body = next((t for t in dialog_ocr if _SKIP_CONFIRM_BODY_RE.search(t.text)), None)
        confirm = next((t for t in dialog_ocr if _CONFIRM_RE.search(t.text)), None)
        dont_show = next((t for t in dialog_ocr if _DONT_SHOW_AGAIN_RE.search(t.text)), None)
        self._update_debug_overlay(
            src_img,
            status=f"skip-confirm body={bool(body)} confirm={bool(confirm)}",
            roi_boxes=self._debug_roi_boxes(src_img),
            ocr_hits=dialog_ocr,
        )
        if body and confirm and dont_show:
            self._control_service.click(*dont_show.center)
            time.sleep(0.1)
            self._control_service.click(*confirm.center)
            time.sleep(0.5)
            return True
        if self.page_action(self._skip_confirm_page, src_img, img, dialog_ocr):
            return True
        return False

    def _try_skip_synopsis(self, src_img: np.ndarray, img: np.ndarray) -> bool:
        dialog_ocr = self._ocr_dialog(src_img, img)
        skip_story = next((t for t in dialog_ocr if _SKIP_STORY_RE.search(t.text)), None)
        self._update_debug_overlay(
            src_img,
            status=f"skip-synopsis hit={bool(skip_story)}",
            roi_boxes=self._debug_roi_boxes(src_img),
            ocr_hits=dialog_ocr,
            skip_hit=skip_story,
        )
        if skip_story is not None:
            self._click_position(skip_story, label="skip-story-th")
            return True
        if self.page_action(self._skip_story_synopsis_page, src_img, img, dialog_ocr):
            return True
        return False

    def _handle_story_skip(self, src_img: np.ndarray, img: np.ndarray) -> bool:
        """Scan all skip ROIs; show every OCR box in debug preview."""
        skip_hit, all_ocr, region = self._find_skip_anywhere(src_img, img)
        self._update_debug_overlay(
            src_img,
            status=f"skip-scan region={region or 'none'} hits={len(all_ocr)}",
            roi_boxes=self._debug_roi_boxes(src_img, active_region=region),
            ocr_hits=all_ocr,
            skip_hit=skip_hit,
        )
        if skip_hit is not None:
            return self._click_position(skip_hit, label=f"skip-{region}")
        return False

    def execute(self, **kwargs):
        if not self._window_service.is_foreground_window():
            time.sleep(0.5)
            if self._mouse_last_check_time is not None:
                self._mouse_last_check_time = time.perf_counter()
            self._control_service.activate()
            return

        start_time = time.perf_counter_ns()
        self._execute()
        use_time = time.perf_counter_ns() - start_time
        if use_time > 0.0:
            logger.debug(f"fps: {(1e9 / use_time)}")
        use_seconds = use_time / 1e9

        if self.skip_is_open:
            # 默认一秒一次，点击了跳过则每秒两次
            fps_lock= 8 if self.skip_btn_is_clicked else 1
        else:
            fps_lock = None
        self._dynamic_fps_limit.sleep(use_seconds, fps_lock=fps_lock)
        use_time = time.perf_counter_ns() - start_time
        if use_time > 0.0:
            logger.debug(f"final fps: {(1e9 / use_time)}")

        return

    @timeit(ignore=3)
    def _execute(self, **kwargs):
        # prepare
        src_img = self._img_service.screenshot()
        img = self._img_service.resize(src_img)
        ocr_results: list[TextPosition] | None = None
        # 定制action，防止卡顿

        auto_npc_interact = False
        # 跳过剧情
        if self.skip_is_open:
            if self._handle_story_skip(src_img, img):
                self.skip_btn_is_clicked = True
                self.skip_btn_is_clicked_start_time = time.time()
                return

            # After clicking skip: confirm dialog / story synopsis (Thai + ZH/EN).
            if time.time() - self.skip_btn_is_clicked_start_time < self.skip_btn_is_clicked_timeout:
                if self._try_skip_confirm(src_img, img):
                    return
                if self._try_skip_synopsis(src_img, img):
                    return
            elif self.skip_btn_is_clicked:
                self.skip_btn_is_clicked = False
                return

            # Legacy top-left skip via page matcher + dialogue advance.
            _, top_left_ocr = self._ocr_roi(src_img, img, _TOP_LEFT_SKIP_ROI_RATE)
            top_left_skip = self._find_skip_in_ocr_list(top_left_ocr)
            if top_left_skip is None:
                skip_match = self._skip_page.get_text_match_by_name("跳过|SKIP")
                matched = self._skip_page.text_match(skip_match, src_img, img, top_left_ocr)
                if isinstance(matched, TextPosition):
                    top_left_skip = matched
            self._update_debug_overlay(
                src_img,
                status="top-left fallback",
                roi_boxes=self._debug_roi_boxes(src_img, active_region="top-left"),
                ocr_hits=top_left_ocr,
                skip_hit=top_left_skip,
            )
            if top_left_skip is not None:
                self._click_position(top_left_skip, label="top-left-skip")
                self.skip_btn_is_clicked = True
                self.skip_btn_is_clicked_start_time = time.time()
                return
            if self.page_action(self._skip_page, src_img, img, top_left_ocr):
                self.skip_btn_is_clicked = True
                self.skip_btn_is_clicked_start_time = time.time()
                return
            self.page_action(self._dialogue_page, src_img, img, top_left_ocr)
            self.page_action(self._dialogue2_page, src_img, img, top_left_ocr)
        else:
            if not self._is_auto_play_enabled:
                # 打开自动播放
                if not self.page_action(self._auto_play_page, src_img, img, ocr_results):
                    self.page_action(self._auto_play2_page, src_img, img, ocr_results)
                time.sleep(0.005)
                # if self.page_action(self._auto_play_open_page, src_img, img, ocr_results):
                #     # self._is_auto_play_enabled = True
                #     pass
                # if self.page_action(self._auto_play_open2_page, src_img, img, ocr_results):
                #     # self._is_auto_play_enabled = True
                #     pass
                time.sleep(0.005)

            # 剧情对话框，不跳过，一句一句自动过剧情
            if self.page_action(self._dialogue_page, src_img, img, ocr_results):
                time.sleep(2)
            elif self.page_action(self._dialogue2_page, src_img, img, ocr_results):
                time.sleep(2)

        # NPC交互框
        if auto_npc_interact:
            self.page_action(self._npc_interact_page, src_img, img, ocr_results)

        if not self.skip_is_open:
            self._set_mouse_position_to_bottom_right()

    @staticmethod
    def page_action(page: Page, src_img: np.ndarray, img: np.ndarray, ocr_results: list[TextPosition]) -> bool:
        if not page.is_match(src_img, img, ocr_results):
            return False
        logger.info("当前页面：%s", page.name)
        page.action(page.matchPositions)
        return True

    def _set_mouse_position_to_bottom_right(self):
        if self._mouse_last_check_time is None:
            listener_thread = threading.Thread(target=self._listen_keys)
            listener_thread.daemon = True  # 设置为守护线程，当主线程退出时该线程自动结束
            listener_thread.start()
            self._listener_thread = listener_thread
            self._mouse_last_check_time = time.perf_counter()
            return
        cur_pos = self._control_service.get_mouse_position()
        x1, y1, x2, y2 = self._window_service.get_client_rect_on_screen()
        w, h = self._window_service.get_client_wh()
        center_rect = w * 256 / 2560 / 2
        if abs(cur_pos[0] - (x2 + x1) // 2) > center_rect or abs(cur_pos[1] - (y2 + y1) // 2) > center_rect:  # 要在窗口中心才行
            self._mouse_last_check_time = time.perf_counter()
            return
        logger.debug("鼠标在正中心")
        cur_time = time.perf_counter()
        if cur_time - self._mouse_last_check_time < self._mouse_idle_time:  # 数秒内未动才行
            logger.debug("鼠标悬停时间不够: %s", cur_time - self._mouse_last_check_time)
            return
        # if self._control_service.get_alt_key_state():  # 没按下alt才行
        #     self._mouse_last_check_time = time.perf_counter()
        #     return
        self._control_service.set_mouse_position_to_bottom_right()
        self._mouse_last_check_time = time.perf_counter()
        logger.debug("移动鼠标到右下角")

    def _on_press(self, key):
        logger.debug(f"按键 {key} 被按下")
        self._mouse_last_check_time = time.perf_counter()
        self._dynamic_fps_limit.refresh()

    def _listen_keys(self):
        with keyboard.Listener(on_press=self._on_press) as listener:
            listener.join()

    def get_pages(self) -> list[Page]:
        return self._story_pages

    def get_conditional_actions(self) -> list[ConditionalAction]:
        return self._story_conditional_actions

    def _build_story_pages(self):
        def skip_page_action(positions: dict[str, Position]) -> bool:
            time.sleep(0.1)
            position = (
                positions.get("跳过|SKIP")
                or positions.get("ข้าม")
                or next(iter(positions.values()), None)
            )
            if position is None:
                return False
            self._control_service.click(*position.center)
            time.sleep(0.1)
            self._control_service.click(*position.center)
            time.sleep(0.1)
            return True

        skip_page = Page(
            name="左上角跳过|SKIP",
            targetTexts=[
                TextMatch(
                    name="跳过|SKIP",
                    text=_SKIP_BUTTON_RE,
                    open_position=False,
                    position=DynamicPosition(rate=_TOP_LEFT_SKIP_ROI_RATE),
                ),
            ],
            action=skip_page_action,
        )
        self._story_pages.append(skip_page)
        self._skip_page = skip_page

        def skip_story_synopsis_action(positions: dict[str, Position]) -> bool:
            time.sleep(0.1)
            position = positions.get("跳过剧情") or positions.get("ข้ามเนื้อเรื่อง")
            if position is None:
                return False
            self._control_service.click(*position.center)
            time.sleep(0.5)
            return True

        skip_story_synopsis_page = Page(
            name="剧情梗概|Summary",
            targetTexts=[
                TextMatch(
                    name="继续观看",
                    text=_RESUME_RE,
                ),
                TextMatch(
                    name="跳过剧情",
                    text=_SKIP_STORY_RE,
                ),
            ],
            action=skip_story_synopsis_action,
        )
        self._story_pages.append(skip_story_synopsis_page)
        self._skip_story_synopsis_page = skip_story_synopsis_page

        def skip_confirm_page_action(positions: dict[str, Position]) -> bool:
            dont_notice_again_position = (
                positions.get("本次登录不再提示")
                or positions.get("ไม่แสดงอีก")
            )
            confirm_position = positions.get("确认") or positions.get("ยืนยัน")
            if dont_notice_again_position is None or confirm_position is None:
                return False
            self._control_service.click(*dont_notice_again_position.center)
            time.sleep(0.1)
            self._control_service.click(*confirm_position.center)
            time.sleep(0.5)
            return True

        skip_confirm_page = Page(
            name="是否确认跳过|SkipConfirm",
            targetTexts=[
                TextMatch(
                    name="完整观看剧情",
                    text=_SKIP_CONFIRM_BODY_RE,
                ),
                TextMatch(
                    name="确认",
                    text=_CONFIRM_RE,
                ),
                TextMatch(
                    name="本次登录不再提示",
                    text=_DONT_SHOW_AGAIN_RE,
                ),
            ],
            action=skip_confirm_page_action,
        )
        self._story_pages.append(skip_confirm_page)
        self._skip_confirm_page = skip_confirm_page

        def auto_play_page_action(positions: dict[str, Position]) -> bool:
            position = positions.get("自动播放|AutoPlay")
            time.sleep(1.2)
            self._control_service.click(*position.center)
            time.sleep(0.2)
            return True

        auto_play_page = Page(
            name="自动播放|AutoPlay",
            screenshot={
                Language.ZH: [
                    "Dialogue_001.png",
                ],
                Language.EN: [
                ],
            },
            targetImages=[
                ImageMatch(
                    name="自动播放|AutoPlay",
                    image="AutoPlay.png",
                    position=DynamicPosition(
                        rate=(
                            1070 / 1280,
                            0.0,
                            1.0,
                            90 / 720
                        ),
                    ),
                    open_roi_cache=True,
                    confidence=0.8,
                ),
            ],
            action=auto_play_page_action,
        )

        auto_play_2_page = Page(
            name="自动播放|AutoPlay-2",  # 电影黑边
            screenshot={
                Language.ZH: [
                    "Dialogue_001.png",
                ],
                Language.EN: [
                ],
            },
            targetImages=[
                ImageMatch(
                    name="自动播放|AutoPlay",
                    image="AutoPlay2.png",
                    position=DynamicPosition(
                        rate=(
                            1070 / 1280,
                            0.0,
                            1.0,
                            150 / 720
                        ),
                    ),
                    open_roi_cache=True,
                    confidence=0.8,
                ),
            ],
            action=auto_play_page_action,
        )

        self._story_pages.append(auto_play_page)
        self._story_pages.append(auto_play_2_page)
        self._auto_play_page = auto_play_page
        self._auto_play2_page = auto_play_2_page

        def auto_play_open_page_action(positions: dict[str, Position]) -> bool:
            return True

        auto_play_open_page = Page(
            name="自动播放已开启|AutoPlayEnabled",
            screenshot={
                Language.ZH: [
                    "",
                ],
                Language.EN: [
                ],
            },
            targetImages=[
                ImageMatch(
                    name="自动播放已开启|AutoPlayEnabled",
                    image="AutoPlayEnabled.png",
                    position=DynamicPosition(
                        rate=(
                            1070 / 1280,
                            0.0,
                            1.0,
                            150 / 720
                        ),
                    ),
                    open_roi_cache=False,
                    confidence=0.8,
                ),
            ],
            action=auto_play_open_page_action,
        )

        auto_play_open2_page = Page(
            name="自动播放已开启|AutoPlayEnabled-2",  # 电影黑边
            screenshot={
                Language.ZH: [
                    "",
                ],
                Language.EN: [
                ],
            },
            targetImages=[
                ImageMatch(
                    name="自动播放已开启|AutoPlayEnabled",
                    image="AutoPlayEnabled2.png",
                    position=DynamicPosition(
                        rate=(
                            1070 / 1280,
                            0.0,
                            1.0,
                            150 / 720
                        ),
                    ),
                    open_roi_cache=False,
                    confidence=0.8,
                ),
            ],
            action=auto_play_open_page_action,
        )

        self._story_pages.append(auto_play_open_page)
        self._story_pages.append(auto_play_open2_page)
        self._auto_play_open_page = auto_play_open_page
        self._auto_play_open2_page = auto_play_open2_page

        def dialogue_page_action(positions: dict[str, Position]) -> bool:
            if not self.skip_is_open:
                time.sleep(0.5)
                self._control_service.set_mouse_position_to_bottom_right()
                time.sleep(1.5)
            self._control_service.pick_up()
            time.sleep(0.1)
            return True

        dialogue_page = Page(
            name="对话框|Dialogue",
            screenshot={
                Language.ZH: [
                    "Dialogue_001.png",
                ],
                Language.EN: [
                ],
            },
            targetImages=[
                ImageMatch(
                    name="Dialogue",
                    image="Dialogue.png",
                    position=DynamicPosition(
                        rate=(
                            768 / 1280,
                            275 / 720,
                            975 / 1280,
                            560 / 720,
                        ),
                    ),
                    open_roi_cache=False,
                ),
            ],
            action=dialogue_page_action,
        )

        dialogue2_page = Page(
            name="对话框|Dialogue-2",  # 电影黑边
            screenshot={
                Language.ZH: [
                    "Dialogue_001.png",
                ],
                Language.EN: [
                ],
            },
            targetImages=[
                ImageMatch(
                    name="Dialogue",
                    image="Dialogue2.png",
                    position=DynamicPosition(
                        rate=(
                            768 / 1280,
                            275 / 720,
                            1060 / 1280,
                            600 / 720,
                        ),
                    ),
                    open_roi_cache=False,
                ),
            ],
            action=dialogue_page_action,
        )

        self._story_pages.append(dialogue_page)
        self._story_pages.append(dialogue2_page)
        self._dialogue_page = dialogue_page
        self._dialogue2_page = dialogue2_page

        def npc_interact_action(positions: dict[str, Position]) -> bool:
            time.sleep(0.5)
            self._control_service.pick_up()
            time.sleep(0.1)
            return True

        npc_interact_page = Page(
            name="NPC交互框|NpcInteract",
            targetImages=[
                ImageMatch(
                    name="NpcInteract",
                    image="NpcInteract.png",
                    position=DynamicPosition(
                        rate=(
                            768 / 1280,
                            275 / 720,
                            1.0,
                            600 / 720,
                        ),
                    ),
                    open_roi_cache=False,
                ),
            ],
            action=npc_interact_action,
        )
        self._story_pages.append(npc_interact_page)
        self._npc_interact_page = npc_interact_page

        # def blank_area_action(positions: dict[str, Position]) -> bool:
        #     position = positions.get("点击空白处关闭")
        #     self._control_service.click(*position.center)
        #     time.sleep(0.1)
        #     return True
        #
        # blank_area_page = Page(
        #     name="点击空白处关闭",
        #     targetTexts=[
        #         TextMatch(
        #             name="点击空白处关闭",
        #             text="点击空白处关闭",
        #         ),
        #     ],
        #     action=blank_area_action,
        # )
        # self._story_pages.append(blank_area_page)
        # self._blank_area_page = blank_area_page
