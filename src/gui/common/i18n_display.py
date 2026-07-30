"""Resolve display language for GUI labels backed by core I18nText."""

from src.core.i18n import I18nText, I18nTr, Language
from src.gui.common.boss import BossNameEnum
from src.gui.common.config import Language as GuiLanguage, cfg, paramConfig

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


def resolve_display_language() -> Language:
    """Pick language for dropdown labels: GUI Thai first, then game language, else ZH."""
    gui_lang = cfg.get(cfg.language)
    if gui_lang == GuiLanguage.THAI:
        return Language.TH

    game_language = paramConfig.get(paramConfig.gameLanguage)
    if game_language:
        try:
            return Language(game_language)
        except ValueError:
            pass

    return Language.ZH
