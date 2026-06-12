"""共享常量与工具函数。"""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

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

# ── 赛季 SID → 中文名称映射 ──────────────────────────────────────────────
# 来源: WeGame API GetBattleReport season_list 中的 sid 字段
# S2~S8: 每赛季 1 个 SID；S9~S12: 每赛季「季前赛 + 赛季」共 2 SID；
# S13: 季前赛 + 第一/第二赛段 共 3 SID；S14 起: 每赛季 3 个赛段

SEASON_NAMES: dict[int, str] = {
    1: "S2赛季",
    2: "S3赛季",
    3: "S4赛季",
    4: "S5赛季",
    5: "S6赛季",
    6: "S7赛季",
    7: "S8赛季",
    8: "S9季前赛",
    9: "S9赛季",
    10: "S10季前赛",
    11: "S10赛季",
    12: "S11季前赛",
    13: "S11赛季",
    14: "S12季前赛",
    15: "S12赛季",
    16: "S13季前赛",
    17: "S13第一赛段",
    18: "S13第二赛段",
    19: "S14第一赛段",
    20: "S14第二赛段",
    21: "S14第三赛段",
    22: "S15第一赛段",
    23: "S15第二赛段",
    24: "S15第三赛段",
    25: "S16第一赛段",
    26: "S16第二赛段",
    27: "S16第三赛段",
}
# 从 S14 起每赛季 3 个赛段，规律延续至 sid=99
_SPLIT_NAMES = ("第一赛段", "第二赛段", "第三赛段")
_season_base = 14
_sid_base = 19
for _sid in range(28, 100):
    _sn = _season_base + (_sid - _sid_base) // 3
    _si = (_sid - _sid_base) % 3
    SEASON_NAMES[_sid] = f"S{_sn}{_SPLIT_NAMES[_si]}"


def get_season_name(sid: int) -> str:
    """根据赛季 SID 返回中文赛季名称。"""
    return SEASON_NAMES.get(sid, f"S{sid}")


# ── 英雄 ID → 显示名称（从 WeGame 官方配置文件提取，175 个标准英雄 + 20 个末日人机变体） ──
# 来源: wegame-api-export/英雄配置文件LOLChampion.*.js
# 格式: "Ename 中文名"，英雄 ID 与 Riot 官方 champion-summary.json 对齐

