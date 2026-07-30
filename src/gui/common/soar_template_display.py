"""Display names for Soar to the Beat macro templates (filenames on disk unchanged)."""

from __future__ import annotations

from src.gui.common.config import Language as GuiLanguage, cfg

SOAR_PRESET_TEMPLATES: tuple[str, ...] = (
    "02_星云漫游_《论灵魂De Anima》_困难.txt",
    "02_星云漫游_《论灵魂De Anima》_普通.txt",
    "03_星云漫游_《万千星语》_困难.txt",
    "03_星云漫游_《万千星语》_普通.txt",
    "04_星云漫游_《此刻寻光星间》_困难.txt",
    "04_星云漫游_《此刻寻光星间》_普通.txt",
    "05_星云漫游_《致那暖明黄金》_困难.txt",
    "05_星云漫游_《致那暖明黄金》_普通.txt",
    "06_行星探索_《悠忽舞于梦中》_困难.txt",
    "06_行星探索_《悠忽舞于梦中》_普通.txt",
    "07_行星探索_《愿戴荣光坠入天渊》_普通.txt",
    "08_行星探索_《Daisy Crown》_普通.txt",
    "09_行星探索_《逐光筑昼》_普通.txt",
    "10_恒星冒险_《光耀诸天群海》_普通.txt",
    "11_恒星冒险_《于无羁之昼点亮真彩(Throttle Up!)》_普通.txt",
    "12_恒星冒险_《烈阳啊，请见我真名》_普通.txt",
    "13_恒星冒险_《死秽失乐福音》_普通.txt",
    "14_Musedash_《雨后甜点》_普通.txt",
    "15_Musedash_《Final Step！》_普通.txt",
    "16_Musedash_《Cthugha》_普通.txt",
)

SOAR_TEMPLATE_DISPLAY_EN: dict[str, str] = {
    "02_星云漫游_《论灵魂De Anima》_困难.txt": "Nebulas Walk - De Anima (Hard)",
    "02_星云漫游_《论灵魂De Anima》_普通.txt": "Nebulas Walk - De Anima (Normal)",
    "03_星云漫游_《万千星语》_困难.txt": "Nebulas Walk - Whispers of Stars (Hard)",
    "03_星云漫游_《万千星语》_普通.txt": "Nebulas Walk - Whispers of Stars (Normal)",
    "04_星云漫游_《此刻寻光星间》_困难.txt": "Nebulas Walk - Moments Captured Among Stars (Hard)",
    "04_星云漫游_《此刻寻光星间》_普通.txt": "Nebulas Walk - Moments Captured Among Stars (Normal)",
    "05_星云漫游_《致那暖明黄金》_困难.txt": "Nebulas Walk - To Bright Warm Gold (Hard)",
    "05_星云漫游_《致那暖明黄金》_普通.txt": "Nebulas Walk - To Bright Warm Gold (Normal)",
    "06_行星探索_《悠忽舞于梦中》_困难.txt": "Planet Tales - Dancing Through Fantasies (Hard)",
    "06_行星探索_《悠忽舞于梦中》_普通.txt": "Planet Tales - Dancing Through Fantasies (Normal)",
    "07_行星探索_《愿戴荣光坠入天渊》_普通.txt": "Planet Tales - With Glory I Shall Fall (Normal)",
    "08_行星探索_《Daisy Crown》_普通.txt": "Planet Tales - Daisy Crown (Normal)",
    "09_行星探索_《逐光筑昼》_普通.txt": "Planet Tales - Till Dawn (Normal)",
    "10_恒星冒险_《光耀诸天群海》_普通.txt": "Star Frontier - Radiance Across Sea and Sky (Normal)",
    "11_恒星冒险_《于无羁之昼点亮真彩(Throttle Up!)》_普通.txt": "Star Frontier - A Splash of True Colors (Throttle Up!) (Normal)",
    "12_恒星冒险_《烈阳啊，请见我真名》_普通.txt": "Star Frontier - O Sun, Witness My Name (Normal)",
    "13_恒星冒险_《死秽失乐福音》_普通.txt": "Star Frontier - The Sound of Lost Joy (Normal)",
    "14_Musedash_《雨后甜点》_普通.txt": "Muse Dash - Drizzle & Dolce (Normal)",
    "15_Musedash_《Final Step！》_普通.txt": "Muse Dash - Final Step! (Normal)",
    "16_Musedash_《Cthugha》_普通.txt": "Muse Dash - Cthugha (Normal)",
}

_DIFFICULTY_ORDER = {"简单": 0, "普通": 1, "困难": 2}
_DIFFICULTY_EN = {"简单": "Easy", "普通": "Normal", "困难": "Hard"}
_CATEGORY_EN = {
    "星云漫游": "Nebulas Walk",
    "行星探索": "Planet Tales",
    "恒星冒险": "Star Frontier",
    "Musedash": "Muse Dash",
}


def soar_template_sort_key(filename: str) -> tuple[int, int]:
    num = int(filename[:2])
    parts = filename[:-4].split("_")
    difficulty = parts[-1]
    return num, _DIFFICULTY_ORDER.get(difficulty, 9)


def get_soar_preset_templates() -> list[str]:
    templates = list(SOAR_PRESET_TEMPLATES)
    templates.sort(key=soar_template_sort_key)
    return templates


def soar_template_display_name(filename: str) -> str:
    """Show English labels when GUI language is Thai; keep filename otherwise."""
    if cfg.get(cfg.language) != GuiLanguage.THAI:
        return filename
    mapped = SOAR_TEMPLATE_DISPLAY_EN.get(filename)
    if mapped:
        return mapped
    return _fallback_display_name(filename)


def _fallback_display_name(filename: str) -> str:
    if not filename.endswith(".txt"):
        return filename
    stem = filename[:-4]
    parts = stem.split("_")
    if len(parts) < 3:
        return filename
    category = _CATEGORY_EN.get(parts[1], parts[1])
    song = parts[2].strip("《》")
    difficulty = _DIFFICULTY_EN.get(parts[-1], parts[-1])
    return f"{category} - {song} ({difficulty})"


def populate_soar_template_combo(combo, filenames: list[str], selected: str | None = None) -> None:
    combo.blockSignals(True)
    combo.clear()
    for filename in filenames:
        combo.addItem(soar_template_display_name(filename), userData=filename)
    if selected:
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else -1)
    combo.blockSignals(False)
