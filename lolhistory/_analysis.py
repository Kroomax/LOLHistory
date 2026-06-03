"""数据分析与交互式 HTML 报告生成模块。

从 SQLite 数据库读取对局历史，进行多维度统计分析，
生成单个静态交互式 HTML 文件（Chart.js CDN）。
"""

import sqlite3
import json
import math
import statistics
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from pathlib import Path

# ── 常量 ────────────────────────────────────────────────────────────────────

# 段位序号映射（API 返回数值字符串）
_TIER_INDEX: dict[str, int] = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}
_TIER_NAMES: list[str] = [
    "Iron", "Bronze", "Silver", "Gold", "Platinum",
    "Emerald", "Diamond", "Master", "Grandmaster", "Challenger",
]
_TIER_NAMES_CN: list[str] = [
    "黑铁", "青铜", "白银", "黄金", "铂金",
    "翡翠", "钻石", "大师", "宗师", "王者",
]
_RANK_NAMES: dict[str, str] = {"0": "I", "1": "II", "2": "III", "3": "IV"}

# 英雄 ID → 名称映射（常用英雄 + 数据中出现的）
_CHAMPION_NAMES: dict[int, str] = {
    1: "Annie 安妮", 2: "Olaf 奥拉夫", 3: "Galio 加里奥",
    4: "Twisted Fate 卡牌", 5: "Xin Zhao 赵信", 6: "Urgot 厄加特",
    7: "LeBlanc 乐芙兰", 8: "Vladimir 弗拉基米尔", 9: "Fiddlesticks 费德提克",
    10: "Kayle 凯尔", 11: "Master Yi 易", 12: "Alistar 阿利斯塔",
    13: "Ryze 瑞兹", 14: "Sion 赛恩", 15: "Sivir 希维尔",
    16: "Soraka 索拉卡", 17: "Teemo 提莫", 18: "Tristana 崔丝塔娜",
    19: "Warwick 沃里克", 20: "Nunu 努努", 21: "Miss Fortune 厄运小姐",
    22: "Ashe 艾希", 23: "Tryndamere 泰达米尔", 24: "Jax 贾克斯",
    25: "Morgana 莫甘娜", 26: "Zilean 基兰", 27: "Singed 辛吉德",
    28: "Evelynn 伊芙琳", 29: "Twitch 图奇", 30: "Karthus 卡尔萨斯",
    31: "Cho'Gath 科加斯", 32: "Amumu 阿木木", 33: "Rammus 拉莫斯",
    34: "Anivia 艾尼维亚", 35: "Shaco 萨科", 36: "Dr. Mundo 蒙多",
    37: "Sona 娑娜", 38: "Kassadin 卡萨丁", 39: "Irelia 艾瑞莉娅",
    40: "Janna 迦娜", 41: "Gangplank 普朗克", 42: "Corki 库奇",
    43: "Karma 卡尔玛", 44: "Taric 塔里克", 45: "Veigar 维迦",
    48: "Trundle 特朗德尔", 50: "Swain 斯维因", 51: "Caitlyn 凯特琳",
    53: "Blitzcrank 布里茨", 54: "Malphite 墨菲特", 55: "Katarina 卡特琳娜",
    56: "Nocturne 魔腾", 57: "Maokai 茂凯", 58: "Renekton 雷克顿",
    59: "Jarvan IV 嘉文四世", 60: "Elise 伊莉丝", 61: "Orianna 奥莉安娜",
    62: "Wukong 孙悟空", 63: "Brand 布兰德", 64: "Lee Sin 李青",
    67: "Vayne 薇恩", 68: "Rumble 兰博", 69: "Cassiopeia 卡西奥佩娅",
    72: "Skarner 斯卡纳", 74: "Heimerdinger 黑默丁格", 75: "Nasus 内瑟斯",
    76: "Nidalee 奈德丽", 77: "Udyr 乌迪尔", 78: "Poppy 波比",
    79: "Gragas 古拉加斯", 80: "Pantheon 潘森", 81: "Ezreal 伊泽瑞尔",
    82: "Mordekaiser 莫德凯撒", 83: "Yorick 约里克", 84: "Akali 阿卡丽",
    85: "Kennen 凯南", 86: "Garen 盖伦", 89: "Leona 蕾欧娜",
    90: "Malzahar 玛尔扎哈", 91: "Talon 泰隆", 92: "Riven 锐雯",
    96: "Kog'Maw 克格莫", 98: "Shen 慎", 99: "Lux 拉克丝",
    101: "Xerath 泽拉斯", 102: "Shyvana 希瓦娜", 103: "Ahri 阿狸",
    104: "Graves 格雷福斯", 105: "Fizz 菲兹", 106: "Volibear 沃利贝尔",
    107: "Rengar 雷恩加尔", 110: "Varus 韦鲁斯", 111: "Nautilus 诺提勒斯",
    112: "Viktor 维克托", 113: "Sejuani 瑟庄妮", 114: "Fiora 菲奥娜",
    115: "Ziggs 吉格斯", 117: "Lulu 璐璐", 119: "Draven 德莱文",
    120: "Hecarim 赫卡里姆", 121: "Kha'Zix 卡兹克", 122: "Darius 德莱厄斯",
    126: "Jayce 杰斯", 127: "Lissandra 丽桑卓", 131: "Diana 黛安娜",
    133: "Quinn 奎因", 134: "Syndra 辛德拉", 136: "Aurelion Sol 奥瑞利安·索尔",
    141: "Kayn 凯隐", 142: "Zoe 佐伊", 143: "Zyra 婕拉",
    145: "Kai'Sa 虚空之女", 147: "Seraphine 萨勒芬妮",
    150: "Gnar 纳尔", 154: "Zac 扎克", 157: "Yasuo 亚索",
    161: "Kai'Sa 虚空之女", 163: "Taliyah 塔莉垭", 164: "Camille 卡蜜尔",
    166: "Akshan 阿克尚", 200: "Bel'Veth 卑尔维斯", 201: "Braum 布隆",
    202: "Jhin 烬", 203: "Kindred 千珏", 221: "Vel'Koz 维克兹",
    222: "Jinx 金克丝", 223: "Tahm Kench 塔姆", 234: "Viego 佛耶戈",
    235: "Senna 赛娜", 236: "Lucian 卢锡安", 238: "Zed 劫",
    240: "Kled 克烈", 245: "Ekko 艾克", 246: "Qiyana 奇亚娜",
    254: "Vi 蔚", 266: "Aatrox 亚托克斯", 267: "Nami 娜美",
    268: "Azir 阿兹尔", 350: "Yuumi 悠米", 360: "Samira 莎弥拉",
    412: "Thresh 锤石", 420: "K'Sante 奎桑提", 421: "Rek'Sai 雷克塞",
    427: "Ivern 艾翁", 429: "Kalista 卡莉丝塔", 432: "Bard 巴德",
    497: "Rakan 洛", 498: "Xayah 霞", 516: "Ornn 奥恩",
    517: "Sylas 塞拉斯", 518: "Neeko 妮蔻", 523: "Aphelios 厄斐琉斯",
    526: "Rell 芮尔", 555: "Pyke 派克", 711: "Gwen 格温",
    777: "Yone 永恩", 800: "Hwei 慧", 875: "Sett 瑟提",
    876: "Lillia 莉莉娅", 887: "Yunara 云娜拉", 888: "Aurora 奥罗拉",
    893: "Renata Glasc 烈娜塔", 895: "Nilah 尼菈", 897: "Naafiri 纳亚菲利",
    901: "Ambessa 安蓓萨", 902: "Smolder 斯莫德", 910: "Briar 布蕾尔",
    950: "Milio 米利欧", 951: "Zeri 泽丽", 952: "Vex 薇古丝",
}

# Chart.js 配色
_CHART_COLORS = [
    "rgba(74,158,255,0.8)", "rgba(168,85,247,0.8)", "rgba(245,158,11,0.8)",
    "rgba(20,184,166,0.8)", "rgba(236,72,153,0.8)", "rgba(46,204,113,0.8)",
    "rgba(231,76,60,0.8)", "rgba(149,165,166,0.8)", "rgba(241,196,15,0.8)",
    "rgba(155,89,182,0.8)",
]
_CHART_BORDERS = [c.replace("0.8", "1.0") for c in _CHART_COLORS]

_DAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_POSITION_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", "Invalid"]


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _champion_name(cid: int) -> str:
    """返回英雄中文名，未知则返回 ID。"""
    name = _CHAMPION_NAMES.get(cid)
    if name:
        # 提取中文部分
        parts = name.split(" ", 1)
        return parts[1] if len(parts) > 1 else name
    return f"英雄{cid}"


def _champion_name_en(cid: int) -> str:
    """返回英雄英文名，未知则返回 ID。"""
    name = _CHAMPION_NAMES.get(cid)
    if name:
        return name.split(" ", 1)[0]
    return f"Champion{cid}"


def _tier_name(tier_str: str) -> str:
    """数值段位→中文名。"""
    if not tier_str or tier_str not in _TIER_INDEX:
        return "无段位"
    return _TIER_NAMES_CN[_TIER_INDEX[tier_str]]


def _tier_rank_display(tier_str: str, rank_str: str) -> str:
    """段位+等级 显示文本，如 '钻石 II'。"""
    if not tier_str or tier_str not in _TIER_INDEX:
        return "无段位"
    idx = _TIER_INDEX[tier_str]
    cn = _TIER_NAMES_CN[idx]
    if idx >= 7:  # 大师+
        return cn
    rk = _RANK_NAMES.get(rank_str, "")
    return f"{cn} {rk}"


def _total_lp(tier_str: str, lp: int) -> int | None:
    """合成连续 LP 分数：段位索引*400 + LP。"""
    if not tier_str or tier_str not in _TIER_INDEX:
        return None
    return _TIER_INDEX[tier_str] * 400 + (lp or 0)


def _win_rate(wins: int, total: int) -> float:
    """计算胜率百分比，保留一位小数。"""
    return round(wins / total * 100, 1) if total > 0 else 0.0


# ── 数据加载 ─────────────────────────────────────────────────────────────────