CHAMPION_DISPLAY: dict[int, str] = {
    1: "Annie 安妮",
    2: "Olaf 奥拉夫",
    3: "Galio 加里奥",
    4: "TwistedFate 崔斯特",
    5: "XinZhao 赵信",
    6: "Urgot 厄加特",
    7: "Leblanc 乐芙兰",
    8: "Vladimir 弗拉基米尔",
    9: "FiddleSticks 费德提克",
    10: "Kayle 凯尔",
    11: "MasterYi 易",
    12: "Alistar 阿利斯塔",
    13: "Ryze 瑞兹",
    14: "Sion 赛恩",
    15: "Sivir 希维尔",
    16: "Soraka 索拉卡",
    17: "Teemo 提莫",
    18: "Tristana 崔丝塔娜",
    19: "Warwick 沃里克",
    20: "Nunu 努努",
    21: "MissFortune 厄运小姐",
    22: "Ashe 艾希",
    23: "Tryndamere 泰达米尔",
    24: "Jax 贾克斯",
    25: "Morgana 莫甘娜",
    26: "Zilean 基兰",
    27: "Singed 辛吉德",
    28: "Evelynn 伊芙琳",
    29: "Twitch 图奇",
    30: "Karthus 卡尔萨斯",
    31: "Chogath 科加斯",
    32: "Amumu 阿木木",
    33: "Rammus 拉莫斯",
    34: "Anivia 艾尼维亚",
    35: "Shaco 萨科",
    36: "DrMundo 蒙多医生",
    37: "Sona 娑娜",
    38: "Kassadin 卡萨丁",
    39: "Irelia 艾瑞莉娅",
    40: "Janna 迦娜",
    41: "Gangplank 普朗克",
    42: "Corki 库奇",
    43: "Karma 卡尔玛",
    44: "Taric 塔里克",
    45: "Veigar 维迦",
    48: "Trundle 特朗德尔",
    50: "Swain 斯维因",
    51: "Caitlyn 凯特琳",
    53: "Blitzcrank 布里茨",
    54: "Malphite 墨菲特",
    55: "Katarina 卡特琳娜",
    56: "Nocturne 魔腾",
    57: "Maokai 茂凯",
    58: "Renekton 雷克顿",
    59: "JarvanIV 嘉文四世",
    60: "Elise 伊莉丝",
    61: "Orianna 奥莉安娜",
    62: "MonkeyKing 孙悟空",
    63: "Brand 布兰德",
    64: "LeeSin 李青",
    67: "Vayne 薇恩",
    68: "Rumble 兰博",
    69: "Cassiopeia 卡西奥佩娅",
    72: "Skarner 斯卡纳",
    74: "Heimerdinger 黑默丁格",
    75: "Nasus 内瑟斯",
    76: "Nidalee 奈德丽",
    77: "Udyr 乌迪尔",
    78: "Poppy 波比",
    79: "Gragas 古拉加斯",
    80: "Pantheon 潘森",
    81: "Ezreal 伊泽瑞尔",
    82: "Mordekaiser 莫德凯撒",
    83: "Yorick 约里克",
    84: "Akali 阿卡丽",
    85: "Kennen 凯南",
    86: "Garen 盖伦",
    89: "Leona 蕾欧娜",
    90: "Malzahar 玛尔扎哈",
    91: "Talon 泰隆",
    92: "Riven 锐雯",
    96: "KogMaw 克格莫",
    98: "Shen 慎",
    99: "Lux 拉克丝",
    101: "Xerath 泽拉斯",
    102: "Shyvana 希瓦娜",
    103: "Ahri 阿狸",
    104: "Graves 格雷福斯",
    105: "Fizz 菲兹",
    106: "Volibear 沃利贝尔",
    107: "Rengar 雷恩加尔",
    110: "Varus 韦鲁斯",
    111: "Nautilus 诺提勒斯",
    112: "Viktor 维克托",
    113: "Sejuani 瑟庄妮",
    114: "Fiora 菲奥娜",
    115: "Ziggs 吉格斯",
    117: "Lulu 璐璐",
    119: "Draven 德莱文",
    120: "Hecarim 赫卡里姆",
    121: "Khazix 卡兹克",
    122: "Darius 德莱厄斯",
    126: "Jayce 杰斯",
    127: "Lissandra 丽桑卓",
    131: "Diana 黛安娜",
    133: "Quinn 奎因",
    134: "Syndra 辛德拉",
    136: "AurelionSol 奥瑞利安·索尔",
    141: "Kayn 凯隐",
    142: "Zoe 佐伊",
    143: "Zyra 婕拉",
    145: "Kaisa 卡莎",
    147: "Seraphine 萨勒芬妮",
    150: "Gnar 迷失之牙",
    154: "Zac 扎克",
    157: "Yasuo 亚索",
    161: "Velkoz 维克兹",
    163: "Taliyah 塔莉垭",
    164: "Camille 卡蜜尔",
    166: "Akshan 阿克尚",
    200: "Belveth 卑尔维斯",
    201: "Braum 布隆",
    202: "Jhin 烬",
    203: "Kindred 千珏",
    221: "Zeri 泽丽",
    222: "Jinx 金克丝",
    223: "TahmKench 塔姆",
    233: "Briar 贝蕾亚",
    234: "Viego 佛耶戈",
    235: "Senna 赛娜",
    236: "Lucian 卢锡安",
    238: "Zed 劫",
    240: "Kled 克烈",
    245: "Ekko 艾克",
    246: "Qiyana 奇亚娜",
    254: "Vi 蔚",
    266: "Aatrox 亚托克斯",
    267: "Nami 娜美",
    268: "Azir 阿兹尔",
    350: "Yuumi 悠米",
    360: "Samira 莎弥拉",
    412: "Thresh 锤石",
    420: "Illaoi 俄洛伊",
    421: "RekSai 雷克塞",
    427: "Ivern 艾翁",
    429: "Kalista 卡莉丝塔",
    432: "Bard 巴德",
    497: "Rakan 洛",
    498: "Xayah 霞",
    516: "Ornn 奥恩",
    517: "Sylas 塞拉斯",
    518: "Neeko 妮蔻",
    523: "Aphelios 厄斐琉斯",
    526: "Rell 芮尔",
    555: "Pyke 派克",
    711: "Vex 薇古丝",
    777: "Yone 永恩",
    799: "Ambessa 安蓓萨",
    800: "Mel 梅尔",
    804: "Yunara 芸阿娜",
    875: "Sett 瑟提",
    876: "Lillia 莉莉娅",
    887: "Gwen 格温",
    888: "Renata 烈娜塔",
    893: "Aurora 阿萝拉",
    895: "Nilah 尼菈",
    897: "KSante 奎桑提",
    901: "Smolder 斯莫德",
    902: "Milio 米利欧",
    904: "Zaahen 亚恒",
    910: "Hwei 彗",
    950: "Naafiri 纳亚菲利",
    # ── 末日人机 特殊变体 (id 66600+) ──
    66600: "Ruby_Urgot 末日人机·厄加特",
    66602: "Ruby_Corki 末日人机·库奇",
    66603: "Ruby_Lux 末日人机·拉克丝",
    66604: "Ruby_Amumu 末日人机·阿木木",
    66605: "Ruby_Chogath 末日人机·科加斯",
    66606: "Ruby_Tristana 末日人机·崔丝塔娜",
    66607: "Ruby_Nami 末日人机·娜美",
    66608: "Ruby_LeeSin 末日人机·李青",
    66609: "Ruby_Caitlyn 末日人机·凯特琳",
    66610: "Ruby_Nautilus 末日人机·诺提勒斯",
    66611: "Ruby_Maokai 末日人机·茂凯",
    66612: "Ruby_Xerath 末日人机·泽拉斯",
    66613: "Ruby_Brand 末日人机·布兰德",
    66614: "Ruby_Wukong 末日人机·孙悟空",
    66615: "Ruby_Soraka 末日人机·索拉卡",
    66616: "Ruby_Diana 末日人机·黛安娜",
    66617: "Ruby_Jinx 末日人机·金克丝",
    66618: "Ruby_Malzahar 末日人机·玛尔扎哈",
    66619: "Ruby_Blitzcrank 末日人机·布里茨",
}

