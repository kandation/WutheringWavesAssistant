"""Resolve display language for GUI labels backed by core I18nText."""

import logging

from src.core.i18n import I18nText, I18nTr, Language
from src.gui.common.boss import BossNameEnum
from src.gui.common.config import Language as GuiLanguage, cfg, paramConfig

logger = logging.getLogger(__name__)

# Languages with OCR regex / page matchers in core i18n data.
OCR_SUPPORTED_LANGUAGES = frozenset({Language.ZH, Language.EN})

_BOSS_I18N_KEY_OVERRIDES: dict[str, str] = {
    "ThousandPuppetPavilion": I18nText.WeeklyBossThousandPuppetPavilion,
    "CourtOfShackledSouls": I18nText.CourtOfShackledSouls,
}

_LIMITED_TIME_BOSS_KEYS: dict[str, str] = {
    "NightmareAdamSmasherLimitedTime": I18nText.EnemyNightmareAdamSmasher,
    "MyriadSnareRustfireChassisLimitedTime": I18nText.EnemyMyriadSnareRustfireChassis,
}

_LIMITED_TIME_SUFFIX_EN = " (Limited Time Early Access)"


def _boss_i18n_key(boss: BossNameEnum) -> str:
    if boss.name in _LIMITED_TIME_BOSS_KEYS:
        return _LIMITED_TIME_BOSS_KEYS[boss.name]
    override = _BOSS_I18N_KEY_OVERRIDES.get(boss.name)
    if override:
        return override
    return f"Enemy{boss.name}"


def boss_display_name(boss: BossNameEnum) -> str:
    """Show English boss names when GUI is Thai; Chinese otherwise (OCR/config unchanged)."""
    if cfg.get(cfg.language) != GuiLanguage.THAI:
        return boss.value

    key = _boss_i18n_key(boss)
    label = I18nTr(Language.EN)(key)
    if label is None:
        return boss.name
    text = label.raw
    if "限时" in boss.value:
        text += _LIMITED_TIME_SUFFIX_EN
    return text


def resolve_game_language() -> Language:
    """Game text language for OCR / i18n matching (from 游戏文本 setting, not GUI language)."""
    game_language = paramConfig.get(paramConfig.gameLanguage)
    if game_language:
        try:
            lang = Language(game_language)
            if lang not in OCR_SUPPORTED_LANGUAGES:
                logger.warning(
                    "Game language '%s' is not supported for OCR (use zh-CN or en); falling back to zh-CN",
                    lang.value,
                )
                return Language.ZH
            return lang
        except ValueError:
            logger.warning("Invalid game language setting: '%s'; falling back to zh-CN", game_language)
    return Language.ZH


def resolve_display_language() -> Language:
    """Pick I18nTr language for game-content dropdown labels (GUI only, not OCR)."""
    gui_lang = cfg.get(cfg.language)
    if gui_lang == GuiLanguage.THAI:
        return Language.TH

    return resolve_game_language()