def _load_matches(db_path: str) -> list[dict]:
    """从 SQLite 加载 match_summary 全部行，按时间升序。"""
    if not Path(db_path).exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM match_summary")
        if cur.fetchone()[0] == 0:
            return []
    except sqlite3.OperationalError:
        return []

    cur.execute("SELECT * FROM match_summary ORDER BY game_start_time ASC")
    rows = cur.fetchall()
    conn.close()

    matches = []
    for row in rows:
        m = dict(row)
        # 解析时间
        try:
            m["_dt"] = datetime.strptime(m["game_start_time"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            m["_dt"] = None
        matches.append(m)

    return matches


def _filter_ranked(matches: list[dict]) -> list[dict]:
    """仅保留排位单双排 (queue_id=420)。"""
    return [m for m in matches if m.get("game_queue_id") == 420]


# ── 总览分析 ─────────────────────────────────────────────────────────────────

def _analyze_overview(matches: list[dict]) -> dict:
    """职业生涯总览统计。"""
    if not matches:
        return {"total_games": 0, "summary": "暂无对局数据。"}

    total = len(matches)
    wins = sum(1 for m in matches if m["win"])
    losses = total - wins
    wr = _win_rate(wins, total)

    total_kills = sum(m["kills"] for m in matches)
    total_deaths = sum(m["deaths"] for m in matches)
    total_assists = sum(m["assists"] for m in matches)
    overall_kda = round((total_kills + total_assists) / max(total_deaths, 1), 2)

    total_gold = sum(m["gold_earned"] for m in matches)
    total_mvps = sum(1 for m in matches if m["was_mvp"])
    total_svps = sum(1 for m in matches if m["was_svp"])
    total_surrenders = sum(1 for m in matches if m["was_surrender"])
    total_afks = sum(1 for m in matches if m["was_afk"])
    total_penta = sum(m["penta_kills"] for m in matches)
    total_quadra = sum(m["quadra_kills"] for m in matches)

    ranked = _filter_ranked(matches)
    first_date = matches[0]["_dt"]
    last_date = matches[-1]["_dt"]
    days_active = 0
    if first_date and last_date:
        days_active = len(set(m["_dt"].strftime("%Y-%m-%d") for m in matches if m["_dt"]))
        days_since_first = (last_date - first_date).days + 1
    else:
        days_since_first = 0

    attendance = round(days_active / days_since_first * 100, 1) if days_since_first > 0 else 0

    # 最高段位
    highest_total_lp = -1
    highest_tier_display = "无段位"
    current_total_lp = -1
    current_tier_display = "无段位"
    for m in ranked:
        tlp = _total_lp(m.get("tier", ""), m.get("league_points", 0))
        if tlp is not None and tlp > highest_total_lp:
            highest_total_lp = tlp
            highest_tier_display = _tier_rank_display(m.get("tier", ""), m.get("rank", ""))
    if ranked:
        last_r = ranked[-1]
        current_total_lp = _total_lp(last_r.get("tier", ""), last_r.get("league_points", 0))
        current_tier_display = _tier_rank_display(last_r.get("tier", ""), last_r.get("rank", ""))

    # 最常用英雄
    champ_counts = Counter(m["champion_id"] for m in matches)
    most_played = champ_counts.most_common(1)[0] if champ_counts else (0, 0)

    # 独特英雄/位置
    unique_champs = len(set(m["champion_id"] for m in matches))
    unique_positions = len(set(m["position"] for m in matches))

    avg_score = sum(m["game_score"] for m in matches) / total if total > 0 else 0
    max_score = max(m["game_score"] for m in matches) if matches else 0

    # 概要
    summary = (
        f"共 {total} 场对局，胜率 {wr}%，整体 KDA {overall_kda}。"
        f"累计获得 {total_gold:,} 金币，{total_mvps} 次 MVP，{total_svps} 次 SVP。"
    )

    return {
        "total_games": total, "wins": wins, "losses": losses, "win_rate": wr,
        "total_kills": total_kills, "total_deaths": total_deaths, "total_assists": total_assists,
        "overall_kda": overall_kda, "total_gold": total_gold,
        "total_mvps": total_mvps, "total_svps": total_svps,
        "total_surrenders": total_surrenders, "total_afks": total_afks,
        "total_penta": total_penta, "total_quadra": total_quadra,
        "first_date": first_date.strftime("%Y-%m-%d") if first_date else "",
        "last_date": last_date.strftime("%Y-%m-%d") if last_date else "",
        "days_active": days_active, "days_since_first": days_since_first,
        "attendance": attendance,
        "highest_tier": highest_tier_display, "current_tier": current_tier_display,
        "most_played_champ": most_played[0], "most_played_champ_name": _champion_name(most_played[0]),
        "most_played_games": most_played[1],
        "unique_champions": unique_champs, "unique_positions": unique_positions,
        "avg_score": round(avg_score), "max_score": max_score,
        "summary": summary,
    }


# ── 时间维度胜率因子 ────────────────────────────────────────────────────────

def _analyze_win_rate_by_day_of_week(matches: list[dict]) -> dict:
    """按星期几分析胜率。"""
    if not matches:
        return {"labels": _DAYS_CN, "win_rates": [0]*7, "games": [0]*7, "summary": "暂无数据。"}

    day_stats = {i: {"wins": 0, "total": 0} for i in range(7)}
    for m in matches:
        if m["_dt"]:
            wd = m["_dt"].weekday()
            day_stats[wd]["total"] += 1
            if m["win"]:
                day_stats[wd]["wins"] += 1

    labels = _DAYS_CN
    win_rates = [_win_rate(day_stats[i]["wins"], day_stats[i]["total"]) for i in range(7)]
    games = [day_stats[i]["total"] for i in range(7)]
    wins = [day_stats[i]["wins"] for i in range(7)]

    # 找最高/最低胜率日
    valid = [(i, wr) for i, wr in enumerate(win_rates) if games[i] > 0]
    best = max(valid, key=lambda x: x[1]) if valid else (0, 0)
    worst = min(valid, key=lambda x: x[1]) if valid else (0, 0)
    diff = best[1] - worst[1]

    if diff >= 10:
        summary = f"星期几确实影响你的状态——{labels[best[0]]}胜率({best[1]}%)比{labels[worst[0]]}({worst[1]}%)高出 {diff:.0f}%，你是典型的'{labels[best[0]]}战神'。"
    elif diff >= 5:
        summary = f"{labels[best[0]]}是你手感最热的一天（胜率 {best[1]}%），而{labels[worst[0]]}则需要调整心态（{worst[1]}%）。"
    else:
        summary = f"一周七天你的表现都很稳定，胜率波动仅 {diff:.1f}%，是真正的全天候选手。"

    return {"labels": labels, "win_rates": win_rates, "games": games, "wins": wins, "summary": summary}


def _analyze_win_rate_by_hour(matches: list[dict]) -> dict:
    """按小时分析胜率。"""
    hour_stats = {h: {"wins": 0, "total": 0} for h in range(24)}
    for m in matches:
        if m["_dt"]:
            h = m["_dt"].hour
            hour_stats[h]["total"] += 1
            if m["win"]:
                hour_stats[h]["wins"] += 1

    labels = [f"{h}:00" for h in range(24)]
    win_rates = [_win_rate(hour_stats[h]["wins"], hour_stats[h]["total"]) for h in range(24)]
    games = [hour_stats[h]["total"] for h in range(24)]

    valid = [(h, wr, games[h]) for h, wr in enumerate(win_rates) if games[h] >= 3]
    if valid:
        best = max(valid, key=lambda x: x[1])
        worst = min(valid, key=lambda x: x[1])
        summary = f"你的黄金时段是 {best[0]}:00（胜率 {best[1]}%，{best[2]}场），而 {worst[0]}:00 胜率仅 {worst[1]}%——也许深夜排位不是好主意？"
    else:
        summary = "各时段数据量不足，尚无法确定你的最佳游戏时间。"

    return {"labels": labels, "win_rates": win_rates, "games": games, "summary": summary}


def _analyze_win_rate_by_team_side(matches: list[dict]) -> dict:
    """按红蓝方分析胜率。"""
    side_stats = {100: {"wins": 0, "total": 0}, 200: {"wins": 0, "total": 0}}
    for m in matches:
        tid = m["team_id"]
        if tid in side_stats:
            side_stats[tid]["total"] += 1
            if m["win"]:
                side_stats[tid]["wins"] += 1

    blue_wr = _win_rate(side_stats[100]["wins"], side_stats[100]["total"])
    red_wr = _win_rate(side_stats[200]["wins"], side_stats[200]["total"])
    diff = abs(blue_wr - red_wr)

    if blue_wr > red_wr + 3:
        summary = f"你在蓝色方胜率更高（{blue_wr}% vs {red_wr}%），蓝色方先手优势对你帮助明显。"
    elif red_wr > blue_wr + 3:
        summary = f"神奇的是你在红色方胜率反而更高（{red_wr}% vs {blue_wr}%），counter位和龙坑地形是你的秘密武器。"
    else:
        summary = f"红蓝双方对你几乎无影响（蓝色 {blue_wr}% vs 红色 {red_wr}%），在哪边都能稳定发挥。"

    return {
        "labels": ["蓝色方", "红色方"],
        "win_rates": [blue_wr, red_wr],
        "games": [side_stats[100]["total"], side_stats[200]["total"]],
        "wins": [side_stats[100]["wins"], side_stats[200]["wins"]],
        "summary": summary,
    }


def _analyze_win_rate_by_position(matches: list[dict]) -> dict:
    """按位置分析胜率。"""
    pos_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for m in matches:
        pos = m["position"] or "Invalid"
        pos_stats[pos]["total"] += 1
        if m["win"]:
            pos_stats[pos]["wins"] += 1

    # 按预定义顺序
    ordered = []
    for p in _POSITION_ORDER:
        if p in pos_stats:
            ordered.append(p)
    for p in sorted(pos_stats):
        if p not in ordered:
            ordered.append(p)

    pos_names = {
        "TOP": "上单", "JUNGLE": "打野", "MIDDLE": "中单",
        "BOTTOM": "ADC", "UTILITY": "辅助", "Invalid": "未知",
    }
    labels = [pos_names.get(p, p) for p in ordered]
    win_rates = [_win_rate(pos_stats[p]["wins"], pos_stats[p]["total"]) for p in ordered]
    games = [pos_stats[p]["total"] for p in ordered]
    wins = [pos_stats[p]["wins"] for p in ordered]

    # 找主位置
    main = max(ordered, key=lambda p: pos_stats[p]["total"], default="")
    main_wr = _win_rate(pos_stats[main]["wins"], pos_stats[main]["total"]) if main else 0
    main_name = pos_names.get(main, main)

    summary = f"你的主位置是{main_name}（{pos_stats[main]['total']}场，胜率{main_wr}%）。"
    off_roles = [(p, _win_rate(pos_stats[p]["wins"], pos_stats[p]["total"]))
                 for p in ordered if p != main and pos_stats[p]["total"] >= 3]
    if off_roles:
        best_off = max(off_roles, key=lambda x: x[1])
        summary += f" 客串{pos_names.get(best_off[0], best_off[0])}时胜率意外达到{best_off[1]}%，或许是隐藏天赋。"

    return {"labels": labels, "win_rates": win_rates, "games": games, "wins": wins, "summary": summary}


def _analyze_win_rate_by_kda_range(matches: list[dict]) -> dict:
    """按 KDA 范围分析胜率。"""
    buckets = [
        ("0-1", 0, 1), ("1-2", 1, 2), ("2-3", 2, 3),
        ("3-5", 3, 5), ("5-10", 5, 10), ("10+", 10, float("inf")),
    ]
    bucket_stats = {b[0]: {"wins": 0, "total": 0} for b in buckets}
    for m in matches:
        kda = m["kda"]
        for label, lo, hi in buckets:
            if lo <= kda < hi:
                bucket_stats[label]["total"] += 1
                if m["win"]:
                    bucket_stats[label]["wins"] += 1
                break

    labels = [b[0] for b in buckets]
    win_rates = [_win_rate(bucket_stats[l]["wins"], bucket_stats[l]["total"]) for l in labels]
    games = [bucket_stats[l]["total"] for l in labels]

    # 关键洞察：KDA 多高时胜率突破 80%?
    threshold = None
    for i, wr in enumerate(win_rates):
        if wr >= 80 and games[i] >= 3:
            threshold = labels[i]
            break

    if threshold:
        summary = f"当你的 KDA 达到 {threshold} 时，胜率突破 {win_rates[labels.index(threshold)]:.0f}%——保持不死就是最好的上分策略。"
    else:
        summary = "KDA 与胜率呈正相关：杀得越多、死得越少，赢面越大。这虽然是废话，但数据证明了它。"

    return {"labels": labels, "win_rates": win_rates, "games": games, "summary": summary}


def _analyze_win_rate_by_duration(matches: list[dict]) -> dict:
    """按对局时长分桶分析胜率。"""
    durations = [m["game_time_played"] / 60 for m in matches]
    if not durations:
        return {"labels": [], "win_rates": [], "scatter": [], "summary": "暂无数据。"}

    q1 = statistics.median(sorted(durations)[:len(durations)//2]) if len(durations) >= 4 else min(durations)
    q3 = statistics.median(sorted(durations)[len(durations)//2:]) if len(durations) >= 4 else max(durations)

    # 按固定分钟分桶
    bucket_edges = [15, 20, 25, 30, 35, float("inf")]
    bucket_labels = ["<15min", "15-20min", "20-25min", "25-30min", "30-35min", "35min+"]
    bucket_stats = {l: {"wins": 0, "total": 0} for l in bucket_labels}

    scatter = []
    for m in matches:
        dur = m["game_time_played"] / 60
        # 分桶
        for i, edge in enumerate(bucket_edges):
            if dur < edge:
                bucket_stats[bucket_labels[i]]["total"] += 1
                if m["win"]:
                    bucket_stats[bucket_labels[i]]["wins"] += 1
                break
        scatter.append({"x": round(dur, 1), "y": 1 if m["win"] else 0})

    labels = bucket_labels
    win_rates = [_win_rate(bucket_stats[l]["wins"], bucket_stats[l]["total"]) for l in labels]
    games = [bucket_stats[l]["total"] for l in labels]

    # 洞察
    early = _win_rate(
        sum(bucket_stats[l]["wins"] for l in bucket_labels[:2]),
        sum(bucket_stats[l]["total"] for l in bucket_labels[:2]),
    )
    late = _win_rate(
        sum(bucket_stats[l]["wins"] for l in bucket_labels[4:]),
        sum(bucket_stats[l]["total"] for l in bucket_labels[4:]),
    )

    if early > late + 5:
        summary = f"你是快攻型选手——前20分钟胜率 {early}% 远高于大后期 {late}%，速战速决才是你的节奏。"
    elif late > early + 5:
        summary = f"你越打越强！大后期胜率 {late}% 远超前期 {early}%，是真正的后期大核选手。"
    else:
        summary = f"前中后各阶段发挥均衡（前期{early}% / 后期{late}%），你能适应各种节奏的对局。"

    return {"labels": labels, "win_rates": win_rates, "games": games, "scatter": scatter, "summary": summary}


def _analyze_mystery_factor(matches: list[dict]) -> dict:
    """聚合所有维度胜率方差，找出'神秘因子'。"""
    dimensions = []

    # 星期
    day = _analyze_win_rate_by_day_of_week(matches)
    day_valid = [wr for wr, g in zip(day["win_rates"], day["games"]) if g > 0]
    if len(day_valid) >= 2:
        dimensions.append({"name": "星期几", "variance": round(max(day_valid) - min(day_valid), 1)})

    # 小时
    hour = _analyze_win_rate_by_hour(matches)
    hour_valid = [wr for wr, g in zip(hour["win_rates"], hour["games"]) if g >= 3]
    if len(hour_valid) >= 2:
        dimensions.append({"name": "游戏时段", "variance": round(max(hour_valid) - min(hour_valid), 1)})

    # 红蓝方
    side = _analyze_win_rate_by_team_side(matches)
    dimensions.append({"name": "红蓝方", "variance": round(abs(side["win_rates"][0] - side["win_rates"][1]), 1)})

    # 位置
    pos = _analyze_win_rate_by_position(matches)
    pos_valid = [wr for wr, g in zip(pos["win_rates"], pos["games"]) if g > 0]
    if len(pos_valid) >= 2:
        dimensions.append({"name": "位置", "variance": round(max(pos_valid) - min(pos_valid), 1)})

    # KDA
    kda = _analyze_win_rate_by_kda_range(matches)
    kda_valid = [wr for wr, g in zip(kda["win_rates"], kda["games"]) if g > 0]
    if len(kda_valid) >= 2:
        dimensions.append({"name": "KDA范围", "variance": round(max(kda_valid) - min(kda_valid), 1)})

    # 时长
    dur = _analyze_win_rate_by_duration(matches)
    dur_valid = [wr for wr, g in zip(dur["win_rates"], dur["games"]) if g > 0]
    if len(dur_valid) >= 2:
        dimensions.append({"name": "对局时长", "variance": round(max(dur_valid) - min(dur_valid), 1)})

    dimensions.sort(key=lambda d: d["variance"], reverse=True)

    if dimensions:
        top = dimensions[0]
        summary = f"影响你胜率最大的'神秘因子'是【{top['name']}】，胜率极差高达 {top['variance']}%。"
        if top["name"] == "星期几":
            summary += " 选对日子上分，效果立竿见影！"
        elif top["name"] == "游戏时段":
            summary += " 在正确的时间打排位，事半功倍。"
        elif top["name"] == "KDA范围":
            summary += " KDA 波动如此之大，说明发挥不够稳定——稳定就是最大的上分空间。"
        else:
            summary += " 关注这个维度，或许就是你的突破口。"
    else:
        summary = "数据量不足以进行神秘因子分析。"

    return {"dimensions": dimensions, "summary": summary}


def _analyze_honors_impact(matches: list[dict]) -> dict:
    """分析获得各项荣誉时 vs 未获得时的胜率。"""
    honors = [
        ("most_kills", "击杀最多", "击杀王"),
        ("most_assists", "助攻最多", "助攻王"),
        ("most_gold", "金币最多", "首富"),
        ("most_damage", "伤害最高", "输出王"),
        ("most_taken", "承受伤害最高", "坦克王"),
        ("most_turrets", "推塔最多", "拆迁队长"),
    ]

    results = []
    for field, name, tag in honors:
        with_honor = {"wins": 0, "total": 0}
        without = {"wins": 0, "total": 0}
        for m in matches:
            if m.get(field):
                with_honor["total"] += 1
                if m["win"]:
                    with_honor["wins"] += 1
            else:
                without["total"] += 1
                if m["win"]:
                    without["wins"] += 1

        wr_with = _win_rate(with_honor["wins"], with_honor["total"])
        wr_without = _win_rate(without["wins"], without["total"])
        results.append({
            "field": field, "name": name, "tag": tag,
            "wr_with": wr_with, "wr_without": wr_without,
            "games_with": with_honor["total"],
            "diff": round(wr_with - wr_without, 1),
        })

    # 最关键荣誉
    best = max(results, key=lambda r: r["diff"])
    if best["diff"] > 5:
        summary = f"获得'{best['name']}'时胜率飙升 {best['diff']:.0f}%（{best['wr_with']}% vs {best['wr_without']}%），"
        summary += f"说明当你成为{best['tag']}时，队伍基本锁定胜局。"
    else:
        summary = "各项荣誉与胜率关联较为均衡，你的打法偏向团队协作而非个人carry。"

    return {"honors": results, "summary": summary}


# ── 英雄分析 ─────────────────────────────────────────────────────────────────

def _analyze_champion_radar(matches: list[dict]) -> dict:
    """Top 5 英雄多维雷达图（至少3场）。"""
    from collections import defaultdict

    champ_stats: dict[int, dict] = defaultdict(lambda: {
        "games": 0, "wins": 0,
        "kills": [], "deaths": [], "assists": [], "kda_vals": [],
        "gold": [], "score": [],
    })

    for m in matches:
        cid = m["champion_id"]
        cs = champ_stats[cid]
        cs["games"] += 1
        if m["win"]:
            cs["wins"] += 1
        cs["kills"].append(m["kills"])
        cs["deaths"].append(m["deaths"])
        cs["assists"].append(m["assists"])
        cs["kda_vals"].append(m["kda"])
        cs["gold"].append(m["gold_earned"])
        cs["score"].append(m["game_score"])

    # 至少 3 场
    eligible = [(cid, s) for cid, s in champ_stats.items() if s["games"] >= 3]
    eligible.sort(key=lambda x: x[1]["games"], reverse=True)
    top5 = eligible[:5]

    if not top5:
        return {"champions": [], "summary": "英雄场次不足（需要单个英雄至少3场），无法生成雷达图。"}

    # 六个维度: KDA, 击杀, 助攻, 金币, 评分, 生存率(1/deaths)
    dims_cn = ["KDA", "击杀", "助攻", "金币/分", "评分", "生存率"]

    # 归一化：所有英雄的所有维度值收集，做 min-max
    all_vals: dict[str, list] = {d: [] for d in dims_cn}
    champ_raw = {}

    for cid, s in top5:
        avg_kda = statistics.mean(s["kda_vals"]) if s["kda_vals"] else 0
        avg_kills = statistics.mean(s["kills"]) if s["kills"] else 0
        avg_assists = statistics.mean(s["assists"]) if s["assists"] else 0
        avg_gpm = statistics.mean([g / max(matches[i]["game_time_played"]/60, 1)
                                    for i, g in enumerate(s["gold"])]) if s["gold"] else 0
        avg_score = statistics.mean(s["score"]) if s["score"] else 0
        avg_survive = statistics.mean([1 / max(d, 1) for d in s["deaths"]]) if s["deaths"] else 0

        raw = [avg_kda, avg_kills, avg_assists, avg_gpm, avg_score, avg_survive]
        champ_raw[cid] = raw
        for i, d in enumerate(dims_cn):
            all_vals[d].append(raw[i])

    # min-max 归一化到 0-100
    def _norm100(v, d):
        vals = all_vals[d]
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return 50.0
        return round((v - mn) / (mx - mn) * 100, 1)

    champions_data = []
    for cid, raw in champ_raw.items():
        normed = {dims_cn[i]: _norm100(raw[i], dims_cn[i]) for i in range(len(dims_cn))}
        champions_data.append({
            "champion_id": cid,
            "name": _champion_name(cid),
            "games": champ_stats[cid]["games"],
            "win_rate": _win_rate(champ_stats[cid]["wins"], champ_stats[cid]["games"]),
            "metrics": normed,
        })

    best = champions_data[0]
    summary = (
        f"你的招牌英雄是 {best['name']}（{best['games']}场，胜率{best['win_rate']}%），"
        f"在 {len(top5)} 个常用英雄中综合实力最突出。"
    )
    if len(champions_data) >= 2:
        summary += f" 第二选择 {champions_data[1]['name']} 也可在特定对局中作为奇招。"

    return {"champions": champions_data, "dimensions": dims_cn, "summary": summary}


def _analyze_champion_pool(matches: list[dict]) -> dict:
    """英雄池分析。"""
    champ_counts = Counter(m["champion_id"] for m in matches)
    total = len(matches)

    # 英雄使用频率
    freq = []
    for cid, cnt in champ_counts.most_common(15):
        wins = sum(1 for m in matches if m["champion_id"] == cid and m["win"])
        freq.append({
            "champion_id": cid, "name": _champion_name(cid),
            "games": cnt, "wins": wins, "losses": cnt - wins,
            "freq_pct": round(cnt / total * 100, 1),
        })

    # 绝活指数: 最常用英雄占比
    top_game_pct = champ_counts.most_common(1)[0][1] / total * 100 if champ_counts else 0

    # 位置灵活性
    champ_positions = defaultdict(set)
    for m in matches:
        champ_positions[m["champion_id"]].add(m["position"])
    avg_positions = statistics.mean([len(ps) for ps in champ_positions.values()]) if champ_positions else 0

    if top_game_pct >= 80:
        summary = f"你是典型的绝活玩家——{_champion_name(champ_counts.most_common(1)[0][0])} 占了 {top_game_pct:.0f}% 的对局。英雄池虽浅，但专精也是一种力量。"
    elif top_game_pct >= 50:
        summary = f"你有明确的招牌英雄（占比{top_game_pct:.0f}%），同时尝试了 {len(champ_counts)} 个不同英雄，池子不算浅。"
    else:
        summary = f"英雄海！{len(champ_counts)} 个不同英雄轮换，平均每个英雄跨 {avg_positions:.1f} 个位置，是真正的全能选手。"

    return {
        "freq": freq,
        "unique_count": len(champ_counts),
        "top_pct": round(top_game_pct, 1),
        "avg_positions": round(avg_positions, 1),
        "summary": summary,
    }


# ── 段位趋势 ─────────────────────────────────────────────────────────────────

def _analyze_rank_progression(matches: list[dict]) -> dict:
    """段位和胜点时间趋势。"""
    ranked = [m for m in _filter_ranked(matches)
              if m.get("tier") and m["tier"] in _TIER_INDEX]

    if len(ranked) < 5:
        return {"labels": [], "lp_values": [], "tier_labels": [],
                "rolling_wr": [], "summary": "排位数据不足（需至少5场），无法绘制趋势图。"}

    labels = []
    lp_values = []
    tier_labels = []
    for m in ranked:
        dt = m["_dt"]
        labels.append(dt.strftime("%m/%d") if dt else "")
        tlp = _total_lp(m["tier"], m.get("league_points", 0))
        lp_values.append(tlp)
        tier_labels.append(_tier_rank_display(m["tier"], m.get("rank", "")))

    # 10场滚动胜率
    rolling_wr = []
    window = 10
    for i in range(len(ranked)):
        start = max(0, i - window + 1)
        seq = ranked[start:i+1]
        wr = sum(1 for m in seq if m["win"]) / len(seq) * 100
        rolling_wr.append(round(wr, 1))

    # 趋势概要
    if len(lp_values) >= 10:
        first_10_avg = statistics.mean(lp_values[:10])
        last_10_avg = statistics.mean(lp_values[-10:])
        change = last_10_avg - first_10_avg
    else:
        change = (lp_values[-1] or 0) - (lp_values[0] or 0)

    if change > 200:
        trend = "猛猛上分中"
    elif change > 50:
        trend = "稳定上分"
    elif change > -50:
        trend = "原地踏步"
    elif change > -200:
        trend = "略微下滑"
    else:
        trend = "断崖式下跌"

    # 段位变化
    tier_changes = []
    prev_tier = None
    for i, m in enumerate(ranked):
        tlp = lp_values[i]
        cur_tier_key = m["tier"]
        if prev_tier is not None and cur_tier_key != prev_tier:
            tier_changes.append({
                "date": labels[i],
                "tier": _tier_name(cur_tier_key),
                "lp": tlp,
            })
        prev_tier = cur_tier_key

    summary = f"排位趋势：{trend}（最近10场与最初10场 LP 变化 {change:+.0f}）。"
    if tier_changes:
        last_change = tier_changes[-1]
        summary += f" 最近一次段位变更为 {last_change['date']} 升入 {last_change['tier']}。"

    return {
        "labels": labels, "lp_values": lp_values, "tier_labels": tier_labels,
        "rolling_wr": rolling_wr, "tier_changes": tier_changes,
        "trend": trend, "lp_change": round(change),
        "summary": summary,
    }


# ── 出勤与日历 ───────────────────────────────────────────────────────────────

def _analyze_attendance(matches: list[dict]) -> dict:
    """出勤率与日历分析。"""
    if not matches:
        return {"days": [], "summary": "暂无数据。"}

    # 按日期聚合
    day_data: dict[str, dict] = defaultdict(lambda: {
        "games": 0, "wins": 0, "losses": 0,
        "total_time": 0, "lp_change": 0,
    })

    ranked_matches = [m for m in _filter_ranked(matches) if m.get("tier")]

    for m in matches:
        if m["_dt"]:
            d = m["_dt"].strftime("%Y-%m-%d")
        else:
            continue
        day_data[d]["games"] += 1
        if m["win"]:
            day_data[d]["wins"] += 1
        else:
            day_data[d]["losses"] += 1
        day_data[d]["total_time"] += m["game_time_played"]

    # LP 变化（从排位中推算）
    prev_total_lp = None
    for m in ranked_matches:
        if not m["_dt"]:
            continue
        d = m["_dt"].strftime("%Y-%m-%d")
        tlp = _total_lp(m["tier"], m.get("league_points", 0))
        if tlp is None:
            continue
        if prev_total_lp is not None:
            day_data[d]["lp_change"] += tlp - prev_total_lp
        prev_total_lp = tlp
        # 确保日期在 day_data 中存在
        if d not in day_data:
            day_data[d] = {"games": 0, "wins": 0, "losses": 0, "total_time": 0, "lp_change": 0}
        day_data[d]["lp_change"] = day_data[d].get("lp_change", 0)

    days_list = []
    for d, stats in sorted(day_data.items()):
        wr = _win_rate(stats["wins"], stats["games"])
        days_list.append({
            "date": d,
            "games": stats["games"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": wr,
            "total_time_min": round(stats["total_time"] / 60),
            "lp_change": stats.get("lp_change", 0),
        })

    # 最佳/最差日
    valid_days = [d for d in days_list if d["games"] >= 2]
    best_day = max(valid_days, key=lambda d: d["win_rate"]) if valid_days else None
    worst_day = min(valid_days, key=lambda d: d["win_rate"]) if valid_days else None
    most_time_day = max(days_list, key=lambda d: d["total_time_min"]) if days_list else None

    # LP 变化
    lp_days = [d for d in days_list if d["lp_change"] != 0]
    most_gain_day = max(lp_days, key=lambda d: d["lp_change"]) if lp_days else None
    most_loss_day = min(lp_days, key=lambda d: d["lp_change"]) if lp_days else None

    # 出勤率
    first = matches[0]["_dt"]
    last = matches[-1]["_dt"]
    days_active = len(day_data)
    if first and last:
        days_since_first = (last - first).days + 1
    else:
        days_since_first = 0
    attendance = round(days_active / days_since_first * 100, 1) if days_since_first > 0 else 0

    if attendance >= 70:
        summary = f"你的出勤率高达 {attendance}%！{days_since_first} 天中有 {days_active} 天在召唤师峡谷战斗，堪称劳模。"
    elif attendance >= 40:
        summary = f"出勤率 {attendance}%，保持着健康的游戏频率，劳逸结合。"
    else:
        summary = f"出勤率 {attendance}%，你是个休闲玩家，但每一场都弥足珍贵。"

    if best_day:
        summary += f" {best_day['date']} 是你最辉煌的一天（{best_day['games']}场，胜率{best_day['win_rate']}%）。"

    return {
        "days": days_list,
        "best_day": best_day,
        "worst_day": worst_day,
        "most_time_day": most_time_day,
        "most_gain_day": most_gain_day,
        "most_loss_day": most_loss_day,
        "attendance": attendance,
        "days_active": days_active,
        "days_since_first": days_since_first,
        "summary": summary,
    }


# ── Session 分析 ─────────────────────────────────────────────────────────────

def _detect_sessions(matches: list[dict], gap_hours: float) -> list[list[dict]]:
    """按时间间隔检测连续游戏 session。"""
    valid = [m for m in matches if m["_dt"] is not None]
    if not valid:
        return []

    sessions = []
    current = [valid[0]]
    for i in range(1, len(valid)):
        gap = (valid[i]["_dt"] - valid[i-1]["_dt"]).total_seconds() / 3600
        if gap < gap_hours:
            current.append(valid[i])
        else:
            sessions.append(current)
            current = [valid[i]]
    sessions.append(current)
    return sessions


def _analyze_sessions(matches: list[dict], gap_hours: float = 3.0) -> dict:
    """连续游戏 Session 分析。"""
    sessions = _detect_sessions(matches, gap_hours)

    if not sessions:
        return {"total": 0, "summary": "暂无数据。"}

    session_stats = []
    for sess in sessions:
        wins = sum(1 for m in sess if m["win"])
        total_time = sum(m["game_time_played"] for m in sess)
        first_win = sess[0]["win"]
        last_win = sess[-1]["win"]
        last_end = sess[-1]["_dt"]
        last_end_hour = last_end.hour + last_end.minute / 60 if last_end else 0

        session_stats.append({
            "size": len(sess),
            "wins": wins,
            "losses": len(sess) - wins,
            "win_rate": _win_rate(wins, len(sess)),
            "total_time_min": round(total_time / 60),
            "first_win": first_win,
            "last_win": last_win,
            "last_end_hour": round(last_end_hour, 1),
            "start_time": sess[0]["_dt"].strftime("%m/%d %H:%M") if sess[0]["_dt"] else "",
        })

    # Session 规模分布
    size_dist = Counter(s["size"] for s in session_stats)
    size_labels = sorted(size_dist.keys())
    size_counts = [size_dist[s] for s in size_labels]

    # 最后一局结束时间分布
    hour_buckets = defaultdict(int)
    for s in session_stats:
        h = int(s["last_end_hour"])
        hour_buckets[h] += 1
    hour_labels = list(range(24))
    hour_counts = [hour_buckets.get(h, 0) for h in hour_labels]

    # 首局 vs 末局胜率
    first_wins = sum(1 for s in session_stats if s["first_win"])
    last_wins = sum(1 for s in session_stats if s["last_win"])
    total_s = len(session_stats)

    avg_size = statistics.mean([s["size"] for s in session_stats])
    max_size = max(s["size"] for s in session_stats)

    # 概要
    fw = _win_rate(first_wins, total_s)
    lw = _win_rate(last_wins, total_s)
    if lw > fw + 5:
        summary = f"你越打越热！Session 首局胜率仅 {fw}%，但末局提升到 {lw}%——需要热身时间。平均每次上线打 {avg_size:.1f} 局。"
    elif fw > lw + 5:
        summary = f"首局状态最佳（胜率 {fw}%），但随着体力下降末局跌至 {lw}%。建议控制每次游戏时长，见好就收。"
    else:
        summary = f"首局({fw}%)与末局({lw}%)胜率接近，状态保持稳定。平均每次上线打 {avg_size:.1f} 局，最长连续 {max_size} 局。"

    return {
        "total": len(session_stats),
        "avg_size": round(avg_size, 1),
        "max_size": max_size,
        "size_labels": size_labels,
        "size_counts": size_counts,
        "hour_labels": [f"{h}:00" for h in hour_labels],
        "hour_counts": hour_counts,
        "first_wr": fw,
        "last_wr": lw,
        "summary": summary,
    }


# ── 创意分析 ─────────────────────────────────────────────────────────────────

def _analyze_tilt(matches: list[dict]) -> dict:
    """心态/tilt 分析：输后胜率 vs 赢后胜率。"""
    if len(matches) < 2:
        return {"after_win": None, "after_loss": None, "after_2loss": None,
                "summary": "数据不足（需至少2场），无法进行 tilt 分析。"}

    after_win = {"wins": 0, "total": 0}
    after_loss = {"wins": 0, "total": 0}
    after_2loss = {"wins": 0, "total": 0}

    prev_results = []
    for m in matches:
        if len(prev_results) >= 1:
            if prev_results[-1]:
                after_win["total"] += 1
                if m["win"]:
                    after_win["wins"] += 1
            else:
                after_loss["total"] += 1
                if m["win"]:
                    after_loss["wins"] += 1
        if len(prev_results) >= 2:
            if not prev_results[-1] and not prev_results[-2]:
                after_2loss["total"] += 1
                if m["win"]:
                    after_2loss["wins"] += 1
        prev_results.append(m["win"])

    aw = _win_rate(after_win["wins"], after_win["total"])
    al = _win_rate(after_loss["wins"], after_loss["total"])
    a2 = _win_rate(after_2loss["wins"], after_2loss["total"])

    diff = round(aw - al, 1)
    if diff > 8:
        summary = f"赢后胜率 {aw}% 远高于输后 {al}%——你是典型的'顺风型'选手，心态受上一局影响明显。"
        if a2:
            summary += f" 连输两局后胜率更降至 {a2}%，建议连败后休息一下。"
    elif diff < -8:
        summary = f"有趣的发现：你输后胜率({al}%)反而高于赢后({aw}%)——越挫越勇型选手，需要'挫折'来激发潜力！"
    else:
        summary = f"赢后胜率({aw}%)与输后({al}%)相差仅 {abs(diff):.1f}%，心态稳定，不被上一局结果左右。"

    return {
        "after_win": {"games": after_win["total"], "wins": after_win["wins"], "wr": aw},
        "after_loss": {"games": after_loss["total"], "wins": after_loss["wins"], "wr": al},
        "after_2loss": {"games": after_2loss["total"], "wins": after_2loss["wins"], "wr": a2} if after_2loss["total"] > 0 else None,
        "summary": summary,
    }


def _analyze_streaks(matches: list[dict]) -> dict:
    """连胜/连败分析。"""
    if not matches:
        return {"longest_win": 0, "longest_loss": 0, "summary": "暂无数据。"}

    all_streaks = []
    current_type = None
    current_len = 0
    current_start = None
    current_end = None

    for m in matches:
        result = "win" if m["win"] else "loss"
        if result != current_type:
            if current_type:
                all_streaks.append({
                    "type": current_type, "length": current_len,
                    "start": current_start, "end": current_end,
                })
            current_type = result
            current_len = 1
            current_start = m["_dt"].strftime("%m/%d") if m["_dt"] else ""
            current_end = current_start
        else:
            current_len += 1
            current_end = m["_dt"].strftime("%m/%d") if m["_dt"] else ""

    if current_type:
        all_streaks.append({
            "type": current_type, "length": current_len,
            "start": current_start, "end": current_end,
        })

    win_streaks = [s for s in all_streaks if s["type"] == "win"]
    loss_streaks = [s for s in all_streaks if s["type"] == "loss"]

    longest_win = max(win_streaks, key=lambda s: s["length"]) if win_streaks else None
    longest_loss = max(loss_streaks, key=lambda s: s["length"]) if loss_streaks else None

    dist = []
    for stype in ["win", "loss"]:
        streaks_of_type = [s for s in all_streaks if s["type"] == stype]
        counter = Counter(s["length"] for s in streaks_of_type)
        for length in sorted(counter):
            dist.append({"type": stype, "length": length, "count": counter[length]})

    current = all_streaks[-1] if all_streaks else None

    if longest_win and longest_win["length"] >= 5:
        summary = f"最长连胜 {longest_win['length']} 局（{longest_win['start']} ~ {longest_win['end']}），那是一段值得怀念的上分之旅。"
    elif longest_loss and longest_loss["length"] >= 5:
        summary = f"最长连败 {longest_loss['length']} 局（{longest_loss['start']} ~ {longest_loss['end']}），那是峡谷给你上的最深刻一课。"
    elif longest_win:
        summary = f"最长连胜 {longest_win['length']} 局，最长连败 {longest_loss['length'] if longest_loss else 0} 局——输赢交替，这才是常态。"
    else:
        summary = "暂无足够的连势数据。"

    return {
        "longest_win": longest_win,
        "longest_loss": longest_loss,
        "current": current,
        "distribution": dist,
        "summary": summary,
    }


def _analyze_comebacks(matches: list[dict]) -> dict:
    """抗压分析：承受伤害最多但赢了。"""
    taken_games = [m for m in matches if m.get("most_taken")]
    not_taken = [m for m in matches if not m.get("most_taken")]

    taken_wr = _win_rate(sum(1 for m in taken_games if m["win"]), len(taken_games))
    not_wr = _win_rate(sum(1 for m in not_taken if m["win"]), len(not_taken))

    if len(taken_games) < 3:
        summary = "抗压样本不足，你很少成为队伍中承受伤害最多的那个。"
    elif taken_wr >= 50:
        summary = f"你扛伤最多时胜率反而达到 {taken_wr}%（{len(taken_games)}场）——不仅能抗，还能赢，这才是真正的坦克艺术。"
    else:
        summary = f"扛伤最多时胜率仅 {taken_wr}%（{len(taken_games)}场），被集火时队伍很难翻盘——注意站位和时机。"

    return {
        "taken_games": len(taken_games), "taken_wr": taken_wr,
        "not_games": len(not_taken), "not_wr": not_wr,
        "summary": summary,
    }


def _analyze_carry(matches: list[dict]) -> dict:
    """硬 Carry 分析：击杀最多+伤害最高。"""
    carry = [m for m in matches if m.get("most_kills") and m.get("most_damage")]
    non_carry = [m for m in matches if not (m.get("most_kills") and m.get("most_damage"))]

    carry_wr = _win_rate(sum(1 for m in carry if m["win"]), len(carry))
    non_wr = _win_rate(sum(1 for m in non_carry if m["win"]), len(non_carry))
    carry_pct = len(carry) / len(matches) * 100 if matches else 0

    if len(carry) < 3:
        summary = "你没有多少'完美carry局'（击杀+伤害双料第一），你可能更偏向团队配合型选手。"
    elif carry_wr >= 70:
        summary = f"当你打出'击杀+伤害双料 MVP'级表现时，胜率飙升至 {carry_wr}%（{len(carry)}场）——你就是队伍的绝对核心。"
    else:
        summary = f"即使击杀+伤害全队第一，胜率也只有 {carry_wr}%——这说明 LOL 是团队游戏，个人carry 不等于胜利。"

    return {
        "carry_games": len(carry), "carry_wr": carry_wr, "carry_pct": round(carry_pct, 1),
        "non_games": len(non_carry), "non_wr": non_wr,
        "summary": summary,
    }


def _analyze_support_carry(matches: list[dict]) -> dict:
    """助攻王分析。"""
    assist_games = [m for m in matches if m.get("most_assists")]
    non_assist = [m for m in matches if not m.get("most_assists")]

    a_wr = _win_rate(sum(1 for m in assist_games if m["win"]), len(assist_games))
    na_wr = _win_rate(sum(1 for m in non_assist if m["win"]), len(non_assist))

    if len(assist_games) < 3:
        summary = "你很少成为助攻王——你可能不是以助攻为核心打法的选手。"
    elif a_wr >= 60:
        summary = f"助攻最多时胜率高达 {a_wr}%（{len(assist_games)}场），证明你在团队中起到了关键的组织串联作用。"
    else:
        summary = f"助攻最多时胜率 {a_wr}%，有时光靠助攻还不足以赢下比赛。"

    return {
        "assist_games": len(assist_games), "assist_wr": a_wr,
        "non_games": len(non_assist), "non_wr": na_wr,
        "summary": summary,
    }


def _analyze_early_vs_late(matches: list[dict]) -> dict:
    """前期 vs 后期分析。"""
    if not matches:
        return {"quartiles": [], "summary": "暂无数据。"}

    sorted_by_dur = sorted(matches, key=lambda m: m["game_time_played"])
    n = len(sorted_by_dur)
    q_size = n // 4

    quartiles = []
    labels_cn = ["极早局 (Q1)", "偏早局 (Q2)", "偏晚局 (Q3)", "极晚局 (Q4)"]
    for qi in range(4):
        start = qi * q_size
        end = (qi + 1) * q_size if qi < 3 else n
        chunk = sorted_by_dur[start:end]
        if not chunk:
            continue
        wins = sum(1 for m in chunk if m["win"])
        dur_min = chunk[0]["game_time_played"] / 60
        dur_max = chunk[-1]["game_time_played"] / 60
        quartiles.append({
            "label": labels_cn[qi],
            "games": len(chunk),
            "wins": wins,
            "win_rate": _win_rate(wins, len(chunk)),
            "dur_min": round(dur_min, 1),
            "dur_max": round(dur_max, 1),
        })

    early_wr = quartiles[0]["win_rate"] if quartiles else 0
    late_wr = quartiles[-1]["win_rate"] if len(quartiles) >= 2 else early_wr
    diff = round(late_wr - early_wr, 1)

    if diff > 10:
        summary = f"你是典型的后期选手！极晚局胜率({late_wr}%)比极早局({early_wr}%)高出 {diff:.0f}%，游戏越拖越有优势。"
    elif diff < -10:
        summary = f"快攻是你的风格：极早局胜率({early_wr}%)远超极晚局({late_wr}%)，速战速决才是赢之道。"
    else:
        summary = f"前期和后期胜率差异不大（差 {abs(diff):.1f}%），你能适应各种节奏。"

    return {"quartiles": quartiles, "summary": summary}


def _analyze_consistency(matches: list[dict]) -> dict:
    """发挥稳定性分析。"""
    ranked = _filter_ranked(matches)
    if len(ranked) < 5:
        return {"kda_cv": 0, "score_cv": 0, "summary": "排位数据不足，无法评估发挥稳定性。"}

    kdas = [m["kda"] for m in ranked]
    scores = [m["game_score"] for m in ranked]

    kda_mean = statistics.mean(kdas)
    kda_stdev = statistics.stdev(kdas) if len(kdas) >= 2 else 0
    kda_cv = round(kda_stdev / kda_mean * 100, 1) if kda_mean > 0 else 0

    score_mean = statistics.mean(scores)
    score_stdev = statistics.stdev(scores) if len(scores) >= 2 else 0
    score_cv = round(score_stdev / score_mean * 100, 1) if score_mean > 0 else 0

    if kda_cv < 50:
        stability = "非常稳定"
    elif kda_cv < 80:
        stability = "较为稳定"
    elif kda_cv < 120:
        stability = "波动较大"
    else:
        stability = "大起大落"

    summary = f"你的发挥{stability}（KDA变异系数 {kda_cv}%），评分变异系数 {score_cv}%。"

    dist = []
    boundaries = [0, 1, 2, 3, 5, 10, float("inf")]
    b_labels = ["0-1", "1-2", "2-3", "3-5", "5-10", "10+"]
    for i, label in enumerate(b_labels):
        lo, hi = boundaries[i], boundaries[i+1]
        count = sum(1 for k in kdas if lo <= k < hi)
        dist.append({"label": label, "count": count})

    return {
        "kda_mean": round(kda_mean, 2), "kda_stdev": round(kda_stdev, 2),
        "kda_cv": kda_cv, "score_cv": score_cv,
        "kda_distribution": dist,
        "summary": summary,
    }


def _analyze_weekly_rhythm(matches: list[dict]) -> dict:
    """周游戏节奏。"""
    day_games = [0] * 7
    day_wins = [0] * 7
    for m in matches:
        if m["_dt"]:
            wd = m["_dt"].weekday()
            day_games[wd] += 1
            if m["win"]:
                day_wins[wd] += 1

    day_wr = [_win_rate(day_wins[i], day_games[i]) for i in range(7)]
    most_active = max(range(7), key=lambda i: day_games[i])
    most_winning = max(range(7), key=lambda i: day_wr[i] if day_games[i] > 0 else -1)

    summary = f"{_DAYS_CN[most_active]}是你最活跃的一天（{day_games[most_active]}场），"
    if day_games[most_winning] >= 3:
        summary += f"而{_DAYS_CN[most_winning]}胜率最高（{day_wr[most_winning]}%）。"

    return {
        "labels": _DAYS_CN, "games": day_games, "win_rates": day_wr,
        "most_active": _DAYS_CN[most_active], "most_winning": _DAYS_CN[most_winning],
        "summary": summary,
    }


def _analyze_position_flexibility(matches: list[dict]) -> dict:
    """位置灵活性分析。"""
    pos_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for m in matches:
        pos = m["position"] or "Invalid"
        pos_stats[pos]["total"] += 1
        if m["win"]:
            pos_stats[pos]["wins"] += 1

    if not pos_stats:
        return {"roles": [], "summary": "暂无位置数据。"}

    main_role = max(pos_stats, key=lambda p: pos_stats[p]["total"])
    main_wr = _win_rate(pos_stats[main_role]["wins"], pos_stats[main_role]["total"])
    main_games = pos_stats[main_role]["total"]

    off_wins = sum(s["wins"] for p, s in pos_stats.items() if p != main_role)
    off_total = sum(s["total"] for p, s in pos_stats.items() if p != main_role)
    off_wr = _win_rate(off_wins, off_total)

    pos_names = {"TOP": "上单", "JUNGLE": "打野", "MIDDLE": "中单",
                 "BOTTOM": "ADC", "UTILITY": "辅助", "Invalid": "未知"}
    roles = []
    for pos, stats in sorted(pos_stats.items(), key=lambda x: x[1]["total"], reverse=True):
        roles.append({
            "position": pos_names.get(pos, pos),
            "games": stats["total"], "wins": stats["wins"],
            "win_rate": _win_rate(stats["wins"], stats["total"]),
            "is_main": pos == main_role,
        })

    if off_total >= 3:
        if off_wr > main_wr + 5:
            summary = f"有趣！你客串其他位置时胜率({off_wr}%)反而高于主位置{pos_names.get(main_role, main_role)}({main_wr}%)。也许你应该考虑转位置？"
        elif main_wr > off_wr + 5:
            summary = f"你的主位置{pos_names.get(main_role, main_role)}胜率({main_wr}%)明显优于客串({off_wr}%)，专注本命位置才是上分之道。"
        else:
            summary = f"主位置和客串位置胜率接近（{main_wr}% vs {off_wr}%），你具备不错的位置灵活性。"
    else:
        summary = f"你几乎只玩{pos_names.get(main_role, main_role)}（{main_games}场），是个专一的单位置选手。"

    return {"roles": roles, "main_role": pos_names.get(main_role, main_role), "summary": summary}


def _analyze_surrender(matches: list[dict]) -> dict:
    """投降分析。"""
    surrenders = [m for m in matches if m["was_surrender"]]
    non_surrenders = [m for m in matches if not m["was_surrender"]]

    sr_rate = round(len(surrenders) / len(matches) * 100, 1) if matches else 0
    non_sr_wr = _win_rate(sum(1 for m in non_surrenders if m["win"]), len(non_surrenders))

    if sr_rate >= 20:
        summary = f"投降率 {sr_rate}% 偏高——你和队友可能容易心态崩溃。在非投降局中胜率达到 {non_sr_wr}%，坚持就有希望。"
    elif sr_rate >= 10:
        summary = f"投降率 {sr_rate}%，属于正常水平。非投降局胜率 {non_sr_wr}%。"
    else:
        summary = f"投降率仅 {sr_rate}%——你是个不轻言放弃的选手，非投降局胜率 {non_sr_wr}%，坚持是最好的翻盘策略。"

    return {
        "surrender_count": len(surrenders), "surrender_rate": sr_rate,
        "non_surrender_wr": non_sr_wr,
        "summary": summary,
    }


def _analyze_afk_impact(matches: list[dict]) -> dict:
    """AFK 影响分析。"""
    afk_games = [m for m in matches if m["was_afk"]]
    non_afk = [m for m in matches if not m["was_afk"]]

    afk_wr = _win_rate(sum(1 for m in afk_games if m["win"]), len(afk_games))
    non_afk_wr = _win_rate(sum(1 for m in non_afk if m["win"]), len(non_afk))

    if len(afk_games) == 0:
        summary = "你没有挂机记录，是一位守序的召唤师！"
    else:
        summary = f"有 {len(afk_games)} 场挂机记录——挂机局胜率仅 {afk_wr}%，非挂机局 {non_afk_wr}%。保持在线就是最好的上分策略。"

    return {
        "afk_games": len(afk_games), "afk_wr": afk_wr,
        "non_afk_games": len(non_afk), "non_afk_wr": non_afk_wr,
        "summary": summary,
    }


def _analyze_gold_efficiency(matches: list[dict]) -> dict:
    """金币效率分析。"""
    if not matches:
        return {"scatter": [], "summary": "暂无数据。"}

    scatter_win = []
    scatter_loss = []
    gpm_vals = []
    for m in matches:
        dur = max(m["game_time_played"] / 60, 1)
        gpm = m["gold_earned"] / dur
        gpm_vals.append(gpm)
        point = {"x": round(dur, 1), "y": round(gpm)}
        if m["win"]:
            scatter_win.append(point)
        else:
            scatter_loss.append(point)

    avg_gpm = round(statistics.mean(gpm_vals)) if gpm_vals else 0

    high_gpm = [m for i, m in enumerate(matches) if gpm_vals[i] >= 400]
    low_gpm = [m for i, m in enumerate(matches) if gpm_vals[i] < 400]
    high_wr = _win_rate(sum(1 for m in high_gpm if m["win"]), len(high_gpm))
    low_wr = _win_rate(sum(1 for m in low_gpm if m["win"]), len(low_gpm))

    if high_wr > low_wr + 10:
        summary = f"经济就是一切！每分钟金币 ≥400 时胜率 {high_wr}%，远高于低经济局 {low_wr}%。你的平均 GPM 为 {avg_gpm}。"
    else:
        summary = f"有趣的是，高经济局胜率({high_wr}%)与低经济局({low_wr}%)差距不大，说明经济优势不一定转化为胜势。平均 GPM: {avg_gpm}。"

    return {
        "scatter_win": scatter_win, "scatter_loss": scatter_loss,
        "avg_gpm": avg_gpm, "high_gpm_wr": high_wr, "low_gpm_wr": low_wr,
        "summary": summary,
    }


# ── HTML 生成 ────────────────────────────────────────────────────────────────

def _chart_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _build_css() -> str:
    return """
:root{
--bg:#0a0e14;--bg2:#141b22;--card:#1a2230;--card-hover:#212b38;
--border:#2a3a4a;--text:#d4d8dd;--text2:#8b95a5;--text3:#5a6575;
--gold:#c8aa6e;--blue:#0ac8b9;--green:#2ecc71;--red:#e74c3c;
--blue2:#4a9eff;--purple:#a855f7;--orange:#f59e0b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC",sans-serif;line-height:1.6;min-height:100vh}
a{color:var(--blue);text-decoration:none}
nav{position:sticky;top:0;z-index:100;background:rgba(10,14,20,0.95);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;gap:8px;overflow-x:auto;white-space:nowrap}
nav .logo{color:var(--gold);font-weight:700;font-size:16px;margin-right:16px}
nav a{color:var(--text2);font-size:13px;padding:6px 12px;border-radius:6px;transition:all .2s}
nav a:hover{color:var(--text);background:var(--card)}
main{max-width:1280px;margin:0 auto;padding:24px 20px 60px}
.hero{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:32px}
.hero-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px 18px;text-align:center;transition:transform .2s}
.hero-card:hover{transform:translateY(-2px)}
.hero-card .value{font-size:28px;font-weight:700;color:var(--gold)}
.hero-card .label{font-size:12px;color:var(--text2);margin-top:4px}
.hero-card.win .value{color:var(--green)}
.hero-card.loss .value{color:var(--red)}
.section{margin-bottom:40px}
.section-title{font-size:22px;font-weight:700;color:var(--gold);margin-bottom:8px;padding-bottom:8px;border-bottom:2px solid var(--border);display:flex;align-items:center;gap:10px}
.section-subtitle{font-size:13px;color:var(--text2);margin-bottom:16px}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}
@media(max-width:768px){.chart-grid{grid-template-columns:1fr}}
.chart-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;transition:border-color .2s}
.chart-card:hover{border-color:var(--gold)}
.chart-card h3{font-size:15px;font-weight:600;color:var(--text);margin-bottom:4px}
.chart-card .chart-wrap{position:relative;width:100%;margin:12px 0}
.chart-card .chart-wrap canvas{width:100%!important}
.chart-card .summary{font-size:13px;color:var(--gold);font-style:italic;margin-top:10px;padding-top:10px;border-top:1px solid var(--border);line-height:1.7}
.chart-card .summary.na{color:var(--text3)}
.chart-card.full{grid-column:1/-1}
.stat-row{display:flex;gap:24px;flex-wrap:wrap;margin:12px 0 20px}
.stat-item{background:var(--bg2);border-radius:8px;padding:8px 14px}
.stat-item .sv{font-weight:700;color:var(--blue)}
.stat-item .sl{font-size:11px;color:var(--text3);margin-left:4px}
footer{text-align:center;padding:32px 20px;color:var(--text3);font-size:12px;border-top:1px solid var(--border)}
footer span{color:var(--gold)}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
"""


def _build_nav() -> str:
    items = [
        ("#overview", "\U0001f4ca 总览"),
        ("#temporal", "\U0001f52e 胜率因子"),
        ("#champion", "\U0001f3c6 英雄"),
        ("#rank", "\U0001f4c8 段位"),
        ("#attendance", "\U0001f4c5 出勤"),
        ("#session", "\U0001f3ae Session"),
        ("#psychology", "\U0001f9e0 心理"),
        ("#performance", "\U0001f4b0 效率"),
    ]
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in items)
    return f'<nav><span class="logo">⚔️ LOLhistory</span>{links}</nav>'


def _build_hero(ov: dict) -> str:
    cards = [
        ("总场次", ov.get("total_games", 0), ""),
        ("胜率", f"{ov.get('win_rate', 0)}%", "win" if ov.get("win_rate", 0) >= 50 else "loss"),
        ("整体 KDA", ov.get("overall_kda", 0), ""),
        ("累计金币", f"{ov.get('total_gold', 0):,}", ""),
        ("总 MVP", ov.get("total_mvps", 0), ""),
        ("总 SVP", ov.get("total_svps", 0), ""),
        ("活跃天数", ov.get("days_active", 0), ""),
        ("出勤率", f"{ov.get('attendance', 0)}%", ""),
        ("最高段位", ov.get("highest_tier", "无"), ""),
        ("当前段位", ov.get("current_tier", "无"), ""),
        ("独特英雄", ov.get("unique_champions", 0), ""),
        ("招牌英雄", ov.get("most_played_champ_name", ""), ""),
    ]
    html_cards = ""
    for label, value, cls in cards:
        html_cards += f'<div class="hero-card {cls}"><div class="value">{value}</div><div class="label">{label}</div></div>'
    return f'<section id="overview"><div class="hero">{html_cards}</div></section>'


def _chart_card(title: str, chart_id: str, summary: str, full_width: bool = False) -> str:
    cls = "chart-card full" if full_width else "chart-card"
    no_data = "数据不足" in summary or "暂无数据" in summary
    summary_cls = "summary na" if no_data else "summary"
    return f"""<div class="{cls}">
<h3>{title}</h3>
<div class="chart-wrap"><canvas id="{chart_id}"></canvas></div>
<p class="{summary_cls}">{summary}</p>
</div>"""


def _build_section_temporal(r: dict) -> str:
    day = r.get("win_rate_by_day", {})
    hour = r.get("win_rate_by_hour", {})
    side = r.get("win_rate_by_side", {})
    pos = r.get("win_rate_by_position", {})
    kda = r.get("win_rate_by_kda", {})
    dur = r.get("win_rate_by_duration", {})
    mystery = r.get("mystery_factor", {})
    honors = r.get("honors_impact", {})
    cards = [
        _chart_card("📅 星期几胜率", "chart-day", day.get("summary", "")),
        _chart_card("🕐 游戏时段胜率", "chart-hour", hour.get("summary", "")),
        _chart_card("🔴🔵 红蓝方胜率", "chart-side", side.get("summary", "")),
        _chart_card("🎯 位置胜率", "chart-position", pos.get("summary", "")),
        _chart_card("⚔️ KDA 范围胜率", "chart-kda", kda.get("summary", "")),
        _chart_card("⏱️ 对局时长胜率", "chart-duration", dur.get("summary", "")),
        _chart_card("🔮 神秘因子：胜率极差排名", "chart-mystery", mystery.get("summary", ""), True),
        _chart_card("🏅 荣誉与胜率", "chart-honors", honors.get("summary", ""), True),
    ]
    return f'<section id="temporal" class="section"><div class="section-title">🔮 时间维度的神秘胜率因子</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_champion(r: dict) -> str:
    radar = r.get("champion_radar", {})
    pool = r.get("champion_pool", {})
    cards = [
        _chart_card("🎯 拿手英雄多维雷达", "chart-radar", radar.get("summary", ""), True),
        _chart_card("📚 英雄池分布", "chart-pool", pool.get("summary", ""), True),
    ]
    return f'<section id="champion" class="section"><div class="section-title">🏆 英雄分析</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_rank(r: dict) -> str:
    rp = r.get("rank_progression", {})
    cards = [
        _chart_card("📈 段位 LP 趋势", "chart-lp", rp.get("summary", ""), True),
        _chart_card("📉 10场滚动胜率", "chart-rolling-wr", "", True),
    ]
    return f'<section id="rank" class="section"><div class="section-title">📈 段位趋势</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_attendance(r: dict) -> str:
    att = r.get("attendance", {})
    summary = att.get("summary", "")
    best = att.get("best_day")
    worst = att.get("worst_day")
    most_t = att.get("most_time_day")
    most_g = att.get("most_gain_day")
    most_l = att.get("most_loss_day")
    key_days = ""
    if best:
        key_days += f'<div class="stat-item"><span class="sv">🏆 胜率最高日</span><span class="sl">{best["date"]} — {best["win_rate"]}% ({best["wins"]}W{best["losses"]}L)</span></div>'
    if worst:
        key_days += f'<div class="stat-item"><span class="sv">💔 胜率最低日</span><span class="sl">{worst["date"]} — {worst["win_rate"]}% ({worst["wins"]}W{worst["losses"]}L)</span></div>'
    if most_t:
        key_days += f'<div class="stat-item"><span class="sv">⏰ 最长游戏日</span><span class="sl">{most_t["date"]} — {most_t["total_time_min"]} 分钟</span></div>'
    if most_g:
        key_days += f'<div class="stat-item"><span class="sv">📈 上分最多日</span><span class="sl">{most_g["date"]} — LP +{most_g["lp_change"]}</span></div>'
    if most_l:
        key_days += f'<div class="stat-item"><span class="sv">📉 掉分最多日</span><span class="sl">{most_l["date"]} — LP {most_l["lp_change"]}</span></div>'
    cards = [
        f'<div class="chart-card full"><h3>📅 出勤日历热力图</h3><div id="cal-heatmap"></div><p class="summary">{summary}</p></div>',
    ]
    if key_days:
        cards.insert(0, f'<div class="chart-card full"><h3>🗓️ 关键日期</h3><div class="stat-row">{key_days}</div></div>')
    cards.append(_chart_card("📊 每日 LP 变化", "chart-daily-lp", "", True))
    return f'<section id="attendance" class="section"><div class="section-title">📅 出勤与日历</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_session(r: dict) -> str:
    sess = r.get("sessions", {})
    cards = [
        _chart_card("📏 Session 规模分布", "chart-session-size", sess.get("summary", "")),
        _chart_card("🌙 Session 最后一局结束时间", "chart-session-hour", ""),
        _chart_card("🎬 Session 首局 vs 末局胜率", "chart-session-wr", ""),
    ]
    return f'<section id="session" class="section"><div class="section-title">🎮 连续游戏 Session 分析</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_psychology(r: dict) -> str:
    tilt = r.get("tilt", {})
    streaks = r.get("streaks", {})
    comebacks = r.get("comebacks", {})
    carry = r.get("carry", {})
    supp = r.get("support_carry", {})
    early = r.get("early_vs_late", {})
    consistency = r.get("consistency", {})
    cards = [
        _chart_card("🎢 心态影响：输后 vs 赢后胜率", "chart-tilt", tilt.get("summary", "")),
        _chart_card("🔥 连势分析", "chart-streaks", streaks.get("summary", "")),
        _chart_card("🛡️ 抗压分析：挨打最多但赢了", "chart-comebacks", comebacks.get("summary", "")),
        _chart_card("⚡ 硬 Carry 分析", "chart-carry", carry.get("summary", "")),
        _chart_card("🤝 助攻王胜率", "chart-support", supp.get("summary", "")),
        _chart_card("⏳ 前期 vs 后期", "chart-earlylate", early.get("summary", "")),
        _chart_card("📊 发挥稳定性", "chart-consistency", consistency.get("summary", "")),
        _chart_card("📅 周节奏", "chart-weekly", r.get("weekly_rhythm", {}).get("summary", "")),
        _chart_card("🔄 位置灵活性", "chart-flex", r.get("position_flexibility", {}).get("summary", "")),
        _chart_card("🏳️ 投降分析", "chart-surrender", r.get("surrender", {}).get("summary", "")),
        _chart_card("🚫 AFK 影响", "chart-afk", r.get("afk_impact", {}).get("summary", "")),
    ]
    return f'<section id="psychology" class="section"><div class="section-title">🧠 心理与风格</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_performance(r: dict) -> str:
    gold = r.get("gold_efficiency", {})
    cards = [
        _chart_card("💰 金币效率：GPM vs 时长", "chart-gpm", gold.get("summary", ""), True),
    ]
    return f'<section id="performance" class="section"><div class="section-title">💰 经济效率</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_footer(games: int, export_time: str) -> str:
    return f"""<footer>
<p>由 <span>LOLhistory</span> 生成 · 共 {games} 场对局 · 导出时间 {export_time}</p>
<p style="margin-top:4px;font-size:11px">所有数据来源于 WeGame API，仅供个人参考。图表由 Chart.js 驱动。</p>
</footer>"""



# ── Chart.js 配置 ────────────────────────────────────────────────────────────

def _build_all_charts(r: dict) -> str:
    """生成所有 Chart.js 初始化代码。"""
    parts = []

    # 星期胜率
    day = r.get("win_rate_by_day", {})
    parts.append(f"""new Chart(document.getElementById('chart-day'),{{
  type:'bar',
  data:{{labels:{_chart_json(day.get('labels',[]))},
    datasets:[
      {{label:'Win Rate %',data:{_chart_json(day.get('win_rates',[]))},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1,yAxisID:'y'}},
      {{label:'Games',data:{_chart_json(day.get('games',[]))},backgroundColor:'rgba(168,85,247,0.3)',borderColor:'#a855f7',borderWidth:1,yAxisID:'y1',type:'line',tension:0.3}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{
      y:{{type:'linear',position:'left',title:{{display:true,text:'Win Rate %',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},max:100}},
      y1:{{type:'linear',position:'right',title:{{display:true,text:'Games',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{display:false}}}},
      x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}
    }}
  }}
}});""")

    # 时段胜率
    hour = r.get("win_rate_by_hour", {})
    parts.append(f"""new Chart(document.getElementById('chart-hour'),{{
  type:'line',
  data:{{labels:{_chart_json(hour.get('labels',[]))},
    datasets:[{{label:'Win Rate %',data:{_chart_json(hour.get('win_rates',[]))},borderColor:'#0ac8b9',backgroundColor:'rgba(10,200,185,0.1)',fill:true,tension:0.3,pointRadius:2}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{min:0,max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 红蓝方 doughnut
    side = r.get("win_rate_by_side", {})
    s_games = side.get("games", [0, 0])
    s_wins = side.get("wins", [0, 0])
    parts.append(f"""new Chart(document.getElementById('chart-side'),{{
  type:'doughnut',
  data:{{labels:{_chart_json(side.get('labels',[]))},
    datasets:[
      {{label:'Wins',data:{_chart_json(s_wins)},backgroundColor:['rgba(74,158,255,0.7)','rgba(231,76,60,0.7)'],borderColor:['#4a9eff','#e74c3c'],borderWidth:1}},
      {{label:'Losses',data:{_chart_json([s_games[0]-s_wins[0],s_games[1]-s_wins[1]])},backgroundColor:['rgba(74,158,255,0.2)','rgba(231,76,60,0.2)'],borderColor:['#4a9eff','#e74c3c'],borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:1.5,plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}}}}
}});""")

    # 位置胜率
    pos = r.get("win_rate_by_position", {})
    p_labels = pos.get("labels", [])
    n = len(p_labels)
    parts.append(f"""new Chart(document.getElementById('chart-position'),{{
  type:'bar',
  data:{{labels:{_chart_json(p_labels)},
    datasets:[{{label:'Win Rate %',data:{_chart_json(pos.get('win_rates',[]))},backgroundColor:{_chart_json([_CHART_COLORS[i%10] for i in range(n)])},borderColor:{_chart_json([_CHART_BORDERS[i%10] for i in range(n)])},borderWidth:1}}]
  }},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{display:false}}}},
    scales:{{x:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # KDA 范围
    kda = r.get("win_rate_by_kda", {})
    parts.append(f"""new Chart(document.getElementById('chart-kda'),{{
  type:'bar',
  data:{{labels:{_chart_json(kda.get('labels',[]))},
    datasets:[{{label:'Win Rate %',data:{_chart_json(kda.get('win_rates',[]))},backgroundColor:'rgba(245,158,11,0.7)',borderColor:'#f59e0b',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 时长胜率
    dur = r.get("win_rate_by_duration", {})
    parts.append(f"""new Chart(document.getElementById('chart-duration'),{{
  type:'bar',
  data:{{labels:{_chart_json(dur.get('labels',[]))},
    datasets:[{{label:'Win Rate %',data:{_chart_json(dur.get('win_rates',[]))},backgroundColor:'rgba(20,184,166,0.7)',borderColor:'#14b8a6',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 神秘因子
    mystery = r.get("mystery_factor", {})
    dims = mystery.get("dimensions", [])
    parts.append(f"""new Chart(document.getElementById('chart-mystery'),{{
  type:'bar',
  data:{{labels:{_chart_json([d['name'] for d in dims])},
    datasets:[{{label:'Win Rate Variance %',data:{_chart_json([d['variance'] for d in dims])},backgroundColor:'rgba(236,72,153,0.7)',borderColor:'#ec4899',borderWidth:1}}]
  }},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 荣誉影响
    honors = r.get("honors_impact", {})
    hlist = honors.get("honors", [])
    parts.append(f"""new Chart(document.getElementById('chart-honors'),{{
  type:'bar',
  data:{{labels:{_chart_json([h['name'] for h in hlist])},
    datasets:[
      {{label:'With Honor',data:{_chart_json([h['wr_with'] for h in hlist])},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'Without Honor',data:{_chart_json([h['wr_without'] for h in hlist])},backgroundColor:'rgba(231,76,60,0.4)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 英雄雷达
    radar = r.get("champion_radar", {})
    champs = radar.get("champions", [])
    dims_radar = radar.get("dimensions", [])
    radar_datasets = []
    for i, ch in enumerate(champs):
        vals = [ch["metrics"].get(d, 0) for d in dims_radar]
        color_key = _CHART_COLORS[i % 10]
        border_key = _CHART_BORDERS[i % 10]
        radar_datasets.append({
            "label": f"{ch['name']} ({ch['win_rate']}%)",
            "data": vals,
            "borderColor": border_key.replace("1.0", "0.8"),
            "backgroundColor": color_key.replace("0.8", "0.15"),
            "borderWidth": 2,
        })
    parts.append(f"""new Chart(document.getElementById('chart-radar'),{{
  type:'radar',
  data:{{labels:{_chart_json(dims_radar)},datasets:{_chart_json(radar_datasets)}}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:1.5,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{r:{{min:0,max:100,ticks:{{color:'#8b95a5',backdropColor:'transparent'}},grid:{{color:'#2a3a4a'}},pointLabels:{{color:'#8b95a5'}}}}}}
  }}
}});""")

    # 英雄池
    pool = r.get("champion_pool", {})
    freq = pool.get("freq", [])
    parts.append(f"""new Chart(document.getElementById('chart-pool'),{{
  type:'bar',
  data:{{labels:{_chart_json([f['name'] for f in freq])},
    datasets:[
      {{label:'Wins',data:{_chart_json([f['wins'] for f in freq])},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'Losses',data:{_chart_json([f['losses'] for f in freq])},backgroundColor:'rgba(231,76,60,0.4)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{x:{{stacked:true,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{stacked:true,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # LP 趋势
    rp = r.get("rank_progression", {})
    parts.append(f"""new Chart(document.getElementById('chart-lp'),{{
  type:'line',
  data:{{labels:{_chart_json(rp.get('labels',[]))},
    datasets:[{{label:'Cumulative LP',data:{_chart_json(rp.get('lp_values',[]))},borderColor:'#c8aa6e',backgroundColor:'rgba(200,170,110,0.1)',fill:true,tension:0.2,pointRadius:0}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'Synthetic LP',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5',maxTicksLimit:30}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 滚动胜率
    parts.append(f"""new Chart(document.getElementById('chart-rolling-wr'),{{
  type:'line',
  data:{{labels:{_chart_json(rp.get('labels',[]))},
    datasets:[
      {{label:'10-Game Rolling WR',data:{_chart_json(rp.get('rolling_wr',[]))},borderColor:'#0ac8b9',tension:0.3,pointRadius:0,fill:false}},
      {{label:'50% Baseline',data:{_chart_json([50]*len(rp.get('labels',[])))},borderColor:'rgba(255,255,255,0.2)',borderDash:[5,5],pointRadius:0,fill:false}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{min:0,max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5',maxTicksLimit:30}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 每日 LP 变化
    att = r.get("attendance", {})
    days = att.get("days", [])
    lp_labels = [d["date"] for d in days if d["lp_change"] != 0]
    lp_values = [d["lp_change"] for d in days if d["lp_change"] != 0]
    lp_colors = ["rgba(46,204,113,0.7)" if v >= 0 else "rgba(231,76,60,0.7)" for v in lp_values]
    parts.append(f"""new Chart(document.getElementById('chart-daily-lp'),{{
  type:'bar',
  data:{{labels:{_chart_json(lp_labels)},
    datasets:[{{label:'LP Change',data:{_chart_json(lp_values)},backgroundColor:{_chart_json(lp_colors)},borderWidth:0}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'LP Change',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5',maxTicksLimit:20}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Session 规模
    sess = r.get("sessions", {})
    parts.append(f"""new Chart(document.getElementById('chart-session-size'),{{
  type:'bar',
  data:{{labels:{_chart_json(sess.get('size_labels',[]))},
    datasets:[{{label:'Sessions',data:{_chart_json(sess.get('size_counts',[]))},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'Sessions',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'Games per Session',color:'#8b95a5'}}}}}}
  }}
}});""")

    # Session 结束时间
    parts.append(f"""new Chart(document.getElementById('chart-session-hour'),{{
  type:'bar',
  data:{{labels:{_chart_json(sess.get('hour_labels',[]))},
    datasets:[{{label:'Sessions',data:{_chart_json(sess.get('hour_counts',[]))},backgroundColor:'rgba(168,85,247,0.7)',borderColor:'#a855f7',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Session 首末局胜率
    parts.append(f"""new Chart(document.getElementById('chart-session-wr'),{{
  type:'bar',
  data:{{labels:['First Game','Last Game'],
    datasets:[{{label:'Win Rate %',data:{_chart_json([sess.get('first_wr',0),sess.get('last_wr',0)])},backgroundColor:['rgba(74,158,255,0.7)','rgba(245,158,11,0.7)'],borderColor:['#4a9eff','#f59e0b'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Tilt
    tilt = r.get("tilt", {})
    aw = tilt.get("after_win") or {}
    al = tilt.get("after_loss") or {}
    a2 = tilt.get("after_2loss") or {}
    tilt_labels = ["After Win", "After Loss"]
    tilt_data = [aw.get("wr", 0), al.get("wr", 0)]
    tilt_colors = ['rgba(46,204,113,0.7)', 'rgba(231,76,60,0.7)']
    tilt_borders = ['#2ecc71', '#e74c3c']
    if a2:
        tilt_labels.append("After 2+ Loss")
        tilt_data.append(a2.get("wr", 0))
        tilt_colors.append('rgba(155,89,182,0.7)')
        tilt_borders.append('#9b59b6')
    parts.append(f"""new Chart(document.getElementById('chart-tilt'),{{
  type:'bar',
  data:{{labels:{_chart_json(tilt_labels)},
    datasets:[{{label:'Win Rate %',data:{_chart_json(tilt_data)},backgroundColor:{_chart_json(tilt_colors)},borderColor:{_chart_json(tilt_borders)},borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 连势分布
    streaks = r.get("streaks", {})
    dist = streaks.get("distribution", [])
    win_d = [d for d in dist if d["type"] == "win"]
    loss_d = [d for d in dist if d["type"] == "loss"]
    wl = sorted(set(d["length"] for d in win_d))
    wc = [sum(d["count"] for d in win_d if d["length"] == l) for l in wl]
    ll_len = sorted(set(d["length"] for d in loss_d))
    lc = [sum(d["count"] for d in loss_d if d["length"] == l) for l in ll_len]
    all_len = sorted(set(wl + ll_len))
    w_fill = [wc[wl.index(l)] if l in wl else 0 for l in all_len]
    l_fill = [lc[ll_len.index(l)] if l in ll_len else 0 for l in all_len]
    lw = streaks.get("longest_win")
    ll = streaks.get("longest_loss")
    streak_title = streaks.get("summary", "")[:80]
    if lw:
        streak_title += f" | Best win: {lw['length']}"
    if ll:
        streak_title += f" | Worst loss: {ll['length']}"

    parts.append(f"""new Chart(document.getElementById('chart-streaks'),{{
  type:'bar',
  data:{{labels:{_chart_json([str(l)+'g' for l in all_len])},
    datasets:[
      {{label:'Win Streaks',data:{_chart_json(w_fill)},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'Loss Streaks',data:{_chart_json(l_fill)},backgroundColor:'rgba(231,76,60,0.7)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}},title:{{display:true,text:{_chart_json(streak_title)},color:'#c8aa6e',font:{{size:11}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Comebacks
    comebacks = r.get("comebacks", {})
    parts.append(f"""new Chart(document.getElementById('chart-comebacks'),{{
  type:'bar',
  data:{{labels:['Most Dmg Taken','Not Most Dmg'],
    datasets:[{{label:'Win Rate %',data:[{comebacks.get('taken_wr',0)},{comebacks.get('not_wr',0)}],backgroundColor:['rgba(155,89,182,0.7)','rgba(149,165,166,0.7)'],borderColor:['#9b59b6','#95a5a6'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Carry
    carry = r.get("carry", {})
    parts.append(f"""new Chart(document.getElementById('chart-carry'),{{
  type:'bar',
  data:{{labels:['Hard Carry','Not Carry'],
    datasets:[{{label:'Win Rate %',data:[{carry.get('carry_wr',0)},{carry.get('non_wr',0)}],backgroundColor:['rgba(241,196,15,0.7)','rgba(149,165,166,0.7)'],borderColor:['#f1c40f','#95a5a6'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Support carry
    supp = r.get("support_carry", {})
    parts.append(f"""new Chart(document.getElementById('chart-support'),{{
  type:'bar',
  data:{{labels:['Most Assists','Not Most Assists'],
    datasets:[{{label:'Win Rate %',data:[{supp.get('assist_wr',0)},{supp.get('non_wr',0)}],backgroundColor:['rgba(20,184,166,0.7)','rgba(149,165,166,0.7)'],borderColor:['#14b8a6','#95a5a6'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 前期 vs 后期
    early = r.get("early_vs_late", {})
    qs = early.get("quartiles", [])
    n_qs = len(qs)
    parts.append(f"""new Chart(document.getElementById('chart-earlylate'),{{
  type:'bar',
  data:{{labels:{_chart_json([q['label'] for q in qs])},
    datasets:[{{label:'Win Rate %',data:{_chart_json([q['win_rate'] for q in qs])},backgroundColor:{_chart_json([_CHART_COLORS[i%10] for i in range(n_qs)])},borderColor:{_chart_json([_CHART_BORDERS[i%10] for i in range(n_qs)])},borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 稳定性
    consistency = r.get("consistency", {})
    kd = consistency.get("kda_distribution", [])
    parts.append(f"""new Chart(document.getElementById('chart-consistency'),{{
  type:'bar',
  data:{{labels:{_chart_json([d['label'] for d in kd])},
    datasets:[{{label:'Games',data:{_chart_json([d['count'] for d in kd])},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'KDA',color:'#8b95a5'}}}}}}
  }}
}});""")

    # 周节奏
    weekly = r.get("weekly_rhythm", {})
    parts.append(f"""new Chart(document.getElementById('chart-weekly'),{{
  type:'bar',
  data:{{labels:{_chart_json(weekly.get('labels',[]))},
    datasets:[
      {{label:'Games',data:{_chart_json(weekly.get('games',[]))},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1,yAxisID:'y'}},
      {{label:'Win Rate %',data:{_chart_json(weekly.get('win_rates',[]))},borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,0.1)',type:'line',tension:0.3,yAxisID:'y1'}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{type:'linear',position:'left',ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y1:{{type:'linear',position:'right',max:100,ticks:{{color:'#8b95a5'}},grid:{{display:false}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 位置灵活性
    flex = r.get("position_flexibility", {})
    roles = flex.get("roles", [])
    flex_colors = ["rgba(46,204,113,0.7)" if ro["is_main"] else "rgba(74,158,255,0.7)" for ro in roles]
    parts.append(f"""new Chart(document.getElementById('chart-flex'),{{
  type:'bar',
  data:{{labels:{_chart_json([ro['position'] for ro in roles])},
    datasets:[{{label:'Win Rate %',data:{_chart_json([ro['win_rate'] for ro in roles])},backgroundColor:{_chart_json(flex_colors)},borderWidth:1}}]
  }},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{x:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 投降
    surr = r.get("surrender", {})
    total_g = r.get("overview", {}).get("total_games", 0)
    parts.append(f"""new Chart(document.getElementById('chart-surrender'),{{
  type:'doughnut',
  data:{{labels:['Surrendered','Fought On'],
    datasets:[{{data:[{surr.get('surrender_count',0)},{total_g - surr.get('surrender_count',0)}],backgroundColor:['rgba(231,76,60,0.7)','rgba(46,204,113,0.7)'],borderColor:['#e74c3c','#2ecc71'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:1.5,plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}}}}
}});""")

    # AFK
    afk = r.get("afk_impact", {})
    parts.append(f"""new Chart(document.getElementById('chart-afk'),{{
  type:'bar',
  data:{{labels:['AFK Games','Normal Games'],
    datasets:[{{label:'Win Rate %',data:[{afk.get('afk_wr',0)},{afk.get('non_afk_wr',0)}],backgroundColor:['rgba(231,76,60,0.7)','rgba(46,204,113,0.7)'],borderColor:['#e74c3c','#2ecc71'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # GPM 散点图
    gold = r.get("gold_efficiency", {})
    parts.append(f"""new Chart(document.getElementById('chart-gpm'),{{
  type:'scatter',
  data:{{datasets:[
    {{label:'Win',data:{_chart_json(gold.get('scatter_win',[]))},backgroundColor:'rgba(46,204,113,0.5)',borderColor:'#2ecc71',pointRadius:3}},
    {{label:'Loss',data:{_chart_json(gold.get('scatter_loss',[]))},backgroundColor:'rgba(231,76,60,0.5)',borderColor:'#e74c3c',pointRadius:3}}
  ]}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'GPM',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'Game Duration (min)',color:'#8b95a5'}}}}}}
  }}
}});""")

    return "\n".join(parts)

def _build_html(results: dict) -> str:
    ov = results.get("overview", {})
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css = _build_css()
    nav = _build_nav()
    hero = _build_hero(ov)
    sections = "".join([
        _build_section_temporal(results),
        _build_section_champion(results),
        _build_section_rank(results),
        _build_section_attendance(results),
        _build_section_session(results),
        _build_section_psychology(results),
        _build_section_performance(results),
    ])
    charts_js = _build_all_charts(results)
    footer = _build_footer(ov.get("total_games", 0), export_time)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOL 对局历史数据分析报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js">
</script>
<style>{css}</style>
</head>
<body>
{nav}
<main>
{hero}
{sections}
</main>
{footer}
<script>
{charts_js}
</script>
</body>
</html>"""


def _build_empty_report(db_path: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOL 分析报告 - 无数据</title>
<style>
body{{background:#0a0e14;color:#d4d8dd;font-family:"Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1a2230;border:1px solid #2a3a4a;border-radius:12px;padding:48px;text-align:center;max-width:500px}}
h1{{color:#c8aa6e;font-size:24px;margin:0 0 16px}}
p{{color:#8b95a5;line-height:1.8;margin:0}}
code{{background:#141b22;padding:2px 8px;border-radius:4px;color:#c8aa6e}}
</style>
</head>
<body>
<div class="card">
<h1>📊 暂无对局数据</h1>
<p>数据库 <code>{db_path}</code> 中未找到对局记录。</p>
<p>请先运行 <code>python -m lolhistory --cookies cookies.json</code> 获取对局历史，再执行分析。</p>
</div>
</body>
</html>"""


def generate_report(
    db_path: str = "wegame_matches.db",
    output_path: str = "lol_analysis_report.html",
    session_gap_hours: float = 3.0,
) -> str:
    db_abs = str(Path(db_path).resolve())
    if not Path(db_path).exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_abs}")
    matches = _load_matches(db_path)
    if not matches:
        html = _build_empty_report(db_abs)
        out = Path(output_path).resolve()
        out.write_text(html, encoding="utf-8")
        return str(out)
    overview = _analyze_overview(matches)
    results = {
        "overview": overview,
        "win_rate_by_day": _analyze_win_rate_by_day_of_week(matches),
        "win_rate_by_hour": _analyze_win_rate_by_hour(matches),
        "win_rate_by_side": _analyze_win_rate_by_team_side(matches),
        "win_rate_by_position": _analyze_win_rate_by_position(matches),
        "win_rate_by_kda": _analyze_win_rate_by_kda_range(matches),
        "win_rate_by_duration": _analyze_win_rate_by_duration(matches),
        "mystery_factor": _analyze_mystery_factor(matches),
        "honors_impact": _analyze_honors_impact(matches),
        "champion_radar": _analyze_champion_radar(matches),
        "champion_pool": _analyze_champion_pool(matches),
        "rank_progression": _analyze_rank_progression(matches),
        "attendance": _analyze_attendance(matches),
        "sessions": _analyze_sessions(matches, session_gap_hours),
        "tilt": _analyze_tilt(matches),
        "streaks": _analyze_streaks(matches),
        "comebacks": _analyze_comebacks(matches),
        "carry": _analyze_carry(matches),
        "support_carry": _analyze_support_carry(matches),
        "early_vs_late": _analyze_early_vs_late(matches),
        "consistency": _analyze_consistency(matches),
        "weekly_rhythm": _analyze_weekly_rhythm(matches),
        "position_flexibility": _analyze_position_flexibility(matches),
        "surrender": _analyze_surrender(matches),
        "afk_impact": _analyze_afk_impact(matches),
        "gold_efficiency": _analyze_gold_efficiency(matches),
    }
    html = _build_html(results)
    out = Path(output_path).resolve()
    out.write_text(html, encoding="utf-8")
    return str(out)