# ── 游戏大区 ID → 配置信息（从 WeGame 官方配置文件提取，29 个区） ──
# 来源: wegame-api-export/游戏大区配置文件LOLGameArea.*.js

GAME_AREA_INFO: dict[int, dict[str, str]] = {
    1: {"strid": "HN1",  "isp": "电信一",     "name": "艾欧尼亚",    "idc": "东莞东城",   "tcls": "257"},
    2: {"strid": "WT1",  "isp": "网通一",     "name": "比尔吉沃特",  "idc": "济南担山屯", "tcls": "258"},
    3: {"strid": "HN2",  "isp": "电信二",     "name": "祖安",       "idc": "杭州东冠",   "tcls": "513"},
    4: {"strid": "HN3",  "isp": "电信三",     "name": "诺克萨斯",    "idc": "东莞大朗",   "tcls": "769"},
    5: {"strid": "HN4",  "isp": "电信四",     "name": "班德尔城",    "idc": "成都光华",   "tcls": "1025"},
    6: {"strid": "WT2",  "isp": "网通二",     "name": "德玛西亚",    "idc": "济南担山屯", "tcls": "514"},
    7: {"strid": "HN5",  "isp": "电信五",     "name": "皮尔特沃夫",  "idc": "杭州东冠",   "tcls": "1281"},
    8: {"strid": "HN6",  "isp": "电信六",     "name": "战争学院",    "idc": "东莞大朗",   "tcls": "1537"},
    9: {"strid": "WT3",  "isp": "网通三",     "name": "弗雷尔卓德",  "idc": "天津数据中心","tcls": "770"},
    10: {"strid": "HN7", "isp": "电信七",     "name": "巨神峰",      "idc": "杭州东冠",   "tcls": "1793"},
    11: {"strid": "HN8", "isp": "电信八",     "name": "雷瑟守备",    "idc": "东莞大朗",   "tcls": "2049"},
    12: {"strid": "WT4", "isp": "网通四",     "name": "无畏先锋",    "idc": "济南担山屯", "tcls": "1026"},
    13: {"strid": "HN9", "isp": "电信九",     "name": "裁决之地",    "idc": "成都高新",   "tcls": "2305"},
    14: {"strid": "HN10","isp": "电信十",     "name": "黑色玫瑰",    "idc": "东莞大朗",   "tcls": "2561"},
    15: {"strid": "HN11","isp": "电信十一",   "name": "暗影岛",      "idc": "东莞大朗",   "tcls": "2817"},
    16: {"strid": "WT5", "isp": "网通五",     "name": "恕瑞玛",      "idc": "天津数据中心","tcls": "1282"},
    17: {"strid": "HN12","isp": "电信十二",   "name": "钢铁烈阳",    "idc": "成都高新",   "tcls": "3073"},
    18: {"strid": "HN13","isp": "电信十三",   "name": "水晶之痕",    "idc": "杭州东冠",   "tcls": "3329"},
    19: {"strid": "HN14","isp": "电信十四",   "name": "均衡教派",    "idc": "南京二长",   "tcls": "3585"},
    20: {"strid": "WT6", "isp": "网通六",     "name": "扭曲丛林",    "idc": "天津数据中心","tcls": "1538"},
    21: {"strid": "EDU1","isp": "教育网",     "name": "教育网专区",  "idc": "上海南汇",   "tcls": "65539"},
    22: {"strid": "HN15","isp": "电信十五",   "name": "影流",        "idc": "南京二长",   "tcls": "3841"},
    23: {"strid": "HN16","isp": "电信十六",   "name": "守望之海",    "idc": "南京二长",   "tcls": "4097"},
    24: {"strid": "HN17","isp": "电信十七",   "name": "征服之海",    "idc": "东莞大朗",   "tcls": "4353"},
    25: {"strid": "HN18","isp": "电信十八",   "name": "卡拉曼达",    "idc": "深圳蛇口",   "tcls": "4609"},
    26: {"strid": "WT7", "isp": "网通七",     "name": "巨龙之巢",    "idc": "天津数据中心","tcls": "1794"},
    27: {"strid": "HN19","isp": "电信十九",   "name": "皮城警备",    "idc": "成都高新",   "tcls": "4865"},
    30: {"strid": "BGP1","isp": "全网络大区一","name": "男爵领域",    "idc": "上海腾讯宝信DC","tcls": "261"},
    31: {"strid": "BGP2","isp": "全网络大区二","name": "峡谷之巅",    "idc": "上海腾讯宝信DC","tcls": "517"},
}

