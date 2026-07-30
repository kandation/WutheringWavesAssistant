"""Merge Thai (th) OCR regex entries into core i18n data at import time.

UI menus/buttons use Thai in-game text. Character, boss, and many item names
stay English in the Thai client and fall back to EN via I18nTr.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from src.core.i18n import I18nText, Language, RegexStr, flex_ws
from src.core.i18n_th_display import TH_CORE_DISPLAY

# Keys that should use English OCR patterns in the Thai client.
_EN_ONLY_KEYS = frozenset({
    I18nText.WutheringWaves,
    # Resonators
    I18nText.Rover, I18nText.Encore, I18nText.Verina, I18nText.Calcharo, I18nText.Lingyang,
    I18nText.Jianxin, I18nText.Yangyang, I18nText.Baizhi, I18nText.Chixia, I18nText.Sanhua,
    I18nText.Aalto, I18nText.Danjin, I18nText.Mortefi, I18nText.Yuanwu, I18nText.Taoqi,
    I18nText.Jiyan, I18nText.Yinlin, I18nText.Jinhsi, I18nText.Changli, I18nText.Zhezhi,
    I18nText.XiangliYao, I18nText.Shorekeeper, I18nText.Youhu, I18nText.Camellya,
    I18nText.Lumi, I18nText.Carlotta, I18nText.Roccia, I18nText.Phoebe, I18nText.Brant,
    I18nText.Cantarella, I18nText.Zanni, I18nText.Ciaccona, I18nText.Cartethyia,
    I18nText.Lupa, I18nText.Phrolova, I18nText.Augusta, I18nText.Iuno, I18nText.Galbrena,
    I18nText.Qiuyuan, I18nText.Chisa, I18nText.Buling, I18nText.Lynae, I18nText.Mornye,
    I18nText.Aemeath, I18nText.LuukHerssen, I18nText.Sigrika, I18nText.Hiyuki,
    I18nText.Denia, I18nText.Lucy, I18nText.Rebecca, I18nText.Lucilla,
    I18nText.YangyangXuanling, I18nText.Suisui, I18nText.Suoming, I18nText.Jingran,
    I18nText.Qingxiao, I18nText.Hsin,
    # Enemy tracing (boss names stay English in Thai client)
    I18nText.EnemyDreamless, I18nText.EnemyFallacyOfNoReturn, I18nText.EnemyLampylumenMyriad,
    I18nText.EnemyBellBorneGeochelone, I18nText.EnemyInfernoRider,
    I18nText.EnemyImpermanenceHeron, I18nText.EnemyMechAbomination, I18nText.EnemyMourningAix,
    I18nText.EnemyThunderingMephis, I18nText.EnemyTempestMephis, I18nText.EnemyFeilianBeringal,
    I18nText.EnemyCrownless, I18nText.EnemyJue, I18nText.EnemySentryConstruct,
    I18nText.EnemyHecate, I18nText.EnemyLorelei, I18nText.EnemyDragonOfDirge,
    I18nText.EnemyNightmareFeilianBeringal, I18nText.EnemyNightmareImpermanenceHeron,
    I18nText.EnemyNightmareTempestMephis, I18nText.EnemyNightmareThunderingMephis,
    I18nText.EnemyNightmareCrownless, I18nText.EnemyNightmareInfernoRider,
    I18nText.EnemyNightmareMourningAix, I18nText.EnemyNightmareLampylumenMyriad,
    I18nText.EnemyFleurdelys, I18nText.EnemyNightmareKelpie, I18nText.EnemyLionessOfGlory,
    I18nText.EnemyNightmareHecate, I18nText.EnemyFenrico, I18nText.EnemyLadyOfTheSea,
    I18nText.EnemyTheFalseSovereign, I18nText.EnemyThrenodianLeviathan, I18nText.EnemyHyvatia,
    I18nText.EnemyReactorHusk, I18nText.EnemySigillum, I18nText.EnemyNamelessExplorer,
    I18nText.EnemyDenia, I18nText.EnemyMyriadSnareRustfireChassis,
    I18nText.EnemyNightmareAdamSmasher,
    # Combat view – boss name fragments stay English
    I18nText.ViewFight,
})

# Thai UI text keyed by I18nText constant value.
UI_TH_BY_KEY: dict[str, str | tuple[str, bool]] = {
  # (text, partial_match) – partial=True allows substring / line-wrap matching
    I18nText.Login: ("เข้าสู่ระบบ", False),
    I18nText.FastTravel: ("เดินทางด่วน", False),
    I18nText.EnableNavigation: ("เปิดการนำทาง", False),
    I18nText.SwitchMap: ("สลับแผนที่", False),
    I18nText.Huanglong: ("Huanglong", True),
    I18nText.Jinzhou: ("Jinzhou", True),
    I18nText.JinzhouCity: ("Jinzhou", True),
    I18nText.Mengzhou: ("Mengzhou", True),
    I18nText.TheBlackShores: ("The Black Shores", True),
    I18nText.Rinascita: ("Rinascita", True),
    I18nText.RoyaFrostlands: ("Roya Frostlands", True),
    I18nText.Confirm: ("ยืนยัน", False),
    I18nText.Restart: ("เริ่มใหม่", False),
    I18nText.Exit: ("ออก", False),
    I18nText.CollectSupplies: ("เก็บเสบียง", False),
    I18nText.ItemsObtained: ("ได้รับไอเทม", False),
    I18nText.TapTheBlankAreaToClose: ("แตะพื้นที่ว่างเพื่อปิด", True),
    I18nText.SelectARevivalItem: ("เลือกไอเทมชุบชีวิต", True),
    I18nText.DoNotShowAgain: ("ไม่แสดงอีกในการเข้าสู่ระบบครั้งนี้", True),
    I18nText.LuniteSubscriptionReward: ("แตะเพื่อรับรางวัลบัตร Lunite", True),
    I18nText.Absorb: ("ดูดซับ", False),
    I18nText.ClaimRewards: ("รับรางวัล", False),
    I18nText.ChallengeAgain: ("ท้าทายอีกครั้ง", False),
    I18nText.Terminal: ("เทอร์มินัล", False),
    I18nText.Birthday: ("วันเกิด", False),
    I18nText.SOL3Phase: ("เลื่อนขั้น SOL3", True),
    I18nText.UnionLevel: ("เลเวลยูเนียน", True),
    I18nText.UnionEXP: ("ค่าประสบการณ์ยูเนียน", True),
    I18nText.Events: ("กิจกรรม", False),
    I18nText.TerminalPioneerPodcast: ("พอดแคสต์", True),
    I18nText.Team: ("ทีม", False),
    I18nText.DataBank: ("คลังข้อมูล", False),
    I18nText.Guidebook: ("คู่มือโซลาริส", False),
    I18nText.Map: ("แผนที่", False),
    I18nText.Mail: ("จดหมาย", False),
    I18nText.PioneerPodcast: ("พอดแคสต์ผู้บุกเบิก", True),
    I18nText.PioneerPodcastUnavailable: ("พอดแคสต์ผู้บุกเบิก", True),
    I18nText.PodcastTasks: ("ภารกิจพอดแคสต์", False),
    I18nText.PioneerPodcastClaimAll: ("รับทั้งหมด", True),
    I18nText.PioneerPodcastConfirm: ("ยืนยัน", False),
    I18nText.TargetedMerge: ("ผสานเจาะจง", False),
    I18nText.StandardMerge: ("ผสานมาตรฐาน", False),
    I18nText.PleaseSelectAtLeast5Echoes: ("กรุณาเลือกอย่างน้อย", True),
    I18nText.DataMergeCount: ("จำนวนการผสานข้อมูล", True),
    I18nText.Activity: ("แถวกิจกรรม", False),
    I18nText.MaterialsSpots: ("จุดฟาร์มวัสดุ", False),
    I18nText.RecurringChallenges: ("ความท้าทายประจำ", True),
    I18nText.PathOfGrowth: ("เส้นทางแห่งการเติบโต", True),
    I18nText.EnemyTracing: ("ติดตามศัตรู", True),
    I18nText.Milestones: ("บันทึกการผจญภัย", True),
    I18nText.CannotPerformThisActionDuringBattle: ("ไม่สามารถทำการกระทำนี้ระหว่างต่อสู้", True),
    I18nText.DoubleDropChancesToday: ("โอกาสดรอปสองเท่าวันนี้", True),
    I18nText.ActivityDaily: ("รายวัน", False),
    I18nText.ActivityWeekly: ("รายสัปดาห์", False),
    I18nText.ActivityPts: ("แต้มกิจกรรม", True),
    I18nText.WeeklyActivityPts: ("แต้มกิจกรรมรายสัปดาห์", True),
    I18nText.ActivityClaim: ("รับ", False),
    I18nText.ForgeryChallenge: ("ความท้าทายการหลอม", False),
    I18nText.SimulationChallenge: ("การท้าทายจำลอง", False),
    I18nText.BossChallenge: ("ท้าทายบอส", False),
    I18nText.TacetSuppression: ("ปราบสนามทาเซ็ต", False),
    I18nText.WeeklyChallenge: ("ท้าทายประจำสัปดาห์", False),
    I18nText.NightmarePurification: ("ชำระล้างฝันร้าย", False),
    I18nText.TacetDiscordNest: ("รังทาเซ็ตดิสคอร์ด", False),
    I18nText.Go: ("ไป", False),
    I18nText.Challenge: ("ท้าทาย", False),
    I18nText.EnterTheForgeryChallenge: ("เข้าสู่ความท้าทายการหลอม", True),
    I18nText.Level: ("เลเวล", True),
    I18nText.Match: ("จับคู่", False),
    I18nText.SoloChallenge: ("ท้าทายเดี่ยว", False),
    I18nText.DefeatTheEnemiesWithinTimeLimit: ("กำจัดศัตรูภายในเวลาที่กำหนด", True),
    I18nText.ForgeryChallengeComplete: ("ท้าทายสำเร็จ", False),
    I18nText.ForgeryClaim: ("รับ", False),
    I18nText.ForgeryClaimX2: ("รับ", True),
    I18nText.ForgeryRestart: ("เริ่มใหม่", False),
    I18nText.ForgeryExit: ("ออก", False),
    I18nText.TacetField: ("สนามทาเซ็ต", True),
    I18nText.EchoSet: ("เซ็ตเอคโค่", True),
    I18nText.DefeatTheTdsInTheTacetField: ("กำจัดทาเซ็ตดิสคอร์ด", True),
    I18nText.TacetFieldChallengeComplete: ("ท้าทายสำเร็จ", False),
    I18nText.TacetFieldClaim: ("รับ", False),
    I18nText.TacetFieldClaimX2: ("รับ", True),
    I18nText.TacetFieldNoticeChallengeComplete: ("ท้าทายสำเร็จ", False),
    I18nText.TacetFieldConfirm: ("ยืนยัน", False),
    I18nText.TacetFieldRestart: ("เริ่มใหม่", False),
    I18nText.TacetFieldExit: ("ออก", False),
    I18nText.WeeklyChallengeWeeklyChallenge: ("ท้าทายประจำสัปดาห์", True),
    I18nText.RemainingWeeklyAttempts: ("จำนวนครั้งที่เหลือ", True),
    I18nText.LimitedTimeEarlyAccess: ("Limited Time", True),
    I18nText.ArrivingAtTheDestination: ("มาถึงจุดหมาย", True),
    I18nText.EnterTheSonoroSphere: ("เข้าสู่ Sonoro Sphere", True),
    I18nText.WeeklySuggestedLv: ("เลเวลแนะนำ", True),
    I18nText.WeeklyRemainingAttempts: ("จำนวนครั้งที่เหลือ", True),
    I18nText.WeeklySoloChallenge: ("ท้าทายเดี่ยว", False),
    I18nText.YourCurrentSol3Phase: ("เลื่อนขั้น SOL3 ปัจจุบัน", True),
    I18nText.WeeklyDefeatTheEnemy: ("กำจัด", True),
    I18nText.WeeklyClaimRewards: ("รับรางวัล", False),
    I18nText.WeeklyConfirm: ("ยืนยัน", False),
    I18nText.WeeklyCancel: ("ยกเลิก", False),
    I18nText.WeeklyRestart: ("เริ่มใหม่", False),
    I18nText.WeeklyExit: ("ออก", False),
    I18nText.YouHaveReachedTheChallengeLimit: ("ถึงขีดจำกัดการท้าทายแล้ว", True),
    I18nText.TacetDiscordNestTacetDiscordNest: ("รังทาเซ็ตดิสคอร์ด", True),
    I18nText.TacetDiscordDefeated: ("กำจัดทาเซ็ตดิสคอร์ดแล้ว", True),
    I18nText.QuickSetup: ("จัดทีมด่วน", True),
    I18nText.Deployed: ("ลงสนามแล้ว", False),
    I18nText.Deploy: ("ลงสนาม", False),
    I18nText.ResonatorDowned: ("เรโซเนเตอร์ล้ม", True),
    I18nText.StartChallenge: ("เริ่มท้าทาย", True),
    I18nText.Mailbox: ("กล่องจดหมาย", True),
    I18nText.MailClaimAll: ("รับทั้งหมด", True),
    I18nText.ClearTheTacetDiscordNest: ("กำจัดทาเซ็ตดิสคอร์ด", True),
    I18nText.TacetDiscordNestCleared: ("กำจัดรังทาเซ็ตดิสคอร์ดแล้ว", True),
    I18nText.ClearTheTacetDiscordNestMengzhou: ("กำจัดทาเซ็ตดิสคอร์ด", True),
    I18nText.TacetDiscordNestClearedMengzhou: ("กำจัดรังทาเซ็ตดิสคอร์ดแล้ว", True),
    I18nText.ViewClaimRewards: ("รับรางวัล", False),
    I18nText.ViewClaimRewardsConfirm: ("ยืนยัน", False),
    I18nText.ViewClaimRewardsCancel: ("ยกเลิก", False),
    I18nText.CrownlessResonanceCord: ("สายเสียงสะท้อน", False),
    I18nText.ViewChallengeComplete: ("ท้าทายสำเร็จ", False),
    I18nText.ViewChallengeFailed: ("ท้าทายล้มเหลว", False),
    I18nText.ViewBreakFree: ("คลิกสลับกันเพื่อหลุดพ้น", True),
    I18nText.ViewLeaveInstanceNote: ("แจ้งเตือน", False),
    I18nText.ViewLeaveInstanceConfirm: ("ยืนยัน", False),
    I18nText.ViewLeaveInstanceRestart: ("เริ่มใหม่", False),
    I18nText.ViewLeaveInstance2Notice: ("แจ้งเตือน", False),
    I18nText.ViewLeaveInstance2Confirm: ("ยืนยัน", False),
    I18nText.ViewLeaveInstance2Cancel: ("ยกเลิก", False),
    I18nText.ViewLeaveInstance2Restart: ("เริ่มใหม่", False),
    I18nText.ViewLeaveInstance2Leave: ("ออก", True),
    I18nText.ViewForgeryChallengeExit: ("ออก", False),
    I18nText.ViewForgeryChallengeRestart: ("เริ่มใหม่", False),
    I18nText.ViewTacetSuppressionChallengeComplete: ("ท้าทายสำเร็จ", False),
    I18nText.ViewTacetSuppressionConfirm: ("ยืนยัน", False),
    I18nText.ViewTacetSuppressionExit: ("ออก", False),
    I18nText.ViewTacetSuppressionCancel: ("ยกเลิก", False),
    I18nText.ViewTacetSuppressionRestart: ("เริ่มใหม่", False),
    I18nText.ViewTacetSuppressionClaimRewards: ("รับรางวัล", False),
    I18nText.ViewTacetSuppressionClaim: ("รับ", False),
    I18nText.ViewTacetSuppressionClaimX2: ("รับ", True),
}

# Regex pattern replacements for I18N_PAGES (EN literal -> TH literal in regex)
_PAGE_REGEX_TH: dict[str, str] = {
    r"^Events$": r"^กิจกรรม$",
    r"^S[O0]L3 Phase$": r"^เลื่อนขั้น SOL3",
    r"^Union Level$": r"^เลเวลยูเนียน$",
    r"^Union EXP$": r"^ค่าประสบการณ์ยูเนียน$",
    r"Tap to claim today|Lunite Subscription reward": r"แตะเพื่อรับรางวัลบัตร Lunite",
    r"^Claim Rewards$": r"^รับรางวัล$",
    r"^Confirm$": r"^ยืนยัน$",
    r"^Cancel$": r"^ยกเลิก$",
    r"^Resonance Cord$": r"^สายเสียงสะท้อน$",
    r"^QuickSetup$": r"^จัดทีมด่วน",
    r"^StartChallenge$": r"^เริ่มท้าทาย$",
    r"^Absorb$": r"^ดูดซับ$",
    r"^Click alternately to break free$": r"^คลิกสลับกันเพื่อหลุดพ้น$",
    r"^BREACH TIME REMAINING": r"^เวลาแฮ็กที่เหลือ",
    r"^Note$": r"^แจ้งเตือน$",
    r"^Restart$": r"^เริ่มใหม่$",
    r"^(Cancel|Restart)$": r"^(ยกเลิก|เริ่มใหม่)$",
    r"Leave": r"ออก",
    r"^(Challenge Complete|Challenge Failed)$": r"^(ท้าทายสำเร็จ|ท้าทายล้มเหลว)$",
    r"^Exit$": r"^ออก$",
    r"^Tap to land in Solaris*": r"^Tap to land in Solaris*",
    r"^(Exit|Notice|Repair)$": r"^(ออก|ประกาศ|ซ่อมแซม)$",
    r"^Login$": r"^เข้าสู่ระบบ$",
    r"^Terminal$": r"^เทอร์มินัล$",
    r"^Team$": r"^ทีม$",
    r"^Data Bank$": r"^คลังข้อมูล$",
    r"^Data Bank Info$": r"^ข้อมูลคลังข้อมูล$",
    r"^Rewards$": r"^รางวัล$",
    r"Targeted Merge$": r"ผสานเจาะจง$",
    r"Standard Merge$": r"ผสานมาตรฐาน$",
    r"^Select All": r"^เลือกทั้งหมด",
    r"^Notice$": r"^แจ้งเตือน$",
    r"High Rarity": r"ความหายากสูง",
    r"Do not show again": r"ไม่แสดงอีก",
    r"New Echo": r"เอคโค่ใหม่",
    r"^Forgery Challenge$": r"^ความท้าทายการหลอม$",
    r"^Simulation Challenge$": r"^การท้าทายจำลอง$",
    r"^Boss Challenge$": r"^ท้าทายบอส$",
    r"^Tacet Suppression$": r"^ปราบสนามทาเซ็ต$",
    r"^Weekly Challenge$": r"^ท้าทายประจำสัปดาห์$",
    r"^Nightmare Purification$": r"^ชำระล้างฝันร้าย$",
    r"^Tacet Discord Nest$": r"^รังทาเซ็ตดิสคอร์ด$",
}


def _th_regex(text: str, *, partial: bool = False, exact: bool = True) -> RegexStr:
    escaped = re.escape(text)
    if exact and not partial:
        pattern = flex_ws(f"^{escaped}$")
    elif partial:
        pattern = flex_ws(escaped)
    else:
        pattern = flex_ws(f"^{escaped}")
    return RegexStr(pattern, raw=text)


def _build_th_text_entry(key: str, lang_map: dict) -> RegexStr | str | None:
    if key in _EN_ONLY_KEYS:
        en_val = lang_map.get(Language.EN)
        return copy.deepcopy(en_val) if en_val is not None else None

    if key in TH_CORE_DISPLAY:
        return _th_regex(TH_CORE_DISPLAY[key], partial=True)

    ui = UI_TH_BY_KEY.get(key)
    if ui:
        text, partial = ui if isinstance(ui, tuple) else (ui, False)
        return _th_regex(text, partial=partial, exact=not partial)

    return None


def merge_th_i18n_text(i18n_text: dict) -> None:
    """Inject Language.TH entries into I18N_TEXT."""
    for key, lang_map in i18n_text.items():
        if Language.TH in lang_map:
            continue
        th_val = _build_th_text_entry(key, lang_map)
        if th_val is not None:
            lang_map[Language.TH] = th_val


def _translate_page_value(value: Any) -> Any:
    if isinstance(value, str):
        for en_pat, th_pat in _PAGE_REGEX_TH.items():
            if en_pat in value:
                return value.replace(en_pat, th_pat)
        return value
    if isinstance(value, dict):
        return {k: _translate_page_value(v) for k, v in value.items()}
    return value


def _clone_lang_pages(pages: dict, source: Language, target: Language) -> None:
    for _page_key, lang_pages in pages.items():
        if source not in lang_pages or target in lang_pages:
            continue
        lang_pages[target] = _translate_page_value(copy.deepcopy(lang_pages[source]))


def _clone_lang_views(pages_boss: dict, source: Language, target: Language) -> None:
    for _view_key, lang_views in pages_boss.items():
        if source not in lang_views or target in lang_views:
            continue
        lang_views[target] = copy.deepcopy(lang_views[source])


def merge_th_pages(
    i18n_pages: dict,
    i18n_pages_echo_merge: dict,
    i18n_pages_guidebook: dict,
    i18n_pages_boss: dict,
) -> None:
    """Inject Language.TH page/view definitions derived from EN."""
    _clone_lang_pages(i18n_pages, Language.EN, Language.TH)
    _clone_lang_pages(i18n_pages_echo_merge, Language.EN, Language.TH)
    _clone_lang_pages(i18n_pages_guidebook, Language.EN, Language.TH)
    _clone_lang_views(i18n_pages_boss, Language.EN, Language.TH)
