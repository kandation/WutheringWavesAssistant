"""Resolve display language for GUI labels backed by core I18nText."""

from src.core.i18n import Language
from src.gui.common.config import Language as GuiLanguage, cfg, paramConfig


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