# ── 大区解析 ──────────────────────────────────────────────────────────────

# 全部有效大区 ID 列表（按编号升序）
ALL_AREA_IDS: list[int] = sorted(GAME_AREA_INFO.keys())

# 大区中文名 → ID 反向映射
AREA_NAME_TO_ID: dict[str, int] = {
    area["name"]: aid for aid, area in GAME_AREA_INFO.items()
}


def resolve_areas(area_arg: str) -> list[int]:
    """将用户输入的 --area 参数解析为大区 ID 列表。

    支持格式：
    - 单区： ``"艾欧尼亚"`` 或 ``"1"``
    - 多区： ``"艾欧尼亚,祖安"``（逗号分隔，兼容中文逗号）
    - 全部： ``"全部"`` 或 ``"all"``
    - 默认 fallback： ``[1]``

    无效名称会被跳过并发出 warning，去重保序。空输入返回 ``[1]``。
    """
    s = area_arg.strip()
    if not s:
        return [1]

    # 全部
    if s.lower() in ("全部", "all"):
        return ALL_AREA_IDS

    # 逗号分隔（兼容中文逗号）
    tokens = [t.strip() for t in re.split(r"[，,]", s) if t.strip()]

    seen: set[int] = set()
    result: list[int] = []
    for token in tokens:
        aid = None
        # 尝试数字 ID
        try:
            aid = int(token)
        except ValueError:
            pass
        # 尝试中文名
        if aid is None:
            aid = AREA_NAME_TO_ID.get(token)
        if aid is None:
            logger.warning("未知大区名称: %s，已跳过", token)
            continue
        if aid not in GAME_AREA_INFO:
            logger.warning("大区 ID %d 不在已知列表中，已跳过", aid)
            continue
        if aid not in seen:
            seen.add(aid)
            result.append(aid)

    return result if result else [1]


# ── 工具函数 ──────────────────────────────────────────────────────────────

def get_wegame_tier_name(tier: int) -> str:
    """WeGame API 返回的段位数值 → 中文显示名。"""
    return WEGAME_TIER_NAMES.get(tier, f"段位{tier}")


def get_champion_name(cid: int) -> str:
    """根据英雄 ID 返回中文名，未知则返回 '英雄{id}'。"""
    display = CHAMPION_DISPLAY.get(cid)
    if display:
        parts = display.split(" ", 1)
        return parts[1] if len(parts) > 1 else display
    return f"英雄{cid}"


def get_champion_name_en(cid: int) -> str:
    """根据英雄 ID 返回英文名，未知则返回 'Champion{id}'。"""
    display = CHAMPION_DISPLAY.get(cid)
    if display:
        return display.split(" ", 1)[0]
    return f"Champion{cid}"


def get_game_area_name(aid: int) -> str:
    """根据大区 ID 返回中文名，未知则返回 '大区{id}'。"""
    area = GAME_AREA_INFO.get(aid)
    if area:
        return f"{area['name']}（{area['isp']}）"
    return f"大区{aid}"


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
