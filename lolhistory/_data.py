"""共享常量与工具函数。"""

import re
from datetime import datetime

# ── 队列ID → 名称 ─────────────────────────────────────────────────────────

QUEUE_NAMES: dict[int, str] = {
    0: "Custom",           2: "Normal Blind",     4: "Ranked Solo (Legacy)",
    6: "Ranked Premade",   7: "Co-op vs AI",      8: "Normal Draft",
    9: "Ranked Flex",      14: "Normal Draft",     16: "Dominion Blind",
    17: "Dominion Draft",  25: "Co-op vs AI",      31: "Co-op vs AI (Intro)",
    32: "Co-op vs AI",     33: "Co-op vs AI",      41: "Ranked Team",
    42: "Ranked Team",     52: "Co-op vs AI",      61: "Team Builder",
    65: "ARAM",            67: "ARAM (Legacy)",    70: "One For All",
    72: "Snowdown",        73: "Hexakill",         75: "Hexakill",
    76: "URF",             78: "Mirror Mode",      83: "Co-op vs AI (URF)",
    91: "Doom Bots",       92: "Doom Bots",        93: "Doom Bots",
    96: "Ascension",       98: "Hexakill (TT)",    100: "ARAM",
    300: "Poro King",      310: "Nemesis Draft",   313: "Black Market",
    315: "Nexus Siege",    317: "Def Not Dominion",318: "ARURF",
    325: "All Random",     400: "Normal Draft",    410: "Ranked Dynamic",
    420: "Ranked Solo",    430: "Normal Blind",    440: "Ranked Flex",
    450: "ARAM",           460: "Normal Blind (TT)",470: "Ranked Flex (TT)",
    490: "Quickplay",      600: "Blood Hunt",      610: "Dark Star",
    700: "Clash",          720: "ARAM Clash",      800: "Co-op vs AI",
    810: "Co-op vs AI",    820: "Co-op vs AI",     830: "Co-op vs AI",
    840: "Co-op vs AI",    850: "Co-op vs AI",     900: "URF",
    910: "Ascension",      920: "Poro King",       940: "Nexus Siege",
    950: "Doom Bots",      960: "Doom Bots",       980: "Star Guardian",
    990: "PROJECT:Hunters",1000: "Overcharge",     1010: "Snow ARURF",
    1020: "One For All",   1030: "Odyssey:Intro",  1040: "Odyssey:Cadet",
    1050: "Odyssey:Crew",  1060: "Odyssey:Captain",1070: "Odyssey:Onslaught",
    1090: "TFT (Normal)",  1100: "Ranked TFT",     1110: "TFT Tutorial",
    1111: "TFT Test",      1130: "TFT Hyper Roll", 1150: "TFT Double Up",
    1160: "TFT (Normal)",  1170: "TFT Fortune",    1200: "Nexus Blitz",
    1300: "Spellbook",     1400: "Ultimate Spellbook",1700: "Arena",
    1710: "Arena (Ranked)",1810: "Swarm (Tutorial)",1820: "Swarm",
    1830: "Swarm (Story)", 1840: "Swarm (Hard)",   1900: "URF (Pick)",
    2000: "Tutorial 1",    2010: "Tutorial 2",     2020: "Tutorial 3",
}

# ── 地图ID → 名称 ──────────────────────────────────────────────────────────

MAP_NAMES: dict[int, str] = {
    1: "Summoner's Rift (Original)", 2: "Summoner's Rift (Autumn)",
    3: "The Proving Grounds",        4: "Twisted Treeline (Original)",
    8: "The Crystal Scar",          10: "Twisted Treeline",
    11: "Summoner's Rift",          12: "Howling Abyss",
    14: "Butcher's Bridge",         16: "Cosmic Ruins",
    18: "Valoran City Park",        19: "Substructure 43",
    20: "Crash Site",               21: "Nexus Blitz",
    22: "Convergence",              30: "Evolved Summoner's Rift",
    33: "Noxus Rift",
}

TFT_QUEUE_IDS = {1090, 1100, 1110, 1111, 1130, 1150, 1160, 1170}

# ── WeGame API 段位数值 → 中文名 ───────────────────────────────────────────
# 与 _analysis.py 中 _WEGAME_TIER_MAP 对齐（1=钻石, 6=超凡大师）
# WeGame 编号方向与 Riot 不同：数值越小段位越高（非大师段位），
# 大师及以上从 6 开始递增

WEGAME_TIER_NAMES: dict[int, str] = {
    0: "未定级",
    1: "钻石",
    2: "翡翠",
    3: "铂金",
    4: "黄金",
    5: "白银",
    6: "超凡大师",
    7: "傲世宗师",
    8: "最强王者",
}

# ── 工具函数 ──────────────────────────────────────────────────────────────

def get_wegame_tier_name(tier: int) -> str:
    """WeGame API 返回的段位数值 → 中文显示名。"""
    return WEGAME_TIER_NAMES.get(tier, f"段位{tier}")


def get_queue_name(qid: int) -> str:
    """根据队列ID返回对局类型名称。"""
    return QUEUE_NAMES.get(qid, f"Unknown({qid})")


def get_map_name(mid: int) -> str:
    """根据地图ID返回地图名称。"""
    return MAP_NAMES.get(mid, f"Unknown({mid})")


def format_duration(seconds: int) -> str:
    """格式化秒数为 m:ss 格式。"""
    if seconds < 0:
        seconds = 0
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def calculate_kda(kills: int, deaths: int, assists: int) -> float:
    """计算KDA比率：(击杀+助攻)/死亡（死亡为0时按1计）。"""
    return round((kills + assists) / max(deaths, 1), 2)


def sanitize_filename(name: str) -> str:
    """清理字符串使其可用作文件名。"""
    return re.sub(r'[<>:"/\\|?*\' ]', '_', name).strip('_')


def parse_game_creation(epoch_ms: int) -> datetime:
    """将毫秒时间戳转换为 datetime 对象。"""
    return datetime.fromtimestamp(epoch_ms / 1000.0)
