"""数据分析与交互式 HTML 报告生成模块。

从 SQLite 数据库读取对局历史，进行多维度统计分析，
生成单个静态交互式 HTML 文件（Chart.js CDN）。
"""

import sqlite3
import json
import math
import statistics
from datetime import datetime
from collections import defaultdict, Counter
from pathlib import Path

from ._data import CHAMPION_DISPLAY, WEGAME_TIER_NAMES, get_season_name

# ── 常量 ────────────────────────────────────────────────────────────────────

# WeGame API 段位数值（字符串）→ (Riot 标准索引, 中文名)
# WeGame 使用与 Riot 不同的段位编号，所有赛季一致：
#   1=钻石(6), 2=铂金(4), 3=黄金(3), 4=白银(2), 5=青铜(1)
#   6=超凡大师(7), 7=傲世宗师(8), 8=最强王者(9), 9=翡翠(5)
# Riot 索引用于 _total_lp() 的段位排序计算。
_WEGAME_TIER_MAP: dict[str, tuple[int, str]] = {
    "1": (6, "钻石"),       # Diamond
    "2": (4, "铂金"),       # Platinum
    "3": (3, "黄金"),       # Gold
    "4": (2, "白银"),       # Silver
    "5": (1, "青铜"),       # Bronze（黑铁无独立值，合并于此）
    "6": (7, "超凡大师"),    # Master
    "7": (8, "傲世宗师"),    # Grandmaster
    "8": (9, "最强王者"),    # Challenger
    "9": (5, "翡翠"),       # Emerald（S13 新增）
}

# Riot 标准段位名称（按索引 0-9）
_TIER_NAMES: list[str] = [
    "Iron", "Bronze", "Silver", "Gold", "Platinum",
    "Emerald", "Diamond", "Master", "Grandmaster", "Challenger",
]
_TIER_NAMES_CN: list[str] = [
    "黑铁", "青铜", "白银", "黄金", "铂金",
    "翡翠", "钻石", "超凡大师", "傲世宗师", "最强王者",
]
_RANK_NAMES: dict[str, str] = {"0": "I", "1": "II", "2": "III", "3": "IV"}

# 段位序号映射（Riot 标准；WeGame 请使用 _wegame_tier_info()）
_TIER_INDEX: dict[str, int] = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}

# 英雄 ID → 名称映射已迁移至 _data.CHAMPION_DISPLAY（WeGame 官方配置）

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
    name = CHAMPION_DISPLAY.get(cid)
    if name:
        # 提取中文部分
        parts = name.split(" ", 1)
        return parts[1] if len(parts) > 1 else name
    return f"英雄{cid}"

def _champion_name_en(cid: int) -> str:
    """返回英雄英文名，未知则返回 ID。"""
    name = CHAMPION_DISPLAY.get(cid)
    if name:
        return name.split(" ", 1)[0]
    return f"Champion{cid}"

def _wegame_tier_info(tier_str: str) -> tuple[int, str] | None:
    """返回 WeGame 段位值对应的 (标准索引, 中文名)，未知则返回 None。"""
    if not tier_str or tier_str not in _WEGAME_TIER_MAP:
        return None
    return _WEGAME_TIER_MAP[tier_str]

def _tier_name(tier_str: str) -> str:
    """WeGame 段位数值→中文名。"""
    info = _wegame_tier_info(tier_str)
    if info:
        return info[1]
    # 回退：尝试标准 Riot 映射
    if tier_str and tier_str in _TIER_INDEX:
        return _TIER_NAMES_CN[_TIER_INDEX[tier_str]]
    return "无段位"

def _tier_rank_display(tier_str: str, rank_str: str) -> str:
    """段位+等级 显示文本，如 '钻石 II'、'超凡大师'。"""
    if not tier_str:
        return "无段位"
    info = _wegame_tier_info(tier_str)
    if info:
        idx, cn = info
        # 大师及以上无小段
        if idx >= 7:
            return cn
        rk = _RANK_NAMES.get(rank_str, "")
        return f"{cn} {rk}"
    # 回退：标准 Riot 映射
    if tier_str in _TIER_INDEX:
        idx = _TIER_INDEX[tier_str]
        cn = _TIER_NAMES_CN[idx]
        if idx >= 7:
            return cn
        rk = _RANK_NAMES.get(rank_str, "")
        return f"{cn} {rk}"
    return "无段位"

def _total_lp(tier_str: str, lp: int) -> int | None:
    """合成连续 LP 分数：标准段位索引 * 400 + LP。"""
    if not tier_str:
        return None
    info = _wegame_tier_info(tier_str)
    if info:
        return info[0] * 400 + (lp or 0)
    if tier_str in _TIER_INDEX:
        return _TIER_INDEX[tier_str] * 400 + (lp or 0)
    return None

def _win_rate(wins: int, total: int) -> float:
    """计算胜率百分比，保留一位小数。"""
    return round(wins / total * 100, 1) if total > 0 else 0.0

# ── 数据加载 ─────────────────────────────────────────────────────────────────

def _load_matches(db_path: str, area_ids: list[int] | None = None) -> list[dict]:
    """从 SQLite 加载 match_summary 行，按时间升序，可指定大区过滤。"""
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

    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM match_summary WHERE area IN ({placeholders}) "
            "ORDER BY game_start_time ASC",
            area_ids,
        )
    else:
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


def _load_champion_mastery(db_path: str, area_ids: list[int] | None = None) -> list[dict]:
    """从 SQLite 加载 champion_mastery 表数据，按总场次降序。"""
    if not Path(db_path).exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM champion_mastery")
        if cur.fetchone()[0] == 0:
            return []
    except sqlite3.OperationalError:
        return []

    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM champion_mastery WHERE area IN ({placeholders}) "
            "AND total_games > 0 ORDER BY total_games DESC",
            area_ids,
        )
    else:
        cur.execute("SELECT * FROM champion_mastery WHERE total_games > 0 ORDER BY total_games DESC")
    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def _load_season_history(db_path: str, area_ids: list[int] | None = None) -> list[dict]:
    """从 SQLite 加载 season_history 表数据，按赛季ID升序。"""
    if not Path(db_path).exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT COUNT(*) FROM season_history")
        if cur.fetchone()[0] == 0:
            return []
    except sqlite3.OperationalError:
        return []

    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM season_history WHERE area IN ({placeholders}) "
            "ORDER BY sid ASC",
            area_ids,
        )
    else:
        cur.execute("SELECT * FROM season_history ORDER BY sid ASC")
    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def _load_summoner_profile(db_path: str, area_ids: list[int] | None = None) -> dict | None:
    """从 SQLite 加载 summoner_profile 表数据（单行）。"""
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM summoner_profile")
        if cur.fetchone()[0] == 0:
            conn.close()
            return None
    except sqlite3.OperationalError:
        conn.close()
        return None
    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM summoner_profile WHERE area IN ({placeholders}) LIMIT 1",
            area_ids,
        )
    else:
        cur.execute("SELECT * FROM summoner_profile LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _load_career_overview(db_path: str, area_ids: list[int] | None = None) -> dict | None:
    """从 SQLite 加载 career_overview 表数据（单行）。"""
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM career_overview")
        if cur.fetchone()[0] == 0:
            conn.close()
            return None
    except sqlite3.OperationalError:
        conn.close()
        return None
    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM career_overview WHERE area IN ({placeholders}) LIMIT 1",
            area_ids,
        )
    else:
        cur.execute("SELECT * FROM career_overview LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _load_summoner_profiles_all(db_path: str, area_ids: list[int] | None = None) -> list[dict]:
    """从 SQLite 加载 summoner_profile 表数据（所有匹配大区的行，用于全区合并）。"""
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM summoner_profile")
        if cur.fetchone()[0] == 0:
            conn.close()
            return []
    except sqlite3.OperationalError:
        conn.close()
        return []
    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM summoner_profile WHERE area IN ({placeholders})",
            area_ids,
        )
    else:
        cur.execute("SELECT * FROM summoner_profile")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _load_career_overviews_all(db_path: str, area_ids: list[int] | None = None) -> list[dict]:
    """从 SQLite 加载 career_overview 表数据（所有匹配大区的行，用于全区合并）。"""
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM career_overview")
        if cur.fetchone()[0] == 0:
            conn.close()
            return []
    except sqlite3.OperationalError:
        conn.close()
        return []
    if area_ids:
        placeholders = ", ".join("?" * len(area_ids))
        cur.execute(
            f"SELECT * FROM career_overview WHERE area IN ({placeholders})",
            area_ids,
        )
    else:
        cur.execute("SELECT * FROM career_overview")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ── 全区数据合并函数 ─────────────────────────────────────────────────────────

def _merge_champion_mastery(rows: list[dict]) -> list[dict]:
    """合并多个大区的英雄熟练度数据。

    按 champion_id 分组：场次求和、胜率重新计算、熟练度取最大、分路合并去重。
    """
    if not rows:
        return []

    merged: dict[int, dict] = {}
    for c in rows:
        cid = c.get("champion_id", 0)
        if not cid:
            continue
        if cid not in merged:
            merged[cid] = dict(c)
            continue
        m = merged[cid]
        m["total_games"] = (m.get("total_games", 0) or 0) + (c.get("total_games", 0) or 0)
        m["wins"] = (m.get("wins", 0) or 0) + (c.get("wins", 0) or 0)
        m["mastery_exp"] = max(m.get("mastery_exp", 0) or 0, c.get("mastery_exp", 0) or 0)
        m["expire_day"] = max(m.get("expire_day", 0) or 0, c.get("expire_day", 0) or 0)
        if not m.get("instance_id") and c.get("instance_id"):
            m["instance_id"] = c["instance_id"]
        m["sid_total"] = (m.get("sid_total", 0) or 0) + (c.get("sid_total", 0) or 0)
        m["sid_wins"] = (m.get("sid_wins", 0) or 0) + (c.get("sid_wins", 0) or 0)
        m["sid_exp"] = (m.get("sid_exp", 0) or 0) + (c.get("sid_exp", 0) or 0)
        # 合并常用分路 JSON
        lanes_merged = []
        try:
            lanes_merged.extend(json.loads(m.get("lanes_json", "[]") or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            lanes_merged.extend(json.loads(c.get("lanes_json", "[]") or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        if lanes_merged:
            seen = set()
            unique = []
            for lane in lanes_merged:
                if lane not in seen:
                    seen.add(lane)
                    unique.append(lane)
            m["lanes_json"] = json.dumps(unique, ensure_ascii=False)
        # area 设为 0 表示全区合并
        m["area"] = 0

    # 重新计算胜率，按 total_games 降序排列
    result = []
    for m in merged.values():
        total = max(m.get("total_games", 0) or 0, 1)
        m["win_rate"] = round((m.get("wins", 0) or 0) / total * 100, 1)
        result.append(m)

    result.sort(key=lambda x: x.get("total_games", 0) or 0, reverse=True)
    return result


def _merge_season_history(rows: list[dict]) -> list[dict]:
    """合并多个大区的赛季历史数据。

    按 sid 分组：场次求和、段位取场次最多的大区。
    """
    if not rows:
        return []

    # 第一遍：分组累加场次 + 追踪段位来源
    merged: dict[int, dict] = {}
    # sid → (max_solo_total, best_row_for_solo)
    best_solo: dict[int, tuple[int, dict]] = {}
    # sid → (max_team_total, best_row_for_team)
    best_team: dict[int, tuple[int, dict]] = {}

    for s in rows:
        sid = s.get("sid", 0)
        if not sid:
            continue

        # 追踪单双排段位最佳来源
        solo_total = s.get("total_games", 0) or 0
        if sid not in best_solo or solo_total > best_solo[sid][0]:
            best_solo[sid] = (solo_total, s)

        # 追踪组排段位最佳来源
        team_total = s.get("team_total", 0) or 0
        if sid not in best_team or team_total > best_team[sid][0]:
            best_team[sid] = (team_total, s)

        if sid not in merged:
            merged[sid] = dict(s)
            continue

        m = merged[sid]
        m["total_games"] = (m.get("total_games", 0) or 0) + solo_total
        m["wins"] = (m.get("wins", 0) or 0) + (s.get("wins", 0) or 0)
        m["losses"] = (m.get("losses", 0) or 0) + (s.get("losses", 0) or 0)
        m["team_total"] = (m.get("team_total", 0) or 0) + team_total
        m["team_wins"] = (m.get("team_wins", 0) or 0) + (s.get("team_wins", 0) or 0)
        m["team_losses"] = (m.get("team_losses", 0) or 0) + (s.get("team_losses", 0) or 0)

    # 回填段位（取场次最多的大区）
    for sid, m in merged.items():
        if sid in best_solo:
            best = best_solo[sid][1]
            m["tier"] = best.get("tier", 255)
            m["win_point"] = best.get("win_point", 0)
            m["queue"] = best.get("queue", 0)
        if sid in best_team:
            best = best_team[sid][1]
            m["team_tier"] = best.get("team_tier", 255)
            m["team_win_point"] = best.get("team_win_point", 0)
            m["team_queue"] = best.get("team_queue", 0)
        m["area"] = 0

    return sorted(merged.values(), key=lambda x: x.get("sid", 0))


def _merge_summoner_profiles(profiles: list[dict]) -> dict | None:
    """合并多个大区的召唤师资料。

    身份标识取场次最多的大区、累计字段求和、极值字段取最大/最小。
    """
    if not profiles:
        return None

    # 选取代表大区（season_total 最大）
    representative = max(profiles, key=lambda p: p.get("season_total", 0) or 0)

    merged: dict = {}

    # ── 身份标识（取代表大区） ──
    for key in ("puin", "summoner_id", "summoner_name", "name_tag",
                "icon_id", "openid"):
        merged[key] = representative.get(key)

    # ── 等级/经验（取最大值） ──
    merged["level"] = max((p.get("level", 0) or 0) for p in profiles)
    merged["experience"] = max((p.get("experience", 0) or 0) for p in profiles)

    # ── 荣誉（求和） ──
    merged["praise"] = sum(p.get("praise", 0) or 0 for p in profiles)
    merged["discredit"] = sum(p.get("discredit", 0) or 0 for p in profiles)

    # ── 布尔 OR ──
    merged["top_of_canyon"] = 1 if any(p.get("top_of_canyon", 0) for p in profiles) else 0

    # ── 赛季快照（取代表大区） ──
    for key in ("season_sid", "season_tier", "season_win_point", "season_queue"):
        merged[key] = representative.get(key)

    # ── 赛季累计（求和） ──
    for key in ("season_total", "season_wins", "season_losses"):
        merged[key] = sum(p.get(key, 0) or 0 for p in profiles)

    # ── 近30天（求和） ──
    for key in ("kill_30days", "death_30days", "assist_30days",
                "recent_win_times", "recent_play_times"):
        merged[key] = sum(p.get(key, 0) or 0 for p in profiles)

    # ── 近30天 KDA（重新计算） ──
    k = merged.get("kill_30days", 0) or 0
    d = merged.get("death_30days", 0) or 0
    a = merged.get("assist_30days", 0) or 0
    merged["recent_kda_score"] = round((k + a) / max(d, 1), 2)

    # ── 近30天最新对局（取时间最新的） ──
    latest = max(profiles, key=lambda p: p.get("last_game_time", "") or "")
    merged["last_game_id"] = latest.get("last_game_id", "")
    merged["last_game_time"] = latest.get("last_game_time", "")

    # ── 常用英雄/位置（JSON 合并去重） ──
    champs_merged: list = []
    positions_merged: list = []
    for p in profiles:
        try:
            champs_merged.extend(json.loads(p.get("common_champions", "[]") or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            positions_merged.extend(json.loads(p.get("common_positions", "[]") or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
    merged["common_champions"] = json.dumps(champs_merged, ensure_ascii=False)
    merged["common_positions"] = json.dumps(positions_merged, ensure_ascii=False)

    # ── 生涯累计（求和） ──
    for key in ("total_mvp_times", "total_svp_times", "total_god_likes",
                "total_penta_kills", "total_quadra_kills", "total_triple_kills",
                "total_kills", "total_assists", "total_ward_placed"):
        merged[key] = sum(p.get(key, 0) or 0 for p in profiles)

    # ── 生涯极值（取最大值） ──
    for key in ("max_consecutive_wins", "highest_game_score",
                "most_kills_num", "most_assists_num", "most_spree_kills_num",
                "most_damage_num", "most_damage_taken_num", "most_gold_earned_num",
                "most_minions_kill_num", "most_turrets_kill_num", "longest_game_num"):
        merged[key] = max((p.get(key, 0) or 0) for p in profiles)

    # ── 最短对局（排除 0 后取最小值） ──
    shortest_vals = [p.get("shortest_game_num", 0) or 0 for p in profiles if (p.get("shortest_game_num", 0) or 0) > 0]
    merged["shortest_game_num"] = min(shortest_vals) if shortest_vals else 0

    # ── 元数据 ──
    merged["area"] = 0
    merged["last_fetch_time"] = latest.get("last_fetch_time", "")

    return merged


def _merge_career_overviews(overviews: list[dict]) -> dict | None:
    """合并多个大区的生涯总览数据。所有数值字段直接求和。"""
    if not overviews:
        return None

    sum_keys = (
        "total_match_games", "total_match_wins", "total_match_losses",
        "total_aram_games", "total_aram_wins", "total_aram_losses",
        "total_rank_games", "total_rank_wins", "total_rank_losses",
        "total_teamrank_games", "total_teamrank_wins", "total_teamrank_losses",
        "total_all_games", "total_all_wins", "total_all_losses",
        "total_ai_games", "total_ai_wins", "total_clash_games",
    )

    merged: dict = {"area": 0}
    for ov in overviews:
        for key in sum_keys:
            merged[key] = merged.get(key, 0) + (ov.get(key, 0) or 0)

    # 保留其他非数值字段（如 puin）从第一个复制
    first = overviews[0]
    for key in ("puin", "last_fetch_time"):
        if key in first:
            merged[key] = first[key]

    return merged


def _filter_ranked(matches: list[dict]) -> list[dict]:
    """仅保留排位单双排 (queue_id=420)。"""
    return [m for m in matches if m.get("game_queue_id") == 420]

# ── 总览分析 ─────────────────────────────────────────────────────────────────

def _analyze_overview(matches: list[dict], summoner_profile: dict | None = None) -> dict:
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

    avg_kills = round(total_kills / total, 1) if total > 0 else 0
    avg_deaths = round(total_deaths / total, 1) if total > 0 else 0
    avg_assists = round(total_assists / total, 1) if total > 0 else 0
    avg_gold = round(total_gold / total) if total > 0 else 0
    max_kills = max(m["kills"] for m in matches) if matches else 0
    # 生涯单局最高击杀（WeGame profile 数据优先）
    if summoner_profile:
        career_max = summoner_profile.get("most_kills_num", 0) or 0
        max_kills = max(max_kills, career_max)
        max_turrets = summoner_profile.get("most_turrets_kill_num", 0) or 0
    else:
        max_turrets = 0

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

    # 最高段位（含胜点）
    highest_total_lp = -1
    highest_tier_display = "无段位"
    highest_lp = 0
    current_total_lp = -1
    current_tier_display = "无段位"
    current_lp = 0
    for m in ranked:
        tlp = _total_lp(m.get("tier", ""), m.get("league_points", 0))
        if tlp is not None and tlp > highest_total_lp:
            highest_total_lp = tlp
            highest_tier_display = _tier_rank_display(m.get("tier", ""), m.get("rank", ""))
            highest_lp = m.get("league_points", 0)
    if ranked:
        last_r = ranked[-1]
        current_total_lp = _total_lp(last_r.get("tier", ""), last_r.get("league_points", 0))
        current_tier_display = _tier_rank_display(last_r.get("tier", ""), last_r.get("rank", ""))
        current_lp = last_r.get("league_points", 0)
    # 最高段位加入胜点
    if highest_lp > 0 and highest_tier_display != "无段位":
        highest_tier_display = f"{highest_tier_display} ({highest_lp}胜点)"
    if current_lp > 0 and current_tier_display != "无段位":
        current_tier_display = f"{current_tier_display} ({current_lp}胜点)"

    # 最常用英雄
    champ_counts = Counter(m["champion_id"] for m in matches)
    most_played = champ_counts.most_common(1)[0] if champ_counts else (0, 0)

    # 英雄池：胜场至少为10的英雄的数量
    champ_win_counts = Counter(m["champion_id"] for m in matches if m["win"])
    hero_pool = sum(1 for cnt in champ_win_counts.values() if cnt >= 10)
    # 位置灵活度：仅计召唤师峡谷中胜场≥20的位置
    pos_win_counts = Counter(m["position"] for m in matches if m["win"] and m.get("map_id") == 11)
    unique_positions = sum(1 for cnt in pos_win_counts.values() if cnt >= 20)

    # 最长连胜（比赛历史）
    longest_win_streak = 0
    cur_streak = 0
    for m in matches:
        if m["win"]:
            cur_streak += 1
            longest_win_streak = max(longest_win_streak, cur_streak)
        else:
            cur_streak = 0

    # 整体评价（含3个突出指标评论）
    if wr >= 55:
        rating = "⭐ 强势上分选手——胜率稳健，实力远超当前段位。"
    elif wr >= 50:
        rating = f"📈 稳中有升——在 {current_tier_display} 保持正向胜率，继续打磨即可更进一步。"
    elif wr >= 45:
        rating = "⚖️ 均势选手——胜率接近五成，需要找到突破瓶颈的关键维度。"
    else:
        rating = "📉 需要调整——胜率偏低，建议从下方分析中找出拖累胜率的核心因子。"

    # 挑选6个最值得评论的突出指标
    metric_comments = []
    # 招牌英雄（必定点名）
    cname_early = _champion_name(most_played[0])
    metric_comments.append(f"招牌英雄{cname_early}（{most_played[1]}场）")
    # 英雄池
    if hero_pool >= 5:
        metric_comments.append(f"英雄池深达{hero_pool}个高胜率英雄，BP阶段难以被针对")
    elif hero_pool == 1:
        metric_comments.append("绝活专精玩家，一招鲜吃遍天")
    # MVP率
    mvp_rate = round(total_mvps / total * 100, 1) if total > 0 else 0
    if mvp_rate >= 10:
        metric_comments.append(f"MVP率高达{mvp_rate}%，在队伍中经常扮演关键角色")
    elif mvp_rate >= 5:
        metric_comments.append(f"MVP率{mvp_rate}%，时有亮眼发挥")
    # SVP率
    svp_rate = round(total_svps / total * 100, 1) if total > 0 else 0
    if svp_rate >= 15:
        metric_comments.append(f"SVP率达{svp_rate}%（{total_svps}次），实力在线但团队配合欠佳")
    # 最长连胜
    if longest_win_streak >= 10:
        metric_comments.append(f"最长打出过{longest_win_streak}连胜，上分爆发力强")
    # 综合KDA
    if overall_kda >= 3:
        metric_comments.append(f"综合KDA高达{overall_kda}，击杀参与度高且死亡控制得当")
    # 五杀
    if total_penta >= 5:
        metric_comments.append(f"斩获{total_penta}次五杀，团战收割能力极强")
    # 四杀
    if total_quadra >= 5:
        metric_comments.append(f"斩获{total_quadra}次四杀，离五杀只差临门一脚")
    # 位置灵活度（仅计胜场≥20的位置）
    if unique_positions >= 4:
        metric_comments.append(f"横跨{unique_positions}个位置，阵容适配力极强")
    # 场均击杀
    if avg_kills >= 8:
        metric_comments.append(f"场均{avg_kills}击杀，线上压制力拉满")
    # 单局最高击杀
    if max_kills >= 20:
        metric_comments.append(f"单局最高斩获{max_kills}杀，个人能力上限极高")
    # 单局最多推塔
    if max_turrets >= 8:
        metric_comments.append(f"单局最多推塔{max_turrets}座，拆塔机器般的推进节奏")
    # 出勤率
    if attendance >= 50:
        metric_comments.append(f"出勤率高达{attendance}%，游戏习惯规律稳定")
    # 取前6个，用中文分号分隔
    highlight = "；".join(metric_comments[:6])
    if highlight:
        rating += f" {highlight}。"

    # 概要
    summary = (
        f"共 {total} 场对局（{days_active} 个活跃日），胜率 {wr}%，整体 KDA {overall_kda}。"
        f"招牌英雄 {cname_early}（{most_played[1]}场），当前段位 {current_tier_display}。"
        f"场均 {avg_kills} 杀 / {avg_deaths} 死 / {avg_assists} 助攻，场均经济 {avg_gold:,} 金币，"
        f"{total_mvps} 次 MVP，{total_svps} 次 SVP。"
    )

    return {
        "total_games": total, "wins": wins, "losses": losses, "win_rate": wr,
        "total_kills": total_kills, "total_deaths": total_deaths, "total_assists": total_assists,
        "overall_kda": overall_kda, "total_gold": total_gold,
        "total_mvps": total_mvps, "total_svps": total_svps,
        "total_surrenders": total_surrenders, "total_afks": total_afks,
        "total_penta": total_penta, "total_quadra": total_quadra,
        "avg_kills": avg_kills, "avg_deaths": avg_deaths, "avg_assists": avg_assists,
        "avg_gold": avg_gold,
        "first_date": first_date.strftime("%Y-%m-%d") if first_date else "",
        "last_date": last_date.strftime("%Y-%m-%d") if last_date else "",
        "days_active": days_active, "days_since_first": days_since_first,
        "attendance": attendance,
        "highest_tier": highest_tier_display, "current_tier": current_tier_display,
        "most_played_champ": most_played[0], "most_played_champ_name": cname_early,
        "most_played_games": most_played[1],
        "hero_pool": hero_pool, "unique_positions": unique_positions,
        "longest_win_streak": longest_win_streak, "max_kills": max_kills,
        "max_turrets": max_turrets,
        "overall_rating": rating,
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
    """按小时分析胜率（仅显示 >10 场的时段胜率）。"""
    hour_stats = {h: {"wins": 0, "total": 0} for h in range(24)}
    for m in matches:
        if m["_dt"]:
            h = m["_dt"].hour
            hour_stats[h]["total"] += 1
            if m["win"]:
                hour_stats[h]["wins"] += 1

    labels = [f"{h}:00" for h in range(24)]
    # 只有 >10 场的时段才显示胜率，否则为 None
    win_rates_display = []
    for h in range(24):
        t = hour_stats[h]["total"]
        if t > 10:
            win_rates_display.append(_win_rate(hour_stats[h]["wins"], t))
        else:
            win_rates_display.append(None)
    games = [hour_stats[h]["total"] for h in range(24)]

    valid = [(h, _win_rate(hour_stats[h]["wins"], hour_stats[h]["total"]), games[h])
             for h in range(24) if games[h] > 10]
    if valid:
        best = max(valid, key=lambda x: x[1])
        worst = min(valid, key=lambda x: x[1])
        best_g = games[best[0]]
        worst_g = games[worst[0]]
        summary = f"你的黄金时段是 {best[0]}:00（胜率 {best[1]}%，{best_g}场），而 {worst[0]}:00 胜率仅 {worst[1]}%（{worst_g}场）——也许深夜排位不是好主意？"
    else:
        summary = "各时段数据量不足（需要 >10 场），尚无法确定你的最佳游戏时间。"

    return {"labels": labels, "win_rates": win_rates_display, "games": games, "summary": summary}

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
        "BOTTOM": "ADC", "UTILITY": "辅助", "Invalid": "乱斗",
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

def _analyze_win_rate_by_lp_range(matches: list[dict]) -> dict:
    """按当前 LP 区间分析胜率（仅排位）。"""
    ranked = _filter_ranked(matches)
    if not ranked:
        return {"labels": [], "win_rates": [], "games": [], "summary": "排位数据不足。"}

    buckets = [
        ("0-20 LP", 0, 20), ("20-40 LP", 20, 40), ("40-60 LP", 40, 60),
        ("60-80 LP", 60, 80), ("80-100 LP", 80, 101),
    ]
    bucket_stats = {b[0]: {"wins": 0, "total": 0} for b in buckets}
    for m in ranked:
        lp = m.get("league_points", 0) or 0
        for label, lo, hi in buckets:
            if lo <= lp < hi:
                bucket_stats[label]["total"] += 1
                if m["win"]:
                    bucket_stats[label]["wins"] += 1
                break

    labels = [b[0] for b in buckets]
    win_rates = [_win_rate(bucket_stats[l]["wins"], bucket_stats[l]["total"]) for l in labels]
    games = [bucket_stats[l]["total"] for l in labels]

    # 洞察：晋级边缘（80-100 LP）vs 低 LP
    high_lp = bucket_stats["80-100 LP"]
    low_lp = bucket_stats["0-20 LP"]
    high_wr = _win_rate(high_lp["wins"], high_lp["total"])
    low_wr = _win_rate(low_lp["wins"], low_lp["total"])

    if high_wr > low_wr + 10 and high_lp["total"] >= 3:
        summary = f"晋级边缘（80-100 LP）胜率高达 {high_wr}%，越是关键局你越能站出来！"
    elif low_wr > high_wr + 10 and low_lp["total"] >= 3:
        summary = f"有趣——你在低 LP 区间（{low_wr}%）反而比晋级边缘（{high_wr}%）打得好，或许是晋级压力影响了发挥？"
    else:
        summary = f"各 LP 区间表现接近（高分段 {high_wr}% vs 低分段 {low_wr}%），心态不会随 LP 波动。"

    return {"labels": labels, "win_rates": win_rates, "games": games, "summary": summary}

def _analyze_win_rate_by_duration(matches: list[dict]) -> dict:
    """按对局时长分桶分析胜率。"""
    durations = [m["game_time_played"] / 60 for m in matches]
    if not durations:
        return {"labels": [], "win_rates": [], "games": [], "scatter": [], "summary": "暂无数据。"}

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

    # 小时（仅考虑 >10 场的时段）
    hour = _analyze_win_rate_by_hour(matches)
    hour_valid = [wr for wr, g in zip(hour["win_rates"], hour["games"]) if wr is not None and g > 10]
    if len(hour_valid) >= 2:
        dimensions.append({"name": "游戏时段", "variance": round(max(hour_valid) - min(hour_valid), 1)})

    # 红蓝方
    side = _analyze_win_rate_by_team_side(matches)
    dimensions.append({"name": "红蓝方", "variance": round(abs(side["win_rates"][0] - side["win_rates"][1]), 1)})

    # 位置（排除场次 < 5 的位置）
    pos = _analyze_win_rate_by_position(matches)
    pos_valid = [wr for wr, g in zip(pos["win_rates"], pos["games"]) if g >= 5]
    if len(pos_valid) >= 2:
        dimensions.append({"name": "位置", "variance": round(max(pos_valid) - min(pos_valid), 1)})

    # LP区间（替代KDA）
    lp_r = _analyze_win_rate_by_lp_range(matches)
    lp_valid = [wr for wr, g in zip(lp_r["win_rates"], lp_r["games"]) if g > 0]
    if len(lp_valid) >= 2:
        dimensions.append({"name": "LP区间", "variance": round(max(lp_valid) - min(lp_valid), 1)})

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
        elif top["name"] == "LP区间":
            summary += " 关键局的发挥决定了你的上分效率。"
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
        summary += f"当你成为{best['tag']}时（{best['games_with']}场），队伍基本锁定胜局。"
    else:
        summary = "各项荣誉与胜率关联较为均衡，你的打法偏向团队协作而非个人carry。"

    return {"honors": results, "summary": summary}

# ── 英雄分析 ─────────────────────────────────────────────────────────────────

def _analyze_champion_radar(matches: list[dict]) -> dict:
    """招牌英雄雷达图（仅显示对局最多的英雄 + 全对局平均背景）。"""
    from collections import defaultdict

    champ_stats: dict[int, dict] = defaultdict(lambda: {
        "games": 0, "wins": 0,
        "kills": [], "deaths": [], "assists": [], "kda_vals": [],
        "gpm_vals": [], "score": [],
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
        # 直接用 GPM 避免索引错位 bug
        cs["gpm_vals"].append(m["gold_earned"] / max(m["game_time_played"] / 60, 1))
        cs["score"].append(m["game_score"])

    # 至少 3 场
    eligible = [(cid, s) for cid, s in champ_stats.items() if s["games"] >= 3]
    eligible.sort(key=lambda x: x[1]["games"], reverse=True)

    if not eligible:
        return {"champions": [], "summary": "英雄场次不足（需要单个英雄至少3场），无法生成雷达图。"}

    # 只取对局最多的 1 个英雄
    top1_cid, top1_stats = eligible[0]

    # 六个维度
    dims_cn = ["KDA", "击杀", "助攻", "GPM", "评分", "生存率"]

    def _avg_or_zero(vals):
        return statistics.mean(vals) if vals else 0

    # 计算全对局平均值
    all_avg_kda = _avg_or_zero([m["kda"] for m in matches])
    all_avg_kills = _avg_or_zero([m["kills"] for m in matches])
    all_avg_assists = _avg_or_zero([m["assists"] for m in matches])
    all_avg_gpm = _avg_or_zero([m["gold_earned"] / max(m["game_time_played"] / 60, 1) for m in matches])
    all_avg_score = _avg_or_zero([m["game_score"] for m in matches])
    all_avg_survive = _avg_or_zero([1 / max(m["deaths"], 1) for m in matches])
    all_avgs = [all_avg_kda, all_avg_kills, all_avg_assists, all_avg_gpm, all_avg_score, all_avg_survive]

    # 计算招牌英雄平均值
    s = top1_stats
    hero_kda = _avg_or_zero(s["kda_vals"])
    hero_kills = _avg_or_zero(s["kills"])
    hero_assists = _avg_or_zero(s["assists"])
    hero_gpm = _avg_or_zero(s["gpm_vals"])
    hero_score = _avg_or_zero(s["score"])
    hero_survive = _avg_or_zero([1 / max(d, 1) for d in s["deaths"]])
    hero_avgs = [hero_kda, hero_kills, hero_assists, hero_gpm, hero_score, hero_survive]

    # 逐维度归一化 (0-100): 以全对局平均为 50 分基准
    # 英雄值 = 平均 → 50分；英雄值 = 2倍平均 → 100分
    def _norm_per_dim(hero_val, all_val):
        base = max(all_val, 0.001)
        ratio = hero_val / base
        score = min(ratio * 50, 100)
        return round(score, 1)

    all_normed = {}
    hero_normed = {}
    for i, dim in enumerate(dims_cn):
        all_normed[dim] = _norm_per_dim(all_avgs[i], all_avgs[i])  # 始终 50
        hero_normed[dim] = _norm_per_dim(hero_avgs[i], all_avgs[i])

    champions_data = [{
        "champion_id": top1_cid,
        "name": _champion_name(top1_cid),
        "games": s["games"],
        "win_rate": _win_rate(s["wins"], s["games"]),
        "metrics": hero_normed,
    }]

    all_avg_data = {
        "name": "全对局平均",
        "metrics": all_normed,
    }

    cname = _champion_name(top1_cid)
    summary = (
        f"你的招牌英雄 {cname}（{s['games']}场，胜率{_win_rate(s['wins'], s['games'])}%），"
        f"灰色虚线为全对局平均线（50分基准）。雷达面积超出灰色区域越多，"
        f"说明该英雄在对应维度的表现越超平均水准。"
    )

    return {
        "champions": champions_data,
        "all_average": all_avg_data,
        "dimensions": dims_cn,
        "summary": summary,
    }

def _analyze_champion_pool(matches: list[dict], champion_mastery: list[dict] | None = None) -> dict:
    """英雄池分析。优先使用 champion_mastery 表数据（全生命周期统计），
    回退到 match_summary 数据。"""
    if champion_mastery:
        # ── 使用 champion_mastery 表（全生命周期） ──
        total_games_all = sum(c["total_games"] for c in champion_mastery)

        freq = []
        for c in champion_mastery:
            games = c["total_games"]
            if games < 3:
                continue
            cid = c["champion_id"]
            wins = c["wins"]
            wr = c.get("win_rate") or 0
            freq.append({
                "champion_id": cid, "name": _champion_name(cid),
                "games": games, "wins": wins, "losses": games - wins,
                "freq_pct": round(games / total_games_all * 100, 1) if total_games_all > 0 else 0,
                "win_rate": round(wr, 1),
            })
            if len(freq) >= 15:
                break

        top_c = champion_mastery[0]
        top_game_pct = round(top_c["total_games"] / total_games_all * 100, 1) if total_games_all > 0 else 0
        unique_count = len(champion_mastery)

        # 位置灵活性（仍从 match_summary 获取）
        champ_positions = defaultdict(set)
        for m in matches:
            champ_positions[m["champion_id"]].add(m["position"])
        avg_positions = statistics.mean([len(ps) for ps in champ_positions.values()]) if champ_positions else 0

        if top_game_pct >= 80:
            summary = f"你是典型的绝活玩家——{_champion_name(top_c['champion_id'])} 占了 {top_game_pct:.0f}% 的对局。英雄池虽浅，但专精也是一种力量。"
        elif top_game_pct >= 50:
            summary = f"你有明确的招牌英雄（占比{top_game_pct:.0f}%），同时使用了 {unique_count} 个不同英雄，池子不算浅。"
        else:
            summary = f"英雄海！{unique_count} 个不同英雄轮换，平均每个英雄跨 {avg_positions:.1f} 个位置，是真正的全能选手。"
    else:
        # ── 回退：match_summary 数据 ──
        champ_counts = Counter(m["champion_id"] for m in matches)
        total = len(matches)

        freq = []
        for cid, cnt in champ_counts.most_common():
            if cnt < 3:
                continue
            wins = sum(1 for m in matches if m["champion_id"] == cid and m["win"])
            freq.append({
                "champion_id": cid, "name": _champion_name(cid),
                "games": cnt, "wins": wins, "losses": cnt - wins,
                "freq_pct": round(cnt / total * 100, 1),
                "win_rate": round(wins / cnt * 100, 1),
            })
            if len(freq) >= 15:
                break

        top_game_pct = champ_counts.most_common(1)[0][1] / total * 100 if champ_counts else 0

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
        "unique_count": unique_count if champion_mastery else len(champ_counts),
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

    # 最佳/最差日（仅计算 ≥3 场的日期）
    valid_days = [d for d in days_list if d["games"] >= 3]
    best_day = max(valid_days, key=lambda d: d["win_rate"]) if valid_days else None
    worst_day = min(valid_days, key=lambda d: d["win_rate"]) if valid_days else None
    most_time_day = max([d for d in days_list if d["games"] >= 3], key=lambda d: d["total_time_min"]) if [d for d in days_list if d["games"] >= 3] else None

    # LP 变化
    lp_days = [d for d in days_list if d["lp_change"] != 0 and d["games"] >= 3]
    most_gain_day = max(lp_days, key=lambda d: d["lp_change"]) if lp_days else None
    most_loss_day = min(lp_days, key=lambda d: d["lp_change"]) if lp_days else None

    # 最多荣誉日（MVP+SVP+荣誉统计）
    day_honors: dict[str, int] = defaultdict(int)
    for m in matches:
        if not m["_dt"]:
            continue
        d = m["_dt"].strftime("%Y-%m-%d")
        honors_count = sum(1 for f in ["was_mvp", "was_svp", "most_kills", "most_assists",
                                        "most_gold", "most_damage", "most_taken", "most_turrets"] if m.get(f))
        day_honors[d] += honors_count
    most_honors_day = max(day_honors, key=lambda d: day_honors[d]) if day_honors else None
    if most_honors_day:
        mhd_data = next((d for d in days_list if d["date"] == most_honors_day), None)
    else:
        mhd_data = None

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
        "most_honors_day": mhd_data,
        "attendance": attendance,
        "days_active": days_active,
        "days_since_first": days_since_first,
        "summary": summary,
    }

# ── 游戏轮次分析 ─────────────────────────────────────────────────────────────

def _detect_sessions(matches: list[dict], gap_hours: float) -> list[list[dict]]:
    """按时间间隔检测连续游戏轮次。"""
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

def _analyze_sessions(matches: list[dict], gap_hours: float = 2.0) -> dict:
    """连续游戏轮次分析。"""
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
        # 首局开始时间
        first_start = sess[0]["_dt"]
        first_start_hour = first_start.hour + first_start.minute / 60 if first_start else 0

        session_stats.append({
            "size": len(sess),
            "wins": wins,
            "losses": len(sess) - wins,
            "win_rate": _win_rate(wins, len(sess)),
            "total_time_min": round(total_time / 60),
            "first_win": first_win,
            "last_win": last_win,
            "last_end_hour": round(last_end_hour, 1),
            "first_start_hour": round(first_start_hour, 1),
            "start_time": sess[0]["_dt"].strftime("%m/%d %H:%M") if sess[0]["_dt"] else "",
        })

    # 游戏轮次规模分布
    size_dist = Counter(s["size"] for s in session_stats)
    size_labels = sorted(size_dist.keys())
    size_counts = [size_dist[s] for s in size_labels]

    # 游戏轮次规模评语（关注规模分布本身，不涉及首末局胜率）
    total_s = len(session_stats)
    avg_size_raw = statistics.mean([s["size"] for s in session_stats])
    max_size_raw = max(s["size"] for s in session_stats)
    most_common_size = max(size_dist, key=size_dist.get)
    most_common_pct = round(size_dist[most_common_size] / total_s * 100, 1)
    short_sessions = sum(c for s, c in size_dist.items() if s <= 2)
    long_sessions = sum(c for s, c in size_dist.items() if s >= 5)
    short_pct = round(short_sessions / total_s * 100, 1)
    long_pct = round(long_sessions / total_s * 100, 1)

    if long_pct >= 40:
        size_summary = (
            f"共 {total_s} 个游戏轮次，{long_pct}% 的轮次持续 5 局以上——你有明显的马拉松倾向，"
            f"一旦坐下就很难停下来。最常见的规模是每次 {most_common_size} 局（占 {most_common_pct}%），"
            f"平均 {avg_size_raw:.1f} 局/轮次，最长连续 {max_size_raw} 局。"
        )
    elif short_pct >= 60:
        size_summary = (
            f"共 {total_s} 个游戏轮次，{short_pct}% 的轮次在 2 局以内——你是典型的'打两把就走'选手，"
            f"游戏节奏克制而高效。最常见的规模是每次 {most_common_size} 局（占 {most_common_pct}%），"
            f"平均 {avg_size_raw:.1f} 局/轮次。"
        )
    elif short_pct >= 40:
        size_summary = (
            f"共 {total_s} 个游戏轮次，{short_pct}% 的轮次在 2 局以内，偏向短平快节奏，"
            f"偶尔也会连打多局。最常见的规模是每次 {most_common_size} 局（占 {most_common_pct}%），"
            f"平均 {avg_size_raw:.1f} 局/轮次，最长连续 {max_size_raw} 局。"
        )
    else:
        size_summary = (
            f"共 {total_s} 个游戏轮次，规模分布较为均匀——你既会快速一两局收手，也会偶尔深度鏖战。"
            f"最常见的规模是每次 {most_common_size} 局（占 {most_common_pct}%），"
            f"平均 {avg_size_raw:.1f} 局/轮次，最长连续 {max_size_raw} 局。"
        )

    # 最后一局结束时间分布
    last_hour_buckets = defaultdict(int)
    for s in session_stats:
        h = int(s["last_end_hour"])
        last_hour_buckets[h] += 1
    last_hour_labels = list(range(24))
    last_hour_counts = [last_hour_buckets.get(h, 0) for h in last_hour_labels]

    # 首局开始时间分布
    first_hour_buckets = defaultdict(int)
    for s in session_stats:
        h = int(s["first_start_hour"])
        first_hour_buckets[h] += 1
    first_hour_labels = list(range(24))
    first_hour_counts = [first_hour_buckets.get(h, 0) for h in first_hour_labels]

    # 首局 vs 末局胜率
    first_wins = sum(1 for s in session_stats if s["first_win"])
    last_wins = sum(1 for s in session_stats if s["last_win"])

    avg_size = statistics.mean([s["size"] for s in session_stats])
    max_size = max(s["size"] for s in session_stats)

    # ── "赢一局就睡结果天亮了" 模式检测 ──
    # 末局动机分析：末局前一场是赢还是输？→ 玩家为什么选择继续打？
    chase_win_last = {"wins": 0, "total": 0}    # 前一场赢了→继续打（追胜）
    chase_loss_last = {"wins": 0, "total": 0}    # 前一场输了→继续打（追输）
    stop_after_win = 0     # 末局是胜局（赢了就停）
    late_night_count = 0   # 深夜（0-6点）结束
    marathon_count = 0     # 5+局马拉松
    win_stop_sessions = 0  # 单局 session 且赢了（赢一局就走）
    loss_stop_sessions = 0 # 单局 session 且输了

    for sess in sessions:
        if sess[-1]["win"]:
            stop_after_win += 1

        if len(sess) >= 2:
            if sess[-2]["win"]:
                chase_win_last["total"] += 1
                if sess[-1]["win"]:
                    chase_win_last["wins"] += 1
            else:
                chase_loss_last["total"] += 1
                if sess[-1]["win"]:
                    chase_loss_last["wins"] += 1
        elif len(sess) == 1:
            if sess[0]["win"]:
                win_stop_sessions += 1
            else:
                loss_stop_sessions += 1

        last_hour = sess[-1]["_dt"].hour if sess[-1]["_dt"] else 0
        if 0 <= last_hour < 6:
            late_night_count += 1

        if len(sess) >= 5:
            marathon_count += 1

    # ── 胜率转移概率：赢了/输了之后是继续打还是停止 ──
    win_total = 0
    loss_total = 0
    win_continue_s = 0
    win_stop_s = 0
    loss_continue_s = 0
    loss_stop_s = 0
    for sess_s in sessions:
        for i, m in enumerate(sess_s):
            if m["win"]:
                win_total += 1
                if i < len(sess_s) - 1:
                    win_continue_s += 1
                else:
                    win_stop_s += 1
            else:
                loss_total += 1
                if i < len(sess_s) - 1:
                    loss_continue_s += 1
                else:
                    loss_stop_s += 1

    win_continue_rate_s = round(win_continue_s / win_total * 100, 1) if win_total > 0 else 0
    loss_continue_rate_s = round(loss_continue_s / loss_total * 100, 1) if loss_total > 0 else 0
    win_stop_rate_s = round(win_stop_s / win_total * 100, 1) if win_total > 0 else 0
    loss_stop_rate_s = round(loss_stop_s / loss_total * 100, 1) if loss_total > 0 else 0
    stop_discipline_s = round(win_stop_rate_s - loss_stop_rate_s, 1)

    chase_win_wr = _win_rate(chase_win_last["wins"], chase_win_last["total"])
    chase_loss_wr = _win_rate(chase_loss_last["wins"], chase_loss_last["total"])
    stop_win_pct = round(stop_after_win / total_s * 100, 1) if total_s > 0 else 0
    late_night_pct = round(late_night_count / total_s * 100, 1) if total_s > 0 else 0

    # 判断追赢/追输主导倾向（一方至少是另一方的 1.5 倍）
    chase_win_dominated = (
        chase_win_last["total"] >= 3 and chase_loss_last["total"] > 0
        and chase_win_last["total"] >= chase_loss_last["total"] * 1.5
    )
    chase_loss_dominated = (
        chase_loss_last["total"] >= 3 and chase_win_last["total"] > 0
        and chase_loss_last["total"] >= chase_win_last["total"] * 1.5
    )

    # 游戏轮次内第 N 局胜率（游戏位置对胜率的影响）
    pos_in_session: dict[int, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for sess in sessions:
        for i, m in enumerate(sess):
            pos = i + 1  # 第1局、第2局...
            pos_in_session[pos]["total"] += 1
            if m["win"]:
                pos_in_session[pos]["wins"] += 1

    max_pos = max(pos_in_session.keys()) if pos_in_session else 0
    pos_labels = [f"第{i}局" for i in range(1, max_pos + 1)]
    pos_wr = [_win_rate(pos_in_session[i]["wins"], pos_in_session[i]["total"]) for i in range(1, max_pos + 1)]
    pos_games = [pos_in_session[i]["total"] for i in range(1, max_pos + 1)]

    # 概要（首局 vs 末局 增强评语，含"赢一局就睡结果天亮了"检测）
    fw = _win_rate(first_wins, total_s)
    lw = _win_rate(last_wins, total_s)

    # ── 首局 vs 末局 详细评语（用于图表卡片）──
    if lw > fw + 5:
        # 末局胜率高于首局 → 三种可能：赢一局就睡 / 打到赢为止 / 越打越热
        if win_stop_rate_s > loss_stop_rate_s + 10 and avg_size <= 3:
            # 赢后停止率显著高于输后停止率 + session偏小 → 自律型"赢一局就睡"
            first_last_summary = (
                f"✅ 赢一局就睡的自律玩家！{win_stop_rate_s}%的胜局你选择见好就收，"
                f"远高于输后停止率({loss_stop_rate_s}%)。末局胜率({lw}%)胜过首局({fw}%)，"
                f"平均每次仅 {avg_size:.1f} 局——优秀的自控力。"
            )
            if win_stop_sessions > loss_stop_sessions * 2:
                first_last_summary += (
                    f" {win_stop_sessions}次打完一局赢了就撤，执行力值得称赞。"
                )
        elif loss_continue_rate_s > win_continue_rate_s + 10 and avg_size >= 3.5:
            # 输后继续率更高 + session偏大 → "打到赢为止"模式
            first_last_summary = (
                f"🎯 打到赢为止！输后继续率({loss_continue_rate_s}%)远超赢后继续率({win_continue_rate_s}%)——"
                f"不甘心输着下机。末局胜率({lw}%)虽高于首局({fw}%)，但代价是平均每次打 {avg_size:.1f} 局。"
                f"注意：{marathon_count}次马拉松式连打(5+局)，追输的成本不容忽视。"
            )
        elif late_night_pct >= 30:
            first_last_summary = (
                f"🌙 深夜战神！末局胜率({lw}%)高于首局({fw}%)，但{late_night_pct}%的游戏轮次在凌晨0-6点结束——"
                f"越晚状态越好，却也越打越上头。{marathon_count}次马拉松式连打(5+局)。"
            )
        else:
            first_last_summary = (
                f"🔥 末局胜率({lw}%)高于首局({fw}%)，赢后继续率({win_continue_rate_s}%)"
                f"与输后继续率({loss_continue_rate_s}%)接近——你属于慢热型选手，需要几局热身才能进入最佳状态。"
            )
    elif fw > lw + 5:
        if chase_win_dominated and chase_win_wr < 50:
            first_last_summary = (
                f"🎯 赢一局就睡结果天亮了！你{chase_win_last['total']}次在赢后选择继续而非见好就收，"
                f"但赢后末局胜率仅{chase_win_wr}%。首局胜率{fw}%→末局{lw}%，"
                f"'再来一局'常常变成'再来一败'。建议：赢一局就走，别让连胜诱惑拖垮胜率。"
            )
        elif chase_loss_dominated and chase_loss_wr < 40:
            first_last_summary = (
                f"📉 输了不甘心！——{chase_loss_last['total']}次输后继续打，末局胜率仅{chase_loss_wr}%。"
                f"首局({fw}%)远好于末局({lw}%)，及时止损比追回来更明智。"
            )
        elif late_night_pct >= 30 and marathon_count >= total_s * 0.2:
            first_last_summary = (
                f"🕐 深夜鏖战拖累胜率！{late_night_pct}%的游戏轮次在凌晨结束，{marathon_count}次马拉松式连打(5+局)。"
                f"首局胜率{fw}%→末局{lw}%，早睡早起或许才是上分秘笈。"
            )
        elif chase_win_last["total"] >= 3 and chase_win_wr < fw - 5:
            first_last_summary = (
                f"⚠️ 赢后追击胜率不佳——{chase_win_last['total']}次赢后继续打，末局胜率仅{chase_win_wr}%，"
                f"远低于首局{fw}%。'手热再来一局'的效果并不好，见好就收才是上分正道。"
            )
        else:
            first_last_summary = (
                f"📊 首局状态最佳（胜率{fw}%），但随着体力下降末局跌至{lw}%。"
                f"建议控制每次游戏时长，见好就收。"
            )
    else:
        if chase_win_dominated and avg_size > 3:
            first_last_summary = (
                f"⚖️ 首局({fw}%)与末局({lw}%)胜率接近，状态稳定——但你有{chase_win_last['total']}次赢后继续打，"
                f"'赢一局就走'的执行力有待加强。平均每次{avg_size:.1f}局，最长{max_size}局。"
            )
        elif late_night_pct >= 30 and avg_size > 3:
            first_last_summary = (
                f"⚖️ 首局({fw}%)与末局({lw}%)胜率接近，状态稳定——"
                f"但{late_night_pct}%的游戏轮次在凌晨结束，注意作息对长期状态的影响。"
            )
        elif win_stop_sessions > loss_stop_sessions * 2 and avg_size <= 2.5:
            first_last_summary = (
                f"✅ 优秀的自律习惯！首局({fw}%)与末局({lw}%)胜率稳定，且{win_stop_sessions}次'赢一局就收'——"
                f"见好就收的执行力值得称赞。平均每次仅{avg_size:.1f}局。"
            )
        else:
            first_last_summary = (
                f"⚖️ 首局({fw}%)与末局({lw}%)胜率接近，状态保持力强。"
                f"平均每次上线打{avg_size:.1f}局，最长连续{max_size}局。"
            )

    # 主 summary（用于规模分布卡片的附加说明，保持简洁）
    if lw > fw + 5:
        if stop_discipline_s > 10 and avg_size <= 3:
            summary = f"末局胜率({lw}%)高于首局({fw}%)，且{win_stop_rate_s}%的胜局你选择见好就收——'赢一局就睡'的自律习惯奏效。平均每次打 {avg_size:.1f} 局。"
        elif loss_continue_rate_s > win_continue_rate_s + 10 and avg_size >= 3.5:
            summary = f"末局胜率({lw}%)高于首局({fw}%)，但输后继续率({loss_continue_rate_s}%)偏高——'打到赢为止'的执念推高了末局胜率，却也拉长了每次的游戏时长（平均 {avg_size:.1f} 局）。"
        else:
            summary = f"你越打越热！游戏轮次首局胜率仅 {fw}%，但末局提升到 {lw}%——需要热身时间。平均每次上线打 {avg_size:.1f} 局。"
    elif fw > lw + 5:
        summary = f"首局状态最佳（胜率 {fw}%），但随着体力下降末局跌至 {lw}%。建议控制每次游戏时长，见好就收。平均每次上线打 {avg_size:.1f} 局。"
    else:
        summary = f"首局({fw}%)与末局({lw}%)胜率接近，状态保持稳定。平均每次上线打 {avg_size:.1f} 局，最长连续 {max_size} 局。"

    # 游戏轮次内胜率趋势概要
    if len(pos_wr) >= 3:
        early_pos = pos_wr[:2]
        late_pos = pos_wr[2:]
        early_avg = statistics.mean(early_pos) if early_pos else 0
        late_avg = statistics.mean(late_pos) if late_pos else 0
        if late_avg > early_avg + 8:
            pos_summary = f"游戏轮次后半段胜率（{late_avg:.0f}%）明显优于前半段（{early_avg:.0f}%），你是慢热型选手，需要几局热身。"
        elif early_avg > late_avg + 8:
            pos_summary = f"游戏轮次前半段胜率（{early_avg:.0f}%）更高，后半段降至 {late_avg:.0f}%——注意力随时间衰减，建议缩短连续游戏时间。"
        else:
            pos_summary = f"游戏轮次内各局胜率稳定，不受游戏顺序影响——状态保持能力强。"
    else:
        pos_summary = "数据不足以分析游戏轮次内胜率趋势。"

    return {
        "total": len(session_stats),
        "avg_size": round(avg_size, 1),
        "max_size": max_size,
        "size_labels": size_labels,
        "size_counts": size_counts,
        "last_hour_labels": [f"{h}:00" for h in last_hour_labels],
        "last_hour_counts": last_hour_counts,
        "first_hour_labels": [f"{h}:00" for h in first_hour_labels],
        "first_hour_counts": first_hour_counts,
        "first_wr": fw,
        "last_wr": lw,
        "pos_labels": pos_labels,
        "pos_wr": pos_wr,
        "pos_games": pos_games,
        "pos_summary": pos_summary,
        "size_summary": size_summary,
        "summary": summary,
        # 新增：末局动机分析字段
        "first_last_summary": first_last_summary,
        "chase_win_games": chase_win_last["total"],
        "chase_win_wr": chase_win_wr,
        "chase_loss_games": chase_loss_last["total"],
        "chase_loss_wr": chase_loss_wr,
        "stop_win_pct": stop_win_pct,
        "late_night_pct": late_night_pct,
        "marathon_count": marathon_count,
        "win_stop_sessions": win_stop_sessions,
        "loss_stop_sessions": loss_stop_sessions,
        "win_continue_rate": win_continue_rate_s,
        "loss_continue_rate": loss_continue_rate_s,
        "win_stop_rate": win_stop_rate_s,
        "loss_stop_rate": loss_stop_rate_s,
        "stop_discipline": stop_discipline_s,
    }

# ── 创意分析 ─────────────────────────────────────────────────────────────────

def _analyze_tilt(matches: list[dict]) -> dict:
    """心态/tilt 分析：输后胜率 vs 赢后胜率。"""
    if len(matches) < 2:
        return {"after_win": None, "after_loss": None, "after_2loss": None, "after_2win": None,
                "summary": "数据不足（需至少2场），无法进行 tilt 分析。"}

    after_win = {"wins": 0, "total": 0}
    after_loss = {"wins": 0, "total": 0}
    after_2loss = {"wins": 0, "total": 0}
    after_2win = {"wins": 0, "total": 0}

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
            if prev_results[-1] and prev_results[-2]:
                after_2win["total"] += 1
                if m["win"]:
                    after_2win["wins"] += 1
        prev_results.append(m["win"])

    aw = _win_rate(after_win["wins"], after_win["total"])
    al = _win_rate(after_loss["wins"], after_loss["total"])
    a2 = _win_rate(after_2loss["wins"], after_2loss["total"])
    a2w = _win_rate(after_2win["wins"], after_2win["total"])

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
        "after_2win": {"games": after_2win["total"], "wins": after_2win["wins"], "wr": a2w} if after_2win["total"] > 0 else None,
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

def _analyze_surrender(matches: list[dict]) -> dict:
    """投降分析。"""
    surr_wins = [m for m in matches if m["was_surrender"] and m["win"]]
    surr_losses = [m for m in matches if m["was_surrender"] and not m["win"]]
    non_surrenders = [m for m in matches if not m["was_surrender"]]

    sr_rate = round((len(surr_wins) + len(surr_losses)) / len(matches) * 100, 1) if matches else 0
    non_sr_wr = _win_rate(sum(1 for m in non_surrenders if m["win"]), len(non_surrenders))
    # 我方投降 vs 对方投降
    enemy_ff = len(surr_wins)  # 对方投降→我方赢
    our_ff = len(surr_losses)   # 我方投降→我方输
    enemy_ff_rate = round(enemy_ff / (enemy_ff + our_ff) * 100, 1) if (enemy_ff + our_ff) > 0 else 0

    if enemy_ff > our_ff:
        summary = (
            f"投降率 {sr_rate}%（{enemy_ff + our_ff}场），但其中 {enemy_ff_rate}% 是对方投降！"
            f"你打崩对手的次数远超被对手打崩——实力压制让对手心态先崩。"
            f" 非投降局胜率 {non_sr_wr}%。"
        )
    elif sr_rate >= 20:
        summary = f"投降率 {sr_rate}% 偏高——你和队友可能容易心态崩溃。在非投降局中胜率 {non_sr_wr}%，坚持就有希望。"
    elif sr_rate >= 10:
        summary = f"投降率 {sr_rate}%，属于正常水平。非投降局胜率 {non_sr_wr}%。"
    else:
        summary = f"投降率仅 {sr_rate}%——你是个不轻言放弃的选手，非投降局胜率 {non_sr_wr}%，坚持是最好的翻盘策略。"

    return {
        "surrender_count": len(surr_wins) + len(surr_losses), "surrender_rate": sr_rate,
        "enemy_ff": enemy_ff, "our_ff": our_ff, "enemy_ff_rate": enemy_ff_rate,
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
    """金币效率分析（排除<4分钟重开局，按占比>20%的模式展示，GPM = 金币/分钟）。"""
    if not matches:
        return {"scatter_win": [], "scatter_loss": [], "mode_name": "", "summary": "暂无数据。"}

    # 排除 <4 分钟（240s）的重开/异常局
    valid = [m for m in matches if m["game_time_played"] >= 240]
    if not valid:
        return {"scatter_win": [], "scatter_loss": [], "mode_name": "", "summary": "排除过短对局后无有效数据。"}

    # 按队列模式分组，只保留占比 >20% 的模式
    total = len(valid)
    mode_counts = Counter(m.get("queue_name", "Unknown") for m in valid)
    major_modes = [mode for mode, cnt in mode_counts.items() if cnt / total > 0.20]
    if not major_modes:
        major_modes = [mode_counts.most_common(1)[0][0]]

    # 取第一个主要模式生成数据
    results = {}
    for mode in major_modes:
        mode_matches = [m for m in valid if m.get("queue_name", "") == mode]
        scatter_win = []
        scatter_loss = []
        gpm_vals = []
        for m in mode_matches:
            dur = max(m["game_time_played"] / 60, 1)
            gpm = m["gold_earned"] / dur
            gpm_vals.append(gpm)
            point = {"x": round(dur, 1), "y": round(gpm)}
            if m["win"]:
                scatter_win.append(point)
            else:
                scatter_loss.append(point)

        if not gpm_vals:
            continue

        avg_gpm = round(statistics.mean(gpm_vals))
        high_gpm = [m for i, m in enumerate(mode_matches) if gpm_vals[i] >= avg_gpm]
        low_gpm = [m for i, m in enumerate(mode_matches) if gpm_vals[i] < avg_gpm]
        high_wr = _win_rate(sum(1 for m in high_gpm if m["win"]), len(high_gpm))
        low_wr = _win_rate(sum(1 for m in low_gpm if m["win"]), len(low_gpm))

        if high_wr > low_wr + 10:
            summary = f"{mode}：每分钟金币 ≥{avg_gpm} 时胜率 {high_wr}%，远高于低经济局 {low_wr}%。经济就是一切！"
        elif low_wr > high_wr + 5:
            summary = f"{mode}：有趣——低经济局胜率({low_wr}%)反而高于高经济局({high_wr}%)，经济优势不直接等于胜利。"
        else:
            summary = f"{mode}：高经济局胜率({high_wr}%)与低经济局({low_wr}%)接近，你的发挥不依赖经济领先。平均 GPM: {avg_gpm}。"

        results[mode] = {
            "scatter_win": scatter_win, "scatter_loss": scatter_loss,
            "avg_gpm": avg_gpm, "high_gpm_wr": high_wr, "low_gpm_wr": low_wr,
            "mode_name": mode, "games": len(mode_matches),
            "summary": summary,
        }

    first_mode = list(results.keys())[0] if results else ""
    r = results.get(first_mode, {})
    return {
        "scatter_win": r.get("scatter_win", []),
        "scatter_loss": r.get("scatter_loss", []),
        "avg_gpm": r.get("avg_gpm", 0),
        "high_gpm_wr": r.get("high_gpm_wr", 0),
        "low_gpm_wr": r.get("low_gpm_wr", 0),
        "mode_name": r.get("mode_name", ""),
        "excluded_short": len(matches) - len(valid),
        "summary": r.get("summary", "暂无数据。"),
    }

# ── 行为与心理分析 ──────────────────────────────────────────────────────────

def _analyze_boomerang_effect(matches: list[dict]) -> dict:
    """过度自信与救赎效应：MVP/大胜后 vs SVP/惨败后的下一局表现变化。"""
    if not matches or len(matches) < 10:
        return {"mvp_next_delta": [], "svp_next_delta": [], "normal_next_delta": [],
                "mvp_count": 0, "svp_count": 0, "summary": "数据不足（需≥10场）。"}

    # 按时间排序
    sorted_m = sorted(matches, key=lambda m: m["_dt"] or datetime.min)

    mvp_deltas = []   # MVP 后下一局 KDA 变化
    svp_deltas = []   # SVP/惨败后下一局 KDA 变化
    normal_deltas = []  # 普通局后下一局 KDA 变化
    scatter_mvp = []   # {x: current_score, y: next_score}
    scatter_svp = []
    scatter_normal = []

    mvp_count = 0
    svp_count = 0
    mvp_next_wins = 0
    svp_next_wins = 0

    for i in range(len(sorted_m) - 1):
        cur = sorted_m[i]
        nxt = sorted_m[i + 1]
        # 跳过跨天（间隔>12小时的不算连续影响）
        if cur["_dt"] and nxt["_dt"] and (nxt["_dt"] - cur["_dt"]).total_seconds() > 12 * 3600:
            continue

        cur_score = cur["game_score"]
        nxt_score = nxt["game_score"]
        point = {"x": cur_score, "y": nxt_score}

        if cur["was_mvp"]:
            mvp_deltas.append(nxt_score - cur_score)
            scatter_mvp.append(point)
            mvp_count += 1
            if nxt["win"]:
                mvp_next_wins += 1
        elif cur["was_svp"] or cur["kda"] < 0.5:
            svp_deltas.append(nxt_score - cur_score)
            scatter_svp.append(point)
            svp_count += 1
            if nxt["win"]:
                svp_next_wins += 1
        else:
            normal_deltas.append(nxt_score - cur_score)
            scatter_normal.append(point)

    mvp_next_wr = _win_rate(mvp_next_wins, mvp_count) if mvp_count > 0 else 0
    svp_next_wr = _win_rate(svp_next_wins, svp_count) if svp_count > 0 else 0

    avg_mvp_delta = round(statistics.mean(mvp_deltas), 1) if mvp_deltas else 0
    avg_svp_delta = round(statistics.mean(svp_deltas), 1) if svp_deltas else 0

    parts = []
    if mvp_count >= 3:
        if avg_mvp_delta < -1:
            parts.append(f"MVP后下一局评分平均下降 {abs(avg_mvp_delta)} 分（过度自信效应明显），MVP后胜率仅 {mvp_next_wr}%")
        else:
            parts.append(f"MVP后表现稳定（评分变化 {avg_mvp_delta:+}），MVP后胜率 {mvp_next_wr}%——状态能延续")
    else:
        parts.append("MVP场次不足，无法评估过度自信效应")
    if svp_count >= 3:
        if avg_svp_delta > 1:
            parts.append(f"惨败后反弹 +{avg_svp_delta} 分（救赎效应），SVP后胜率 {svp_next_wr}%——知耻后勇！")
        else:
            parts.append(f"惨败后评分变化 {avg_svp_delta:+}，SVP后胜率 {svp_next_wr}%——情绪影响较大")
    else:
        parts.append("惨败/SVP场次不足，无法评估救赎效应")

    return {
        "scatter_mvp": scatter_mvp, "scatter_svp": scatter_svp, "scatter_normal": scatter_normal,
        "mvp_count": mvp_count, "svp_count": svp_count,
        "avg_mvp_delta": avg_mvp_delta, "avg_svp_delta": avg_svp_delta,
        "mvp_next_wr": mvp_next_wr, "svp_next_wr": svp_next_wr,
        "summary": "；".join(parts) + "。",
    }

def _analyze_one_more_game(matches: list[dict]) -> dict:
    """"再来一局"陷阱：游戏轮次末局胜率 vs 前N-1局胜率（独立对比），检测追输/追赢/赢后贪多行为。"""
    if not matches or len(matches) < 5:
        return {"session_sizes": [], "prev_wrs": [], "last_wrs": [],
                "bin_counts": [], "chase_loss_rate": 0,
                "win_stop_ratio": 0, "summary": "数据不足（需≥5场）。"}

    # 按 session 分组（session gap = 2h）
    sorted_m = sorted(matches, key=lambda m: m["_dt"] or datetime.min)
    sessions = []
    cur_session = [sorted_m[0]]
    for i in range(1, len(sorted_m)):
        prev = sorted_m[i - 1]
        cur = sorted_m[i]
        if prev["_dt"] and cur["_dt"] and (cur["_dt"] - prev["_dt"]).total_seconds() <= 2 * 3600:
            cur_session.append(cur)
        else:
            sessions.append(cur_session)
            cur_session = [cur]
    sessions.append(cur_session)

    if len(sessions) < 3:
        return {"session_sizes": [], "prev_wrs": [], "last_wrs": [],
                "bin_counts": [], "chase_loss_rate": 0,
                "win_stop_ratio": 0, "summary": f"仅有 {len(sessions)} 个游戏轮次，需≥3个才能分析。"}

    # ── 胜率转移概率（核心新增）──
    # 在所有相邻对局中统计：赢后继续/输后继续/赢后停止 的概率
    win_continue = 0    # 赢了 → 继续打下一局
    win_stop = 0        # 赢了 → 停止（session 最后一局是胜局）
    loss_continue = 0   # 输了 → 继续打下一局
    loss_stop = 0       # 输了 → 停止（session 最后一局是败局）
    win_total = 0       # 总共的胜局数
    loss_total = 0      # 总共的败局数

    for s in sessions:
        for i, m in enumerate(s):
            if m["win"]:
                win_total += 1
                if i < len(s) - 1:
                    win_continue += 1  # 赢了但继续打
                else:
                    win_stop += 1      # 赢了就停
            else:
                loss_total += 1
                if i < len(s) - 1:
                    loss_continue += 1  # 输了但继续打
                else:
                    loss_stop += 1      # 输了就停

    win_continue_rate = round(win_continue / win_total * 100, 1) if win_total > 0 else 0
    loss_continue_rate = round(loss_continue / loss_total * 100, 1) if loss_total > 0 else 0
    win_stop_ratio = round(win_stop / win_total * 100, 1) if win_total > 0 else 0
    # 关键指标："赢了就停" vs "输了就停"——自律者赢后停止率 > 输后停止率
    loss_stop_ratio = round(loss_stop / loss_total * 100, 1) if loss_total > 0 else 0
    stop_discipline = win_stop_ratio - loss_stop_ratio  # 正值=赢后更倾向停止（自律）

    # ── 按 session 规模分组（含1局"见好就收"列）──
    size_bins = [(1, 1, "1局\n(见好就收)"), (2, 2, "2局"), (3, 3, "3局"),
                 (4, 5, "4-5局"), (6, 999, "6+局")]
    bin_labels = []
    prev_wrs = []      # 前N-1局胜率（不含末局，独立指标）
    last_wrs = []      # 末局胜率
    bin_counts = []

    for lo, hi, label in size_bins:
        in_bin = [s for s in sessions if lo <= len(s) <= hi]
        if len(in_bin) < 3:
            continue
        bin_labels.append(label)
        bin_counts.append(len(in_bin))

        if lo == 1 and hi == 1:
            # 1局 session：整体胜率即末局胜率，前N-1局不存在
            all_g = [g for s in in_bin for g in s]
            last_wrs.append(_win_rate(sum(1 for g in all_g if g["win"]), len(all_g)))
            prev_wrs.append(None)  # 标记为无前N-1局数据
        else:
            # 前N-1局胜率（排除末局，独立计算）
            prev_games = [g for s in in_bin for g in s[:-1]]
            prev_wrs.append(_win_rate(sum(1 for g in prev_games if g["win"]), len(prev_games)))
            last_games = [s[-1] for s in in_bin]
            last_wrs.append(_win_rate(sum(1 for g in last_games if g["win"]), len(last_games)))

    # ── 追输/追赢/赢后贪多检测 ──
    chase_loss_count = 0
    chase_win_count = 0
    chase_win_lose_count = 0
    total_multi = 0
    for s in sessions:
        if len(s) >= 2:
            total_multi += 1
            prev_win = s[-2]["win"]
            last_win = s[-1]["win"]
            if last_win == 0 and prev_win == 0:
                chase_loss_count += 1
            elif last_win == 1 and prev_win == 1:
                chase_win_count += 1
            elif last_win == 0 and prev_win == 1:
                chase_win_lose_count += 1

    chase_loss_rate = round(chase_loss_count / total_multi * 100, 1) if total_multi > 0 else 0
    chase_win_rate = round(chase_win_count / total_multi * 100, 1) if total_multi > 0 else 0
    chase_win_lose_rate = round(chase_win_lose_count / total_multi * 100, 1) if total_multi > 0 else 0

    # ── 末局胜率与整体均值对比（用于检测"赢一局就睡"模式）──
    all_matches_win = sum(1 for m in matches if m["win"])
    overall_avg_wr = _win_rate(all_matches_win, len(matches))
    # 所有末局胜率
    all_last_games = [s[-1] for s in sessions]
    all_last_wr = _win_rate(sum(1 for g in all_last_games if g["win"]), len(all_last_games))
    # 所有末局前一场胜率（排除1局session）
    all_prev_games = [s[-2] for s in sessions if len(s) >= 2]
    all_prev_wr = _win_rate(sum(1 for g in all_prev_games if g["win"]), len(all_prev_games)) if all_prev_games else 0

    # ── 多维度评语（结合转移概率+规模对比+追输追赢）──
    verdict_parts = []

    # 先判断核心模式
    avg_session_size = statistics.mean([len(s) for s in sessions]) if sessions else 0
    one_game_sessions = sum(1 for s in sessions if len(s) == 1)
    one_game_pct = round(one_game_sessions / len(sessions) * 100, 1) if sessions else 0
    one_game_win = sum(1 for s in sessions if len(s) == 1 and s[0]["win"])
    one_game_wr = _win_rate(one_game_win, one_game_sessions) if one_game_sessions > 0 else 0

    # 模式1：赢一局就睡（末局胜率 > 整体均值 + 平均session小 + win_stop高）
    if all_last_wr > overall_avg_wr + 5 and win_stop_ratio > loss_stop_ratio + 10 and avg_session_size <= 3:
        verdict_parts.append(
            f"✅ 赢一局就睡的自律玩家！{win_stop_ratio}%的胜局你选择见好就收，"
            f"远高于输后停止率({loss_stop_ratio}%)。末局胜率({all_last_wr}%)显著高于整体均值({overall_avg_wr}%)，"
            f"说明你善于在获胜时果断收手"
        )
        if one_game_pct >= 20:
            verdict_parts.append(f"单局即停的'打完就撤'占 {one_game_pct}%，其中胜率 {one_game_wr}%")
        if chase_win_lose_rate > 20:
            verdict_parts.append(
                f"但注意：仍有{chase_win_lose_count}次（{chase_win_lose_rate}%）赢后继续却末局失利——"
                f"那些'再来一局'最终变成了'再来一败'"
            )

    # 模式2：打到赢为止（末局胜率高 + session规模大 + 输后继续率高）
    elif all_last_wr > overall_avg_wr + 5 and loss_continue_rate > win_continue_rate + 10 and avg_session_size >= 3.5:
        verdict_parts.append(
            f"🎯 打到赢为止！末局胜率({all_last_wr}%)虽然高于整体均值({overall_avg_wr}%)，"
            f"但输后继续率({loss_continue_rate}%)远超赢后继续率({win_continue_rate}%)——"
            f"你不甘心输了就停，倾向于'不赢不走'，平均每次打 {avg_session_size:.1f} 局"
        )
        if chase_loss_rate > 30:
            verdict_parts.append(f"代价：{chase_loss_rate}%的多局游戏轮次以连败收尾，追输成本不容忽视")

    # 模式3：越打越热（末局胜率高 + session内递增 + 无明显追输追赢偏好）
    elif all_last_wr > overall_avg_wr + 5:
        verdict_parts.append(
            f"🔥 末局胜率({all_last_wr}%)高于整体均值({overall_avg_wr}%)，且赢后续打率({win_continue_rate}%)"
            f"与输后续打率({loss_continue_rate}%)接近——你属于慢热型选手，越打状态越好，不受上局结果影响"
        )

    # 模式4：追输陷阱（末局胜率低 + 输后继续率高）
    if chase_loss_rate > 40:
        verdict_parts.append(f"⚠️ 连败追输倾向明显（{chase_loss_rate}%的多局游戏轮次以连败收尾）——'再来一局'常常变成再送一局")
    elif chase_loss_rate > 25:
        verdict_parts.append(f"有一定追输倾向（{chase_loss_rate}%的游戏轮次以连败结束）")

    # 模式5：赢后贪多（独立检测，可与上述模式叠加）
    if chase_win_lose_rate > 25:
        verdict_parts.append(
            f"🔍 赢一局就睡结果天亮了！{chase_win_lose_count}次（{chase_win_lose_rate}%）赢后选择继续，"
            f"但末局输掉——本该见好就收的胜利被'再来一局'葬送"
        )
    elif chase_win_lose_rate > 15:
        verdict_parts.append(
            f"有{chase_win_lose_count}次（{chase_win_lose_rate}%）赢后继续却末局失利——"
            f"'赢一局就走'的执行力还有提升空间"
        )

    if chase_win_rate > 30:
        verdict_parts.append(f"连胜追击成功率高（{chase_win_rate}%以连胜收尾），手热时乘胜追击是有效策略")
    elif chase_win_count >= 3 and chase_win_lose_count > chase_win_count:
        verdict_parts.append(f"赢后继续的胜率不如见好就收（赢后续胜{chase_win_count}次 vs 赢后续败{chase_win_lose_count}次）")

    if not verdict_parts:
        if chase_loss_rate <= 15 and chase_win_lose_rate <= 10:
            verdict_parts.append(f"追输倾向低（{chase_loss_rate}%），且赢后贪多失利好少（{chase_win_lose_rate}%）——自律性优秀")
        else:
            verdict_parts.append(f"追输倾向较低（{chase_loss_rate}%），见好就收或及时止损的意识不错")

    chase_verdict = "；".join(verdict_parts)

    return {
        "session_sizes": bin_labels, "prev_wrs": prev_wrs, "last_wrs": last_wrs,
        "bin_counts": bin_counts, "chase_loss_rate": chase_loss_rate,
        "chase_win_rate": chase_win_rate, "chase_win_lose_rate": chase_win_lose_rate,
        "total_sessions": len(sessions),
        "win_continue_rate": win_continue_rate, "loss_continue_rate": loss_continue_rate,
        "win_stop_ratio": win_stop_ratio, "loss_stop_ratio": loss_stop_ratio,
        "stop_discipline": round(stop_discipline, 1),
        "all_last_wr": all_last_wr, "overall_avg_wr": overall_avg_wr,
        "one_game_pct": one_game_pct, "one_game_wr": one_game_wr,
        "avg_session_size": round(avg_session_size, 1),
        "all_prev_wr": all_prev_wr,
        "summary": f"共 {len(sessions)} 个游戏轮次。{chase_verdict}",
    }

# ── 效率与风格分析 ──────────────────────────────────────────────────────────

def _analyze_carry_profile(matches: list[dict]) -> dict:
    """Carry依赖度画像：胜/败局的详细类型分布。"""
    if not matches or len(matches) < 5:
        return {"labels_win": [], "win_data": [], "labels_loss": [], "loss_data": [],
                "summary": "数据不足（需≥5场）。"}

    # 计算中位 game_score（用于分类）
    scores = [m["game_score"] for m in matches]
    median_score = statistics.median(scores) if scores else 0

    # 胜局分类
    wins = [m for m in matches if m["win"]]
    hard_carry = 0   # MVP + ≥2荣誉
    contributed = 0   # 非MVP非躺赢
    got_carried = 0   # 躺赢 (game_score < median 且无荣誉)

    for m in wins:
        honors = sum([m["most_kills"], m["most_assists"], m["most_gold"],
                      m["most_damage"], m["most_taken"], m["most_turrets"]])
        if m["was_mvp"] and honors >= 2:
            hard_carry += 1
        elif m["game_score"] < median_score and honors == 0:
            got_carried += 1
        else:
            contributed += 1

    # 败局分类
    losses = [m for m in matches if not m["win"]]
    svp_loss = 0      # SVP — 尽力局
    crash_loss = 0    # kda<1 且 game_score < median — 崩盘
    normal_loss = 0

    for m in losses:
        if m["was_svp"]:
            svp_loss += 1
        elif m["kda"] < 1 and m["game_score"] < median_score:
            crash_loss += 1
        else:
            normal_loss += 1

    total_wins = len(wins)
    total_losses = len(losses)
    total = len(matches)

    hard_pct = round(hard_carry / total * 100, 1) if total > 0 else 0
    svp_pct = round(svp_loss / total * 100, 1) if total > 0 else 0
    crash_pct = round(crash_loss / total * 100, 1) if total > 0 else 0

    if hard_pct > 20:
        carry_verdict = "你是队伍的绝对核心——超1/5的局靠你Carry赢下。"
    elif hard_pct > 10:
        carry_verdict = "有一定Carry能力，能在关键局站出来。"
    else:
        carry_verdict = "更偏团队型选手，不依赖个人Carry取胜。"

    if svp_pct > 15:
        svp_verdict = f"但 {svp_pct}% 的局是SVP尽力局——队友不给力是最大痛点。"
    elif crash_pct > 15:
        svp_verdict = f"有 {crash_pct}% 的局崩盘（KDA<1+低评分），需要减少'炸线'频率。"
    else:
        svp_verdict = "败局也大多是正常发挥，没有频繁崩盘。"

    return {
        "labels_win": ["硬Carry", "稳定参与", "躺赢"],
        "win_data": [hard_carry, contributed, got_carried],
        "labels_loss": ["尽力局(SVP)", "普通败局", "崩盘局"],
        "loss_data": [svp_loss, normal_loss, crash_loss],
        "total_wins": total_wins, "total_losses": total_losses,
        "hard_carry_pct": hard_pct, "svp_pct": svp_pct, "crash_pct": crash_pct,
        "summary": f"{carry_verdict} {svp_verdict}",
    }

def _analyze_multi_kill_impact(matches: list[dict]) -> dict:
    """多杀含金量分析：各多杀等级的胜率与频率分布。"""
    if not matches:
        return {"labels": [], "winrates": [], "counts": [], "total_games": 0,
                "penta_loss_games": [], "summary": "暂无数据。"}

    total = len(matches)

    # 按最高多杀等级分组
    tiers = [
        ("无多杀", lambda m: m["double_kills"] == 0 and m["triple_kills"] == 0 and m["quadra_kills"] == 0 and m["penta_kills"] == 0),
        ("双杀", lambda m: m["double_kills"] > 0 and m["triple_kills"] == 0 and m["quadra_kills"] == 0 and m["penta_kills"] == 0),
        ("三杀", lambda m: m["triple_kills"] > 0 and m["quadra_kills"] == 0 and m["penta_kills"] == 0),
        ("四杀", lambda m: m["quadra_kills"] > 0 and m["penta_kills"] == 0),
        ("五杀", lambda m: m["penta_kills"] > 0),
    ]

    labels = []
    winrates = []
    counts = []
    penta_loss_games = []

    for label, pred in tiers:
        group = [m for m in matches if pred(m)]
        if not group:
            continue
        labels.append(label)
        counts.append(len(group))
        wr = _win_rate(sum(1 for m in group if m["win"]), len(group))
        winrates.append(wr)

        # 记录五杀败局（悲剧故事）
        if label == "五杀":
            for m in group:
                if not m["win"]:
                    champ = _champion_name(m["champion_id"])
                    date_str = m["_dt"].strftime("%m/%d") if m["_dt"] else "?"
                    penta_loss_games.append(f"{date_str} {champ} 五杀仍败")

    # 计算多杀频率
    total_multi = sum(1 for m in matches if m["double_kills"] > 0 or m["triple_kills"] > 0 or
                      m["quadra_kills"] > 0 or m["penta_kills"] > 0)
    multi_rate = round(total_multi / total * 100, 1) if total > 0 else 0

    # 分析多杀质量
    if len(winrates) >= 2 and winrates[-1] and winrates[0]:
        if winrates[-1] > winrates[0] + 20:
            quality_verdict = "多杀能显著提升胜率——你的高光时刻直接转化为胜利。"
        else:
            quality_verdict = "多杀与胜率关系不绝对——个人表现好不一定赢，团队配合更重要。"
    else:
        quality_verdict = f"共 {total_multi} 场有多杀记录（{multi_rate}%）。"

    return {
        "labels": labels, "winrates": winrates, "counts": counts, "total_games": total,
        "penta_loss_games": penta_loss_games, "multi_rate": multi_rate,
        "penta_total": sum(1 for m in matches if m["penta_kills"] > 0),
        "summary": f"{quality_verdict}" +
                   (f" ⚠️ {len(penta_loss_games)} 次五杀仍然落败——个人英雄主义不足以逆天改命。" if penta_loss_games else ""),
    }

def _analyze_lp_efficiency(matches: list[dict]) -> dict:
    """LP爬分效率：排位LP净变化/游戏时长 = 实际上分速率。"""
    ranked = [m for m in matches if m.get("game_queue_id") == 420]
    if not ranked or len(ranked) < 5:
        return {"avg_lp_per_hr": 0, "by_champ": [], "by_position": [],
                "trend_labels": [], "trend_lp_hr": [], "summary": "排位数据不足（需≥5场排位）。"}

    # 需要按时间排序来跟踪LP变化
    ranked_sorted = sorted(ranked, key=lambda m: m["_dt"] or datetime.min)

    # 计算LP变化
    lp_changes = []
    total_lp_change = 0
    total_hrs = 0
    for i in range(len(ranked_sorted)):
        cur = ranked_sorted[i]
        dur_hrs = cur["game_time_played"] / 3600
        total_hrs += dur_hrs
        # 估算LP变化：win≈+20LP, loss≈-18LP（近似）
        # 如果有相邻对局的LP记录则使用实际值
        if i < len(ranked_sorted) - 1:
            nxt = ranked_sorted[i + 1]
            cur_lp = _total_lp(cur.get("tier", ""), cur.get("league_points", 0))
            nxt_lp = _total_lp(nxt.get("tier", ""), nxt.get("league_points", 0))
            if cur_lp is not None and nxt_lp is not None:
                lp_change = nxt_lp - cur_lp
                lp_changes.append({"lp": lp_change, "hrs": dur_hrs, "champion": cur["champion_id"],
                                   "position": cur["position"], "dt": cur["_dt"]})

    # 若无法从LP记录计算，使用胜率估算
    if not lp_changes:
        for m in ranked_sorted:
            dur_hrs = m["game_time_played"] / 3600
            est_lp = 20 if m["win"] else -18
            lp_changes.append({"lp": est_lp, "hrs": dur_hrs, "champion": m["champion_id"],
                               "position": m["position"], "dt": m["_dt"]})

    total_lp_change = sum(lc["lp"] for lc in lp_changes)
    avg_lp_per_hr = round(total_lp_change / total_hrs, 1) if total_hrs > 0 else 0

    # 按英雄的 LP/小时
    by_champ: dict[int, list[dict]] = defaultdict(list)
    for lc in lp_changes:
        by_champ[lc["champion"]].append(lc)
    champ_lp = []
    for cid, changes in by_champ.items():
        if len(changes) < 3:
            continue
        lp_sum = sum(c["lp"] for c in changes)
        hrs_sum = sum(c["hrs"] for c in changes)
        lp_hr = round(lp_sum / hrs_sum, 1) if hrs_sum > 0 else 0
        champ_lp.append({"name": _champion_name(cid), "lp_per_hr": lp_hr, "games": len(changes)})
    champ_lp.sort(key=lambda x: x["lp_per_hr"], reverse=True)

    # 按位置的 LP/小时
    by_pos: dict[str, list[dict]] = defaultdict(list)
    for lc in lp_changes:
        by_pos[lc["position"]].append(lc)
    pos_lp = []
    for pos, changes in by_pos.items():
        if len(changes) < 3 or pos == "Invalid":
            continue
        lp_sum = sum(c["lp"] for c in changes)
        hrs_sum = sum(c["hrs"] for c in changes)
        lp_hr = round(lp_sum / hrs_sum, 1) if hrs_sum > 0 else 0
        pos_lp.append({"name": pos, "lp_per_hr": lp_hr, "games": len(changes)})
    pos_lp.sort(key=lambda x: x["lp_per_hr"], reverse=True)

    # 滚动 LP 效率趋势（每10场）
    trend_labels = []
    trend_lp_hr = []
    window = min(10, len(lp_changes))
    for i in range(0, len(lp_changes) - window + 1, max(1, window // 2)):
        window_data = lp_changes[i:i + window]
        lp_sum = sum(w["lp"] for w in window_data)
        hrs_sum = sum(w["hrs"] for w in window_data)
        lp_hr = round(lp_sum / hrs_sum, 1) if hrs_sum > 0 else 0
        mid_idx = i + window // 2
        if mid_idx < len(ranked_sorted) and ranked_sorted[mid_idx]["_dt"]:
            trend_labels.append(ranked_sorted[mid_idx]["_dt"].strftime("%m/%d"))
        else:
            trend_labels.append(f"#{mid_idx + 1}")
        trend_lp_hr.append(lp_hr)

    if avg_lp_per_hr > 5:
        verdict = f"LP效率 {avg_lp_per_hr}/小时——上分速度不错，保持这个节奏！"
    elif avg_lp_per_hr > 0:
        verdict = f"LP效率 {avg_lp_per_hr}/小时——缓慢上分中，需要提高胜率或缩短对局时长。"
    elif avg_lp_per_hr > -5:
        verdict = f"LP效率 {avg_lp_per_hr}/小时——基本在原地踏步，需要突破瓶颈。"
    else:
        verdict = f"LP效率 {avg_lp_per_hr}/小时——正在掉分，建议暂停排位调整状态。"

    return {
        "avg_lp_per_hr": avg_lp_per_hr, "by_champ": champ_lp[:8], "by_position": pos_lp,
        "trend_labels": trend_labels, "trend_lp_hr": trend_lp_hr,
        "total_lp_change": total_lp_change, "total_hrs": round(total_hrs, 1),
        "summary": verdict + f" 共 {len(ranked_sorted)} 场排位，{round(total_hrs, 1)} 小时，净LP变化 {total_lp_change:+}。",
    }

def _analyze_prime_time_matrix(matches: list[dict]) -> dict:
    """时间交互热力图：星期×2小时段的胜率二维矩阵（12列，每列2小时）。"""
    if not matches or len(matches) < 20:
        return {"cells": [], "day_labels": [], "hour_labels": [],
                "best_cell": "", "worst_cell": "", "summary": "数据不足（需≥20场）。",
                "game_cells": []}

    NUM_SLOTS = 12  # 12 个 2 小时段
    # 构建 7×12 矩阵（每格 2 小时：0-1, 2-3, ..., 22-23）
    matrix = [[{"wr": 0, "games": 0, "wins": 0} for _ in range(NUM_SLOTS)] for _ in range(7)]

    for m in matches:
        if not m["_dt"]:
            continue
        dow = m["_dt"].weekday()  # 0=Monday
        hour = m["_dt"].hour
        slot = hour // 2  # 0→0, 1→0, 2→1, 3→1, ..., 22→11, 23→11
        cell = matrix[dow][slot]
        cell["games"] += 1
        if m["win"]:
            cell["wins"] += 1

    # 计算胜率
    for d in range(7):
        for s in range(NUM_SLOTS):
            cell = matrix[d][s]
            if cell["games"] > 0:
                cell["wr"] = round(cell["wins"] / cell["games"] * 100, 1)

    # 转为前端可用格式
    cells = []
    game_cells = []
    best_wr = -1
    worst_wr = 101
    best_cell = ""
    worst_cell = ""
    day_labels = _DAYS_CN
    hour_labels = [f"{h*2}-{h*2+1}" for h in range(NUM_SLOTS)]

    for d in range(7):
        for s in range(NUM_SLOTS):
            cell = matrix[d][s]
            if cell["games"] >= 3:
                cells.append({"day": d, "hour": s, "wr": cell["wr"], "games": cell["games"]})
                if cell["wr"] > best_wr:
                    best_wr = cell["wr"]
                    best_cell = f"{day_labels[d]} {hour_labels[s]} ({cell['wr']}%, {cell['games']}场)"
                if cell["wr"] < worst_wr:
                    worst_wr = cell["wr"]
                    worst_cell = f"{day_labels[d]} {hour_labels[s]} ({cell['wr']}%, {cell['games']}场)"
            if cell["games"] > 0:
                game_cells.append({"day": d, "hour": s, "games": cell["games"]})

    return {
        "cells": cells, "game_cells": game_cells,
        "day_labels": day_labels, "hour_labels": hour_labels,
        "best_cell": best_cell, "worst_cell": worst_cell,
        "total_cells": len(cells),
        "summary": f"🏆 最佳时段: {best_cell} | 💀 最差时段: {worst_cell}" +
                   (f"。共 {len(cells)} 个有效时段（≥3场）" if cells else "。注意：空白单元格表示数据不足（<3场）。"),
    }


# ── 赛季历史分析 ──────────────────────────────────────────────────────────────

# WeGame 段位编号 → Y 轴数值（越高段位越高，用于图表展示）
# 层级（低→高）：未定级(0) → 青铜(1) → 白银(2) → 黄金(3) → 铂金(4)
#               → 翡翠(5) → 钻石(6) → 大师(7) → 宗师(8) → 王者(9)
_SEASON_TIER_Y = {
    8: 9, 7: 8, 6: 7, 1: 6, 9: 5,
    2: 4, 3: 3, 4: 2, 5: 1, 255: 0, 0: 0,
}
# Y 轴数值 → 中文段位名
_SEASON_TIER_LABELS = {
    9: "最强王者", 8: "傲世宗师", 7: "超凡大师",
    6: "钻石", 5: "翡翠", 4: "铂金", 3: "黄金",
    2: "白银", 1: "青铜", 0: "未定级",
}

def _analyze_season_stats(season_history: list[dict]) -> dict:
    """从 season_history 表统计各赛季对局数量和胜率（单双排+组排合计）。"""
    if not season_history:
        return {"labels": [], "games": [], "win_rates": [], "summary": "暂无赛季历史数据。"}

    labels = []
    games_list = []
    wr_list = []
    for s in season_history:
        sid = s.get("sid", 0)
        if not sid:
            continue
        labels.append(get_season_name(sid))
        total = (s.get("total_games", 0) or 0) + (s.get("team_total", 0) or 0)
        wins = (s.get("wins", 0) or 0) + (s.get("team_wins", 0) or 0)
        games_list.append(total)
        wr_list.append(round(wins / total * 100, 1) if total > 0 else None)

    if not labels:
        return {"labels": [], "games": [], "win_rates": [], "summary": "暂无有效赛季数据。"}

    overall_games = sum(games_list)
    summary_parts = [f"共 {overall_games} 场覆盖 {len(labels)} 个赛季"]
    if games_list and max(games_list) > 0:
        max_idx = games_list.index(max(games_list))
        summary_parts.append(f"最多场次赛季 {labels[max_idx]}（{max(games_list)}场）")

    return {
        "labels": labels,
        "games": games_list,
        "win_rates": wr_list,
        "summary": " · ".join(summary_parts) + "。",
    }


def _analyze_season_tier_timeline(season_history: list[dict]) -> dict:
    """赛季段位演进：折线图展示单双排和组排段位跨赛季变化。"""
    if not season_history:
        return {"labels": [], "solo_tiers": [], "flex_tiers": [],
                "summary": "暂无赛季历史数据。"}

    # 过滤有排位数据的赛季（单双排或组排至少一个有数据）
    active = [s for s in season_history
              if (s.get("total_games") or 0) > 0 or (s.get("team_total") or 0) > 0]
    if not active:
        return {"labels": [], "solo_tiers": [], "flex_tiers": [],
                "summary": "暂无赛季段位数据。"}

    labels = [get_season_name(s["sid"]) for s in active]
    solo_tiers = [_SEASON_TIER_Y.get(s.get("tier", 255), 0) for s in active]
    flex_tiers = [_SEASON_TIER_Y.get(s.get("team_tier", 255), 0) for s in active]

    # 生成摘要
    solo_peaks = [(i, v) for i, v in enumerate(solo_tiers) if v > 0]
    if solo_peaks:
        peak_idx, peak_val = max(solo_peaks, key=lambda x: x[1])
        peak_label = _SEASON_TIER_LABELS.get(peak_val, "")
        peak_season = labels[peak_idx]
        current_tier = _SEASON_TIER_LABELS.get(solo_tiers[-1], "") if solo_tiers else ""
        summary = f"共 {len(active)} 个赛季，最高段位 {peak_label}（{peak_season}），当前 {current_tier}。"
    else:
        summary = f"共 {len(active)} 个赛季，暂无段位记录。"

    if len(active) == 1:
        summary += " 仅有1个赛季数据，趋势分析需多个赛季。"

    return {"labels": labels, "solo_tiers": solo_tiers, "flex_tiers": flex_tiers,
            "summary": summary}


# ── 生涯全景分析（summoner_profile + career_overview） ─────────────────────

def _analyze_summoner_profile(
    profile: dict | None,
    career: dict | None,
    overview: dict,
) -> dict:
    """整合 summoner_profile 和 career_overview，生成生涯全景分析。"""
    result = {
        "has_profile": profile is not None,
        "has_career": career is not None,
    }
    if not profile and not career:
        return result

    # 召唤师基本信息
    if profile:
        result["summoner_name"] = profile.get("summoner_name", "")
        result["level"] = profile.get("level", 0)

    # 1. 生涯里程碑
    result["milestones"] = _calc_career_milestones(profile, career, overview)

    # 2. 全模式分布
    if career:
        result["mode_distribution"] = _calc_mode_distribution(career)

    # 3. 生涯纪录榜
    if profile:
        result["records"] = _calc_records_board(profile)

    # 4. 近30天状态
    if profile:
        result["recent30"] = _calc_recent30_status(profile)

    # 5. 当前赛季
    if profile:
        result["season_info"] = _calc_season_info(profile)

    return result


def _calc_career_milestones(profile, career, overview):
    """对比生涯总计 vs 已下载数据。"""
    m = {}
    if career:
        m["career_total_games"] = career.get("total_all_games", 0) or 0
    m["analyzed_games"] = overview.get("total_games", 0) or 0

    if profile:
        m["total_kills"] = profile.get("total_kills", 0) or 0
        m["total_assists"] = profile.get("total_assists", 0) or 0
        m["total_penta"] = profile.get("total_penta_kills", 0) or 0
        m["total_mvps"] = profile.get("total_mvp_times", 0) or 0
        m["total_svps"] = profile.get("total_svp_times", 0) or 0
        m["max_streak"] = profile.get("max_consecutive_wins", 0) or 0
        m["total_ward"] = profile.get("total_ward_placed", 0) or 0
        m["level"] = profile.get("level", 0) or 0
        praise = profile.get("praise", 0) or 0
        discredit = profile.get("discredit", 0) or 0
        total_fb = praise + discredit
        m["praise_ratio"] = round(praise / total_fb * 100, 1) if total_fb > 0 else 0

    if career:
        total = m.get("career_total_games", 0)
        analyzed = m.get("analyzed_games", 0)
        m["coverage_pct"] = round(analyzed / total * 100, 1) if total > 0 else 0
    return m


def _calc_mode_distribution(career):
    """计算全模式生涯分布。"""
    modes = [
        ("排位", career.get("total_rank_games", 0), career.get("total_rank_wins", 0)),
        ("大乱斗", career.get("total_aram_games", 0), career.get("total_aram_wins", 0)),
        ("匹配", career.get("total_match_games", 0), career.get("total_match_wins", 0)),
        ("组排", career.get("total_teamrank_games", 0), career.get("total_teamrank_wins", 0)),
        ("人机", career.get("total_ai_games", 0), career.get("total_ai_wins", 0)),
        ("Clash", career.get("total_clash_games", 0), 0),
    ]
    filtered = []
    for name, games, wins in modes:
        if games > 0:
            wr = _win_rate(wins or 0, games) if wins is not None else None
            filtered.append({"name": name, "games": games, "wins": wins or 0, "win_rate": wr})

    filtered.sort(key=lambda x: x["games"], reverse=True)
    total_g = sum(m["games"] for m in filtered)
    for m in filtered:
        m["pct"] = round(m["games"] / total_g * 100, 1) if total_g > 0 else 0

    if not filtered:
        return {"modes": [], "total_games": 0, "summary": "", "wr_summary": ""}

    summary = f"生涯共 {total_g} 场，{filtered[0]['name']} {filtered[0]['games']} 场最多（{filtered[0]['pct']}%）。"
    wr_list = [f"{m['name']} {m['win_rate']}%" for m in filtered if m['win_rate'] is not None]
    wr_summary = "各模式胜率：" + "、".join(wr_list) if wr_list else ""
    return {"modes": filtered, "total_games": total_g, "summary": summary, "wr_summary": wr_summary}


def _calc_records_board(profile):
    """生涯单局纪录榜。"""
    long_sec = profile.get("longest_game_num", 0) or 0
    long_min = int(long_sec / 60)
    long_display = f"{long_min}min" if long_min > 0 else ""
    pairs = [
        ("单局最高击杀", "most_kills_num", ""),
        ("单局最高助攻", "most_assists_num", ""),
        ("单局最高伤害", "most_damage_num", "num"),
        ("单局最高承伤", "most_damage_taken_num", "num"),
        ("单局最高经济", "most_gold_earned_num", "num"),
        ("单局最高补刀", "most_minions_kill_num", ""),
        ("单局最多推塔", "most_turrets_kill_num", ""),
        ("生涯总超神", "total_god_likes", ""),
    ]
    records = []
    for label, key, fmt in pairs:
        val = profile.get(key)
        if val is not None and val != 0:
            if fmt == "num":
                display = f"{val:,}" if val >= 1000 else str(val)
            else:
                display = str(val)
            records.append({"label": label, "value": display})
    # 生涯最长游戏时间（独立字段，整数分钟）
    if long_display:
        records.append({"label": "生涯最长游戏时间", "value": long_display})
    return records


def _calc_recent30_status(profile):
    """近30天状态。"""
    r = {}
    kills = profile.get("kill_30days", 0) or 0
    deaths = profile.get("death_30days", 0) or 0
    assists = profile.get("assist_30days", 0) or 0
    wins = profile.get("recent_win_times", 0) or 0
    games = profile.get("recent_play_times", 0) or 0

    r["kills"] = kills
    r["deaths"] = deaths
    r["assists"] = assists
    r["kda"] = round((kills + assists) / max(deaths, 1), 2)
    r["wins"] = wins
    r["games"] = games
    r["win_rate"] = _win_rate(wins, games)
    r["kda_score"] = profile.get("recent_kda_score", 0) or 0

    # 解析常用英雄 JSON
    champs_raw = profile.get("common_champions")
    if champs_raw:
        try:
            champs = json.loads(champs_raw) if isinstance(champs_raw, str) else champs_raw
            r["common_champions"] = list(champs)[:5] if isinstance(champs, list) else []
        except (json.JSONDecodeError, TypeError):
            r["common_champions"] = []
    return r


def _calc_season_info(profile):
    """当前赛季信息。"""
    s = {}
    s["total"] = profile.get("season_total", 0) or 0
    s["wins"] = profile.get("season_wins", 0) or 0
    s["losses"] = profile.get("season_losses", 0) or 0
    s["win_rate"] = _win_rate(s["wins"], s["total"])
    s["tier"] = profile.get("season_tier")
    s["lp"] = profile.get("season_win_point", 0) or 0
    # 映射段位中文名
    tier_val = s["tier"]
    if isinstance(tier_val, int) and tier_val in WEGAME_TIER_NAMES:
        s["tier_name"] = WEGAME_TIER_NAMES[tier_val]
    else:
        s["tier_name"] = "未知"
    return s


# ── HTML 生成 ────────────────────────────────────────────────────────────────

def _chart_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)

def _build_css() -> str:
    return """
:root{
--bg:#0a0e14;--bg2:rgba(20,27,34,0.65);--card:#1a2230;--card-alpha:rgba(26,34,48,0.75);--card-hover:#212b38;
--border:#2a3a4a;--text:#d4d8dd;--text2:#8b95a5;--text3:#5a6575;
--gold:#c8aa6e;--blue:#0ac8b9;--green:#2ecc71;--red:#e74c3c;
--blue2:#4a9eff;--purple:#a855f7;--orange:#f59e0b;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-padding-top:92px;scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC",sans-serif;line-height:1.6;min-height:100vh}
a{color:var(--blue);text-decoration:none}
nav{position:sticky;top:0;z-index:100;background:rgba(10,14,20,0.25);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;justify-content:center;align-items:center;gap:10px;overflow-x:auto;white-space:nowrap}
nav .logo{color:var(--gold);font-weight:700;font-size:18px;margin-right:20px}
nav a{color:var(--text2);font-size:14px;padding:8px 14px;border-radius:6px;transition:all .2s}
nav a:hover{color:var(--text);background:var(--card)}
main{max-width:1280px;margin:0 auto;padding:24px 20px 60px}
.hero{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:32px}
.hero-card{background:var(--card-alpha);backdrop-filter:blur(2px);border:1px solid var(--border);border-radius:10px;padding:16px 18px;text-align:center;transition:transform .2s}
.hero-card:hover{transform:translateY(-2px)}
.hero-card .value{font-size:28px;font-weight:700;color:var(--gold)}
.hero-card .label{font-size:12px;color:var(--text2);margin-top:4px}
.hero-card.win .value{color:var(--green)}
.hero-card.loss .value{color:var(--red)}
.player-banner{display:flex;align-items:center;gap:18px;background:linear-gradient(135deg,rgba(200,170,110,0.10),rgba(10,200,185,0.05),rgba(10,14,20,0.6));border:1px solid rgba(200,170,110,0.28);border-radius:14px;padding:20px 28px;margin-bottom:20px}
.player-banner .pb-icon{flex-shrink:0}.player-banner .pb-icon img{width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid rgba(200,170,110,0.35);filter:drop-shadow(0 2px 10px rgba(200,170,110,0.25))}
.player-banner .pb-info{flex:1;min-width:0}
.player-banner .pb-main{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:4px}
.player-banner .pb-name{font-size:26px;font-weight:700;color:var(--gold);letter-spacing:0.5px}
.player-banner .pb-level{display:inline-block;background:rgba(200,170,110,0.12);color:var(--gold);border:1px solid rgba(200,170,110,0.22);border-radius:16px;padding:1px 12px;font-size:13px;font-weight:500;white-space:nowrap}
.player-banner .pb-tier{display:inline-block;background:linear-gradient(135deg,rgba(74,158,255,0.18),rgba(168,85,247,0.12));border:1px solid rgba(74,158,255,0.28);border-radius:16px;padding:1px 14px;font-size:13px;font-weight:600;color:var(--blue2);white-space:nowrap}
.player-banner .pb-sub{font-size:13px;color:var(--text2)}
.player-banner .pb-sub span{color:var(--text);font-weight:500}
.overall-rating{background:linear-gradient(135deg,rgba(200,170,110,0.15),rgba(10,200,185,0.08));border:1px solid var(--gold);border-radius:10px;padding:14px 20px;margin-bottom:16px;font-size:15px;color:var(--gold);text-align:center;font-weight:500}
@media(max-width:640px){.player-banner .pb-name{font-size:20px}.player-banner .pb-icon img{width:40px;height:40px}}
.section{margin-bottom:40px}
.section-title{font-size:22px;font-weight:700;color:var(--gold);margin-bottom:8px;padding-bottom:8px;border-bottom:2px solid var(--border);display:flex;align-items:center;gap:10px}
.section-subtitle{font-size:13px;color:var(--text2);margin-bottom:16px}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}
@media(max-width:768px){.chart-grid{grid-template-columns:1fr}}
.chart-card{background:var(--card-alpha);backdrop-filter:blur(2px);border:1px solid var(--border);border-radius:10px;padding:20px;transition:border-color .2s}
.chart-card:hover{border-color:var(--gold)}
.chart-card h3{font-size:15px;font-weight:600;color:var(--text);margin-bottom:4px}
.chart-card .chart-wrap{position:relative;width:100%;margin:12px 0}
.chart-card .chart-wrap canvas{display:block;width:100%!important;height:100%!important}
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
body{position:relative}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background-image:var(--bg-image,none);background-size:cover;background-position:center;background-repeat:no-repeat;opacity:0.25;z-index:0;pointer-events:none}
body::after{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:linear-gradient(to right,rgba(10,14,20,0.50) 0%,rgba(10,14,20,0.10) 14%,transparent 28%,transparent 72%,rgba(10,14,20,0.10) 86%,rgba(10,14,20,0.50) 100%);z-index:0;pointer-events:none}
main,footer{position:relative;z-index:1}
.skin-switch-btn{flex-shrink:0;background:rgba(200,170,110,0.10);border:1px solid rgba(200,170,110,0.22);color:var(--gold);padding:6px 14px;border-radius:8px;cursor:pointer;font-size:12px;transition:all .2s;white-space:nowrap;user-select:none}
.skin-switch-btn:hover{background:rgba(200,170,110,0.22);border-color:rgba(200,170,110,0.4)}
.skin-switch-btn.loading{opacity:0.5;cursor:wait}
@media(max-width:640px){.skin-switch-btn{padding:4px 10px;font-size:11px}}
"""

def _build_nav(extra_html: str = "") -> str:
    items = [
        ("#overview", "\U0001f4ca 总览"),
        ("#winrate", "\U0001f52e 胜率因子"),
        ("#game-rhythm", "\U0001f3ae 游戏节奏"),
        ("#psychology", "\U0001f9e0 游戏心理"),
        ("#player-level", "\U0001f4c8 玩家水平"),
        ("#attendance", "\U0001f4c5 出勤日历"),
    ]
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in items)
    return f'<nav><span class="logo">⚔️ LOLhistory</span>{extra_html}{links}</nav>'

def _build_hero(results: dict) -> str:
    ov = results.get("overview", {})
    sa = results.get("summoner_profile_analysis", {})
    rating = ov.get("overall_rating", "")

    # 招牌英雄：优先从 overview（需对局列表数据）取，后备英雄池分布的 top 1
    champ_id = ov.get("most_played_champ", 0)
    champ_name = ov.get("most_played_champ_name", "")
    if not champ_id:
        pool = results.get("champion_pool", {})
        pool_freq = pool.get("freq", [])
        if pool_freq:
            top = pool_freq[0]
            champ_id = top.get("champion_id", 0) or 0
            champ_name = top.get("name", "")

    # ── 玩家名片横幅 ──
    banner_html = ""
    player_name = sa.get("summoner_name", "")
    if player_name:
        lv = sa.get("level", 0)
        # 段位徽章
        tier_badge = ""
        season = sa.get("season_info", {})
        if season and season.get("tier_name") and season["tier_name"] != "未知":
            tier_label = season["tier_name"]
            lp = season.get("lp", 0)
            if lp > 0:
                tier_label += f" · {lp}胜点"
            tier_badge = f'<span class="pb-tier">{tier_label}</span>'
        # 组装横幅 — 招牌英雄图标（后备值已由函数顶部计算）
        champ_icon_url = f"https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/champions/{champ_id}.png" if champ_id else ""
        icon_html = f'<img src="{champ_icon_url}" alt="{champ_name}" title="{champ_name}" onerror="this.parentElement.innerHTML=\'⚔️\'">' if champ_icon_url else "⚔️"
        banner_html = f'''<div class="player-banner">
  <div class="pb-icon">{icon_html}</div>
  <div class="pb-info">
    <div class="pb-main">
      <span class="pb-name">{player_name}</span>
      <span class="pb-level">Lv.{lv}</span>
      {tier_badge}
    </div>
  </div>
  <button class="skin-switch-btn loading" id="skinSwitchBtn" title="皮肤检测中…">🎨 背景换肤</button>
</div>'''

    # ── 总体评价 ──
    rating_html = f'<div class="overall-rating">⭐ {rating}</div>' if rating else ""

    # ── 生涯里程碑数据（提前获取，用于后续生涯里程碑区域）──
    milestones_early = sa.get("milestones", {}) if sa.get("has_profile") or sa.get("has_career") else {}

    # ── 近期对局概览卡片 ──
    cards = [
        ("总场次", ov.get("total_games", 0), ""),
        ("胜率", f"{ov.get('win_rate', 0)}%", "win" if ov.get("win_rate", 0) >= 50 else "loss"),
        ("整体 KDA", ov.get("overall_kda", 0), ""),
        ("场均击杀", ov.get("avg_kills", 0), ""),
        ("场均死亡", ov.get("avg_deaths", 0), ""),
        ("场均助攻", ov.get("avg_assists", 0), ""),
        ("场均经济", f"{ov.get('avg_gold', 0):,}", ""),
        ("总 MVP", ov.get("total_mvps", 0), ""),
        ("总 SVP", ov.get("total_svps", 0), ""),
        ("五杀次数", ov.get("total_penta", 0), ""),
        ("四杀次数", ov.get("total_quadra", 0), ""),
        ("最长连胜", f"{ov.get('longest_win_streak', 0)}局", ""),
        ("出勤率", f"{ov.get('attendance', 0)}%", ""),
        ("出勤天数", ov.get("days_active", 0), ""),
        ("英雄池", f"{ov.get('hero_pool', 0)}", ""),
        ("招牌英雄", champ_name, ""),
        ("最高段位", ov.get("highest_tier", "无"), ""),
        ("当前段位", ov.get("current_tier", "无"), ""),
    ]
    html_cards = ""
    for label, value, cls in cards:
        html_cards += f'<div class="hero-card {cls}"><div class="value">{value}</div><div class="label">{label}</div></div>'

    # ── 生涯里程碑（第二行） ──
    extra_html = ""
    milestones = milestones_early
    records = sa.get("records", []) if sa.get("has_profile") else []
    if milestones or records:
        all_cards = []
        # 从 records 中提取可单独排列的条目
        rec_by_label = {r["label"]: r["value"] for r in records}
        if milestones:
            ordered = [
                # 生涯基础
                ("生涯总场次", milestones.get("career_total_games", 0), ""),
                ("生涯总击杀", f"{milestones.get('total_kills', 0):,}", ""),
                ("生涯总助攻", f"{milestones.get('total_assists', 0):,}", ""),
                ("生涯总插眼", f"{milestones.get('total_ward', 0):,}", ""),
                # 连胜与超神
                ("生涯最长连胜", f"{milestones.get('max_streak', 0)}局", ""),
                ("生涯总超神", rec_by_label.pop("生涯总超神", "0"), ""),
                # 荣誉
                ("生涯MVP", milestones.get("total_mvps", 0), ""),
                ("生涯SVP", milestones.get("total_svps", 0), ""),
                # 五杀
                ("生涯五杀", milestones.get("total_penta", 0), ""),
            ]
            all_cards.extend(ordered)
            # 单局纪录
            skip = {"生涯总超神", "生涯最长游戏时间"}
            for rec in records:
                if rec["label"] in skip:
                    continue
                all_cards.append((rec["label"], rec["value"], ""))
            # 生涯最长游戏时间
            if "生涯最长游戏时间" in rec_by_label:
                all_cards.append(("生涯最长游戏时间", rec_by_label["生涯最长游戏时间"], ""))
            # 受欢迎度
            all_cards.append(("受欢迎度", f"{milestones.get('praise_ratio', 0)}%",
                             "win" if milestones.get("praise_ratio", 0) >= 50 else "loss"))
        elif records:
            for rec in records:
                all_cards.append((rec["label"], rec["value"], ""))
        combined = "".join(
            f'<div class="hero-card {cls}"><div class="value">{v}</div><div class="label">{l}</div></div>'
            for l, v, cls in all_cards
        )
        extra_html = f'<div class="section-subtitle" style="margin-top:20px">🏆 生涯里程碑</div><div class="hero">{combined}</div>'

    overview_html = f'<div class="section-subtitle" style="margin-top:16px">📊 近期对局概览</div><div class="hero">{html_cards}</div>'

    return f'<section id="overview">{banner_html}{rating_html}{extra_html}{overview_html}</section>'

def _chart_card(title: str, chart_id: str, summary: str, full_width: bool = False) -> str:
    cls = "chart-card full" if full_width else "chart-card"
    no_data = "数据不足" in summary or "暂无数据" in summary
    summary_cls = "summary na" if no_data else "summary"
    return f"""<div class="{cls}">
<h3>{title}</h3>
<div class="chart-wrap"><canvas id="{chart_id}"></canvas></div>
<p class="{summary_cls}">{summary}</p>
</div>"""

def _build_section_winrate(r: dict) -> str:
    """胜率因子分析 — 报告第1章（总览之后）。"""
    mystery = r.get("mystery_factor", {})
    day = r.get("win_rate_by_day", {})
    hour = r.get("win_rate_by_hour", {})
    side = r.get("win_rate_by_side", {})
    pos = r.get("win_rate_by_position", {})
    lp_r = r.get("win_rate_by_lp", {})
    dur = r.get("win_rate_by_duration", {})
    honors = r.get("honors_impact", {})
    cards = [
        _chart_card("📅 星期几胜率", "chart-day", day.get("summary", "")),
        _chart_card("🕐 时段胜率", "chart-hour", hour.get("summary", "")),
        _chart_card("🔵 红蓝方胜率", "chart-side", side.get("summary", "")),
        _chart_card("🎯 位置胜率", "chart-position", pos.get("summary", "")),
        _chart_card("⏱️ 对局时长胜率", "chart-duration", dur.get("summary", "")),
        _chart_card("📊 LP区间胜率", "chart-lp-range", lp_r.get("summary", "")),
        _chart_card("🔮 胜率极差排名", "chart-mystery", mystery.get("summary", ""), True),
        _chart_card("🏅 荣誉与胜率", "chart-honors", honors.get("summary", ""), True),
    ]
    return f'<section id="winrate" class="section"><div class="section-title">🔮 胜率因子</div><div class="section-subtitle">多维度下钻胜率，定位影响你上分的关键因子</div><div class="chart-grid">{"".join(cards)}</div></section>'

def _build_section_game_rhythm(r: dict) -> str:
    """游戏节奏 — 报告第3章。"""
    sess = r.get("sessions", {})
    omg = r.get("one_more_game", {})
    tilt = r.get("tilt", {})

    # 游戏轮次规模分布（双列）
    size_card = f"""<div class="chart-card">
    <h3>📏 游戏轮次规模分布</h3>
    <div class="chart-wrap"><canvas id="chart-session-size"></canvas></div>
    <p class="summary">{sess.get("size_summary", "")}</p>
    </div>"""

    # 轮次首局开始时间分布
    first_hour_summary = ""
    if sess.get("first_hour_counts"):
        first_peak_hour = max(range(24), key=lambda h: sess["first_hour_counts"][h]) if any(sess["first_hour_counts"]) else 0
        first_hour_summary = f"首局最常在 {first_peak_hour}:00-{first_peak_hour}:59 时段开始——这是你'开张'的高频时段。"

    # 轮次末局结束时间分布
    last_hour_summary = ""
    if sess.get("last_hour_counts"):
        peak_hour = max(range(24), key=lambda h: sess["last_hour_counts"][h]) if any(sess["last_hour_counts"]) else 0
        last_hour_summary = f"游戏轮次最常在 {peak_hour}:00-{peak_hour}:59 时段结束——这是你'收工'的高峰时段。"

    cards = [
        size_card,
        _chart_card("🌅 轮次首局开始时间分布", "chart-session-first-hour", first_hour_summary),
        _chart_card("🌙 轮次末局结束时间分布", "chart-session-last-hour", last_hour_summary),
        _chart_card("📈 轮次内第N局胜率", "chart-session-pos", sess.get("pos_summary", "")),
        _chart_card("🎰 '再来一局'陷阱", "chart-one-more", omg.get("summary", "")),
        _chart_card("🎢 输后与赢后胜率", "chart-tilt", tilt.get("summary", "")),
    ]
    return f'<section id="game-rhythm" class="section"><div class="section-title">🎮 游戏节奏</div><div class="section-subtitle">游戏轮次模式（相邻对局间隔较短的连续游戏序列）、连续对局行为与胜率转移规律</div><div class="chart-grid">{"".join(cards)}</div></section>'

def _build_section_psychology(r: dict) -> str:
    """游戏心理 — 报告第4章。"""
    streaks = r.get("streaks", {})
    consistency = r.get("consistency", {})
    boom = r.get("boomerang_effect", {})

    cards = [
        _chart_card("🔥 胜负连势分析", "chart-streaks", streaks.get("summary", "")),
        _chart_card("📊 发挥稳定性", "chart-consistency", consistency.get("summary", "")),
        _chart_card("🚫 挂机影响", "chart-afk", r.get("afk_impact", {}).get("summary", "")),
        _chart_card("🏳️ 投降分析", "chart-surrender", r.get("surrender", {}).get("summary", "")),
        _chart_card("🪃 过度自信与救赎效应", "chart-boomerang", boom.get("summary", ""), True),
    ]
    return f'<section id="psychology" class="section"><div class="section-title">🧠 游戏心理</div><div class="section-subtitle">心态波动、情绪韧性与行为模式深度剖析</div><div class="chart-grid">{"".join(cards)}</div></section>'


def _build_section_player_level(r: dict) -> str:
    """玩家水平 — 报告第5章。"""
    pool = r.get("champion_pool", {})
    radar = r.get("champion_radar", {})
    mk = r.get("multi_kill_impact", {})
    cp = r.get("carry_profile", {})
    gold = r.get("gold_efficiency", {})
    season_tier = r.get("season_tier_timeline", {})
    sa = r.get("summoner_profile_analysis", {})
    mode_dist = sa.get("mode_distribution", {}) if sa.get("has_career") else {}

    cards = []
    # ── 生涯全景：赛季段位演进 + 全模式分布 — 放在最前面 ──
    cards.append(_chart_card("📈 赛季段位演进", "chart-season-tier-timeline", season_tier.get("summary", ""), True))
    if mode_dist.get("modes"):
        cards.append(_chart_card("📊 全模式生涯分布", "chart-career-mode-dist", mode_dist.get("summary", "")))
        cards.append(_chart_card("🎯 各模式胜率对比", "chart-career-mode-wr", mode_dist.get("wr_summary", "")))

    # ── 英雄池与个人能力 ──
    cards.append(_chart_card("📚 英雄池分布", "chart-pool", pool.get("summary", ""), True))
    cards.append(_chart_card("🎯 招牌英雄雷达", "chart-radar", radar.get("summary", ""), True))
    cards.append(_chart_card("⚔️ 多杀含金量", "chart-multikill", mk.get("summary", "")))
    cards.append(_chart_card("🎭 Carry依赖度画像", "chart-carry-profile", cp.get("summary", "")))
    cards.append(_chart_card("💰 经济效率分析", "chart-gpm", gold.get("summary", ""), True))

    cards_html = "".join(c for c in cards if c)
    return f'<section id="player-level" class="section"><div class="section-title">📈 玩家水平</div><div class="section-subtitle">段位演进、生涯全景、英雄池深度与个人能力画像</div><div class="chart-grid">{cards_html}</div></section>'

def _build_section_attendance(r: dict) -> str:
    """出勤日历 — 报告第6章。"""
    att = r.get("attendance", {})
    rp = r.get("rank_progression", {})
    pt = r.get("prime_time_matrix", {})

    # ── 关键日期指标卡片 ──
    best = att.get("best_day")
    worst = att.get("worst_day")
    most_t = att.get("most_time_day")
    most_g = att.get("most_gain_day")
    most_l = att.get("most_loss_day")
    most_h = att.get("most_honors_day")
    key_cards_html = ""
    if best:
        key_cards_html += f'<div class="hero-card win"><div class="value">{best["win_rate"]}%</div><div class="label">🏆 胜率最高日<br>{best["date"]}<br>{best["wins"]}W{best["losses"]}L · {best["games"]}场</div></div>'
    if worst:
        key_cards_html += f'<div class="hero-card loss"><div class="value">{worst["win_rate"]}%</div><div class="label">💔 胜率最低日<br>{worst["date"]}<br>{worst["wins"]}W{worst["losses"]}L · {worst["games"]}场</div></div>'
    if most_t:
        key_cards_html += f'<div class="hero-card"><div class="value">{most_t["total_time_min"]}min</div><div class="label">⏰ 最长游戏日<br>{most_t["date"]}<br>{most_t["games"]}场</div></div>'
    if most_g:
        key_cards_html += f'<div class="hero-card win"><div class="value">+{most_g["lp_change"]}</div><div class="label">📈 上分最多日<br>{most_g["date"]}<br>{most_g["games"]}场</div></div>'
    if most_l:
        key_cards_html += f'<div class="hero-card loss"><div class="value">{most_l["lp_change"]}</div><div class="label">📉 掉分最多日<br>{most_l["date"]}<br>{most_l["games"]}场</div></div>'
    if most_h:
        key_cards_html += f'<div class="hero-card"><div class="value">{most_h["games"]}场</div><div class="label">🏅 最多荣誉日<br>{most_h["date"]}<br>多项荣誉加身</div></div>'

    # 滚动胜率概要
    rolling_summary = rp.get("rolling_summary", "")
    if not rolling_summary and rp.get("rolling_wr"):
        rw = rp["rolling_wr"]
        recent_avg = round(sum(rw[-10:]) / min(len(rw), 10), 1) if rw else 0
        trend = "上升" if len(rw) >= 20 and sum(rw[-10:]) > sum(rw[:10]) else ("下降" if len(rw) >= 20 and sum(rw[-10:]) < sum(rw[:10]) else "稳定")
        rolling_summary = f"近10场滚动胜率均值 {recent_avg}%，近期趋势{trend}。滚动胜率持续高于50%是上分的关键信号。"

    # LP变化概要
    lp_days = [d for d in att.get("days", []) if d["lp_change"] != 0]
    lp_summary = ""
    if lp_days:
        gain_days = sum(1 for d in lp_days if d["lp_change"] > 0)
        loss_days = sum(1 for d in lp_days if d["lp_change"] < 0)
        lp_summary = f"{len(lp_days)} 天有LP变化：{gain_days} 天上涨，{loss_days} 天下跌。绿色柱=上分日，红色柱=掉分日。"

    season_stats = r.get("season_stats", {})
    cards = []
    # ── 各赛季对局数量与胜率（全宽） ──
    cards.append(_chart_card("🏆 各赛季对局数量与胜率", "chart-season-stats", season_stats.get("summary", ""), True))
    if key_cards_html:
        cards.append(f'<div class="chart-card full"><h3>🗓️ 关键日期</h3><p style="color:#8b95a5;font-size:12px;margin-bottom:8px">（仅统计 ≥3 场的日期）</p><div class="hero">{key_cards_html}</div></div>')

    cards.append(_chart_card("📅 出勤日历热力图", "chart-cal-heatmap", att.get("summary", ""), True))
    cards.append(_chart_card("📉 10场滚动胜率", "chart-rolling-wr", rolling_summary, True))

    if pt.get("cells"):
        cards.append(f"""<div class="chart-card full">
    <h3>🗺️ 游戏时段热力图（胜率）</h3>
    <div id="heatmap-prime-time" style="overflow-x:auto"></div>
    <p class="summary">{pt.get('summary', '')}</p>
    </div>""")
    if pt.get("game_cells"):
        cards.append(f"""<div class="chart-card full">
    <h3>📊 对局数量热力图</h3>
    <div id="heatmap-game-count" style="overflow-x:auto"></div>
    <p class="summary">展示各时段的对局频次分布，颜色越深表示该时段对局越多。</p>
    </div>""")

    cards.append(_chart_card("📈 段位LP趋势", "chart-lp", rp.get("summary", ""), True))
    cards.append(_chart_card("📊 每日LP变化", "chart-daily-lp", lp_summary, True))

    return f'<section id="attendance" class="section"><div class="section-title">📅 出勤日历</div><div class="section-subtitle">游戏习惯、活跃时段与段位变化全景</div><div class="chart-grid">{"".join(cards)}</div></section>'

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
      {{label:'胜率 %',data:{_chart_json(day.get('win_rates',[]))},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1,yAxisID:'y'}},
      {{label:'场次',data:{_chart_json(day.get('games',[]))},backgroundColor:'rgba(168,85,247,0.3)',borderColor:'#a855f7',borderWidth:1,yAxisID:'y1',type:'line',tension:0.3}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{
      y:{{type:'linear',position:'left',title:{{display:true,text:'胜率 %',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},max:100}},
      y1:{{type:'linear',position:'right',title:{{display:true,text:'场次',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{display:false}}}},
      x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}
    }}
  }}
}});""")

    # 时段胜率（null = 场次不足被遮罩）
    hour = r.get("win_rate_by_hour", {})
    h_wr = hour.get("win_rates", [])
    h_g = hour.get("games", [])
    # 在标签上显示场次
    h_labels_with_count = [f"{h}:00 ({g}场)" if g > 0 else f"{h}:00" for h, g in zip(range(24), h_g)]
    parts.append(f"""new Chart(document.getElementById('chart-hour'),{{
  type:'bar',
  data:{{labels:{_chart_json(h_labels_with_count)},
    datasets:[
      {{label:'胜率 %',data:{_chart_json(h_wr)},backgroundColor:'rgba(10,200,185,0.7)',borderColor:'#0ac8b9',borderWidth:1,yAxisID:'y'}},
      {{label:'场次',data:{_chart_json(h_g)},backgroundColor:'rgba(168,85,247,0.3)',borderColor:'#a855f7',borderWidth:1,yAxisID:'y1',type:'line',tension:0.3}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}},tooltip:{{callbacks:{{label:function(ctx){{if(ctx.datasetIndex===0&&ctx.raw===null)return'(场次不足，不显示胜率)';return ctx.dataset.label+': '+ctx.raw+'%';}}}}}}}},
    scales:{{
      y:{{type:'linear',position:'left',title:{{display:true,text:'胜率 %',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},max:100}},
      y1:{{type:'linear',position:'right',ticks:{{color:'#8b95a5'}},grid:{{display:false}}}},
      x:{{ticks:{{color:'#8b95a5',maxRotation:45}},grid:{{color:'#2a3a4a'}}}}
    }}
  }}
}});""")

    # 红蓝方 grouped bar
    side = r.get("win_rate_by_side", {})
    s_games = side.get("games", [0, 0])
    s_wins = side.get("wins", [0, 0])
    s_labels_with_cnt = [f"{lbl} ({s_games[i]}场)" for i, lbl in enumerate(side.get("labels", ["蓝色方", "红色方"]))]
    parts.append(f"""new Chart(document.getElementById('chart-side'),{{
  type:'bar',
  data:{{labels:{_chart_json(s_labels_with_cnt)},
    datasets:[
      {{label:'胜',data:{_chart_json(s_wins)},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'负',data:{_chart_json([s_games[0]-s_wins[0],s_games[1]-s_wins[1]])},backgroundColor:'rgba(231,76,60,0.5)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'场次',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 位置胜率（标签含场次）
    pos = r.get("win_rate_by_position", {})
    p_labels = pos.get("labels", [])
    p_games = pos.get("games", [])
    n = len(p_labels)
    p_labels_with_cnt = [f"{p_labels[i]} ({p_games[i]}场)" if i < len(p_games) else p_labels[i] for i in range(n)]
    parts.append(f"""new Chart(document.getElementById('chart-position'),{{
  type:'bar',
  data:{{labels:{_chart_json(p_labels_with_cnt)},
    datasets:[{{label:'胜率 %',data:{_chart_json(pos.get('win_rates',[]))},backgroundColor:{_chart_json([_CHART_COLORS[i%10] for i in range(n)])},borderColor:{_chart_json([_CHART_BORDERS[i%10] for i in range(n)])},borderWidth:1}}]
  }},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{display:false}}}},
    scales:{{x:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # LP 区间胜率
    lp_r = r.get("win_rate_by_lp", {})
    lp_labels = lp_r.get("labels", [])
    lp_games = lp_r.get("games", [])
    lp_labels_with_cnt = [f"{lbl} ({lp_games[i]}场)" if i < len(lp_games) else lbl for i, lbl in enumerate(lp_labels)]
    parts.append(f"""new Chart(document.getElementById('chart-lp-range'),{{
  type:'bar',
  data:{{labels:{_chart_json(lp_labels_with_cnt)},
    datasets:[{{label:'胜率 %',data:{_chart_json(lp_r.get('win_rates',[]))},backgroundColor:'rgba(245,158,11,0.7)',borderColor:'#f59e0b',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 时长胜率（标签含场次）
    dur = r.get("win_rate_by_duration", {})
    dur_labels = dur.get("labels", [])
    dur_games = dur.get("games", [])
    dur_labels_with_cnt = [f"{dur_labels[i]} ({dur_games[i]}场)" if i < len(dur_games) else dur_labels[i] for i in range(len(dur_labels))]
    parts.append(f"""new Chart(document.getElementById('chart-duration'),{{
  type:'bar',
  data:{{labels:{_chart_json(dur_labels_with_cnt)},
    datasets:[{{label:'胜率 %',data:{_chart_json(dur.get('win_rates',[]))},backgroundColor:'rgba(20,184,166,0.7)',borderColor:'#14b8a6',borderWidth:1}}]
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
    datasets:[{{label:'胜率极差 %',data:{_chart_json([d['variance'] for d in dims])},backgroundColor:'rgba(236,72,153,0.7)',borderColor:'#ec4899',borderWidth:1}}]
  }},
  options:{{indexAxis:'y',responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 荣誉影响（标签含场次）
    honors = r.get("honors_impact", {})
    hlist = honors.get("honors", [])
    h_labels_with_cnt = [f"{h['name']} ({h['games_with']}场)" for h in hlist]
    parts.append(f"""new Chart(document.getElementById('chart-honors'),{{
  type:'bar',
  data:{{labels:{_chart_json(h_labels_with_cnt)},
    datasets:[
      {{label:'获得荣誉',data:{_chart_json([h['wr_with'] for h in hlist])},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'未获得荣誉',data:{_chart_json([h['wr_without'] for h in hlist])},backgroundColor:'rgba(231,76,60,0.4)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 英雄雷达（招牌英雄 + 全对局平均背景）
    radar = r.get("champion_radar", {})
    champs = radar.get("champions", [])
    dims_radar = radar.get("dimensions", [])
    all_avg = radar.get("all_average")
    radar_datasets = []
    # 先添加全对局平均作为灰色背景
    if all_avg:
        avg_vals = [all_avg["metrics"].get(d, 0) for d in dims_radar]
        radar_datasets.append({
            "label": all_avg.get("name", "全对局平均"),
            "data": avg_vals,
            "borderColor": "rgba(149,165,166,0.5)",
            "backgroundColor": "rgba(149,165,166,0.08)",
            "borderWidth": 1,
            "borderDash": [5, 5],
        })
    # 招牌英雄
    for i, ch in enumerate(champs):
        vals = [ch["metrics"].get(d, 0) for d in dims_radar]
        color_key = _CHART_COLORS[i % 10]
        border_key = _CHART_BORDERS[i % 10]
        radar_datasets.append({
            "label": f"{ch['name']} ({ch['games']}场, {ch['win_rate']}%)",
            "data": vals,
            "borderColor": border_key.replace("1.0", "0.8"),
            "backgroundColor": color_key.replace("0.8", "0.2"),
            "borderWidth": 2,
        })
    parts.append(f"""new Chart(document.getElementById('chart-radar'),{{
  type:'radar',
  data:{{labels:{_chart_json(dims_radar)},datasets:{_chart_json(radar_datasets)}}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{r:{{min:0,max:100,ticks:{{color:'#8b95a5',backdropColor:'transparent'}},grid:{{color:'#2a3a4a'}},pointLabels:{{color:'#8b95a5'}}}}}}
  }}
}});""")

    # 英雄池
    pool = r.get("champion_pool", {})
    freq = pool.get("freq", [])
    pool_labels = [f"{item['name']} {item.get('win_rate', 0):.0f}%" for item in freq]
    parts.append(f"""new Chart(document.getElementById('chart-pool'),{{
  type:'bar',
  data:{{labels:{_chart_json(pool_labels)},
    datasets:[
      {{label:'胜',data:{_chart_json([f['wins'] for f in freq])},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'负',data:{_chart_json([f['losses'] for f in freq])},backgroundColor:'rgba(231,76,60,0.4)',borderColor:'#e74c3c',borderWidth:1}}
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
    datasets:[{{label:'累计LP',data:{_chart_json(rp.get('lp_values',[]))},borderColor:'#c8aa6e',backgroundColor:'rgba(200,170,110,0.1)',fill:true,tension:0.2,pointRadius:0}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'综合LP',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5',maxTicksLimit:30}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 各赛季对局数量与胜率（出勤日历最前）
    ss = r.get("season_stats", {})
    if ss.get("labels"):
        parts.append(f"""new Chart(document.getElementById('chart-season-stats'),{{
  type:'bar',
  data:{{labels:{_chart_json(ss.get('labels',[]))},
    datasets:[
      {{label:'对局数量',data:{_chart_json(ss.get('games',[]))},backgroundColor:'rgba(74,158,255,0.6)',borderColor:'#4a9eff',borderWidth:1,yAxisID:'y',order:2}},
      {{label:'胜率 %',data:{_chart_json(ss.get('win_rates',[]))},borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,0.08)',borderWidth:2.5,pointRadius:5,pointBackgroundColor:'#f59e0b',pointBorderColor:'#f59e0b',yAxisID:'y1',type:'line',tension:0.3,fill:false,spanGaps:true,order:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{labels:{{color:'#8b95a5',usePointStyle:true}}}}}},
    scales:{{
      y:{{type:'linear',position:'left',title:{{display:true,text:'场次',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},beginAtZero:true}},
      y1:{{type:'linear',position:'right',title:{{display:true,text:'胜率 %',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{display:false}},min:0,max:100}},
      x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}
    }}
  }}
}});""")

    # 滚动胜率
    parts.append(f"""new Chart(document.getElementById('chart-rolling-wr'),{{
  type:'line',
  data:{{labels:{_chart_json(rp.get('labels',[]))},
    datasets:[
      {{label:'10场滚动胜率',data:{_chart_json(rp.get('rolling_wr',[]))},borderColor:'#0ac8b9',tension:0.3,pointRadius:0,fill:false}},
      {{label:'50% 基准线',data:{_chart_json([50]*len(rp.get('labels',[])))},borderColor:'rgba(255,255,255,0.2)',borderDash:[5,5],pointRadius:0,fill:false}}
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
    datasets:[{{label:'LP变化',data:{_chart_json(lp_values)},backgroundColor:{_chart_json(lp_colors)},borderWidth:0}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'LP变化',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5',maxTicksLimit:20}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Session 规模
    sess = r.get("sessions", {})
    parts.append(f"""new Chart(document.getElementById('chart-session-size'),{{
  type:'bar',
  data:{{labels:{_chart_json(sess.get('size_labels',[]))},
    datasets:[{{label:'次数',data:{_chart_json(sess.get('size_counts',[]))},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'次数',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'每轮游戏局数',color:'#8b95a5'}}}}}}
  }}
}});""")

    # Session 首局开始时间
    parts.append(f"""new Chart(document.getElementById('chart-session-first-hour'),{{
  type:'bar',
  data:{{labels:{_chart_json(sess.get('first_hour_labels',[]))},
    datasets:[{{label:'次数',data:{_chart_json(sess.get('first_hour_counts',[]))},backgroundColor:'rgba(245,158,11,0.7)',borderColor:'#f59e0b',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'次数',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Session 末局结束时间
    parts.append(f"""new Chart(document.getElementById('chart-session-last-hour'),{{
  type:'bar',
  data:{{labels:{_chart_json(sess.get('last_hour_labels',[]))},
    datasets:[{{label:'次数',data:{_chart_json(sess.get('last_hour_counts',[]))},backgroundColor:'rgba(168,85,247,0.7)',borderColor:'#a855f7',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'次数',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 日历热力图（使用 bar chart 按日期着色）
    days_all = att.get("days", [])
    cal_labels = [d["date"] for d in days_all]
    cal_games = [d["games"] for d in days_all]
    cal_wr = [d["win_rate"] for d in days_all]
    cal_colors = ["rgba(46,204,113,0.8)" if wr >= 50 else "rgba(231,76,60,0.8)" for wr in cal_wr]
    parts.append(f"""new Chart(document.getElementById('chart-cal-heatmap'),{{
  type:'bar',
  data:{{labels:{_chart_json(cal_labels)},
    datasets:[{{label:'场次',data:{_chart_json(cal_games)},backgroundColor:{_chart_json(cal_colors)},borderWidth:0}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:3,
    plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(ctx){{var wr={_chart_json(cal_wr)};return ctx.raw+'场 — 胜率 '+wr[ctx.dataIndex]+'%';}}}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5',maxTicksLimit:25,maxRotation:45}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Session 内第N局胜率
    pos_labels_s = sess.get("pos_labels", [])
    pos_wr_s = sess.get("pos_wr", [])
    pos_g_s = sess.get("pos_games", [])
    pos_lbl_with_cnt = [f"{lbl} ({pos_g_s[i]}场)" if i < len(pos_g_s) else lbl for i, lbl in enumerate(pos_labels_s)]
    parts.append(f"""new Chart(document.getElementById('chart-session-pos'),{{
  type:'bar',
  data:{{labels:{_chart_json(pos_lbl_with_cnt)},
    datasets:[{{label:'胜率 %',data:{_chart_json(pos_wr_s)},backgroundColor:'rgba(20,184,166,0.7)',borderColor:'#14b8a6',borderWidth:1}}]
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
    a2w = tilt.get("after_2win") or {}
    tilt_labels = ["赢后", "输后"]
    tilt_data = [aw.get("wr", 0), al.get("wr", 0)]
    tilt_colors = ['rgba(46,204,113,0.7)', 'rgba(231,76,60,0.7)']
    tilt_borders = ['#2ecc71', '#e74c3c']
    if a2w:
        tilt_labels.append("连赢2局后")
        tilt_data.append(a2w.get("wr", 0))
        tilt_colors.append('rgba(46,204,113,0.9)')
        tilt_borders.append('#1ea853')
    if a2:
        tilt_labels.append("连输2局后")
        tilt_data.append(a2.get("wr", 0))
        tilt_colors.append('rgba(231,76,60,0.9)')
        tilt_borders.append('#c0392b')
    parts.append(f"""new Chart(document.getElementById('chart-tilt'),{{
  type:'bar',
  data:{{labels:{_chart_json(tilt_labels)},
    datasets:[{{label:'胜率 %',data:{_chart_json(tilt_data)},backgroundColor:{_chart_json(tilt_colors)},borderColor:{_chart_json(tilt_borders)},borderWidth:1}}]
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
    parts.append(f"""new Chart(document.getElementById('chart-streaks'),{{
  type:'bar',
  data:{{labels:{_chart_json([str(l)+'局' for l in all_len])},
    datasets:[
      {{label:'连胜',data:{_chart_json(w_fill)},backgroundColor:'rgba(46,204,113,0.7)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'连败',data:{_chart_json(l_fill)},backgroundColor:'rgba(231,76,60,0.7)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 稳定性
    consistency = r.get("consistency", {})
    kd = consistency.get("kda_distribution", [])
    parts.append(f"""new Chart(document.getElementById('chart-consistency'),{{
  type:'bar',
  data:{{labels:{_chart_json([d['label'] for d in kd])},
    datasets:[{{label:'场次',data:{_chart_json([d['count'] for d in kd])},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'场次',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'KDA',color:'#8b95a5'}}}}}}
  }}
}});""")

    # 投降分析（柱状图）
    surr = r.get("surrender", {})
    total_g = r.get("overview", {}).get("total_games", 0)
    enemy_ff = surr.get("enemy_ff", 0)
    our_ff = surr.get("our_ff", 0)
    fought_on = total_g - enemy_ff - our_ff
    parts.append(f"""new Chart(document.getElementById('chart-surrender'),{{
  type:'bar',
  data:{{labels:['对方投降(赢)','我方投降(输)','战斗到结束'],
    datasets:[{{label:'场次',data:[{enemy_ff},{our_ff},{fought_on}],backgroundColor:['rgba(46,204,113,0.7)','rgba(231,76,60,0.7)','rgba(74,158,255,0.7)'],borderColor:['#2ecc71','#e74c3c','#4a9eff'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'场次',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # AFK
    afk = r.get("afk_impact", {})
    parts.append(f"""new Chart(document.getElementById('chart-afk'),{{
  type:'bar',
  data:{{labels:['挂机场次','正常场次'],
    datasets:[{{label:'胜率 %',data:[{afk.get('afk_wr',0)},{afk.get('non_afk_wr',0)}],backgroundColor:['rgba(231,76,60,0.7)','rgba(46,204,113,0.7)'],borderColor:['#e74c3c','#2ecc71'],borderWidth:1}}]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,plugins:{{legend:{{display:false}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # GPM 散点图
    gold = r.get("gold_efficiency", {})
    mode_name = gold.get("mode_name", "")
    excluded = gold.get("excluded_short", 0)
    gpm_title = f"每分钟金币 vs 对局时长 — {mode_name}" if mode_name else "每分钟金币 vs 对局时长"
    parts.append(f"""new Chart(document.getElementById('chart-gpm'),{{
  type:'scatter',
  data:{{datasets:[
    {{label:'胜',data:{_chart_json(gold.get('scatter_win',[]))},backgroundColor:'rgba(46,204,113,0.5)',borderColor:'#2ecc71',pointRadius:3}},
    {{label:'负',data:{_chart_json(gold.get('scatter_loss',[]))},backgroundColor:'rgba(231,76,60,0.5)',borderColor:'#e74c3c',pointRadius:3}}
  ]}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'GPM (每分钟金币)',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'对局时长 (分钟)',color:'#8b95a5'}}}}}}
  }}
}});""")

    # 过度自信与救赎效应散点图
    boom = r.get("boomerang_effect", {})
    parts.append(f"""new Chart(document.getElementById('chart-boomerang'),{{
  type:'scatter',
  data:{{datasets:[
    {{label:'MVP后下一局',data:{_chart_json(boom.get('scatter_mvp',[]))},backgroundColor:'rgba(245,158,11,0.6)',borderColor:'#f59e0b',pointRadius:4}},
    {{label:'SVP/惨败后下一局',data:{_chart_json(boom.get('scatter_svp',[]))},backgroundColor:'rgba(231,76,60,0.6)',borderColor:'#e74c3c',pointRadius:4}},
    {{label:'普通对局后',data:{_chart_json(boom.get('scatter_normal',[]))},backgroundColor:'rgba(149,165,166,0.4)',borderColor:'#95a5a6',pointRadius:3}}
  ]}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'下一局评分',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'当前局评分',color:'#8b95a5'}}}}}}
  }}
}});""")

    # "再来一局"陷阱
    omg = r.get("one_more_game", {})
    # 在标签上附加样本量
    omg_sizes = omg.get('session_sizes', [])
    omg_counts = omg.get('bin_counts', [])
    omg_labels_with_n = [f"{lbl}\\n({omg_counts[i]}次)" if i < len(omg_counts) else lbl for i, lbl in enumerate(omg_sizes)]
    # 整体平均胜率参考线
    omg_avg = omg.get('overall_avg_wr', 0)
    omg_avg_line = [omg_avg] * len(omg_sizes) if omg_sizes else []
    parts.append(f"""new Chart(document.getElementById('chart-one-more'),{{
  type:'bar',
  data:{{labels:{_chart_json(omg_labels_with_n)},
    datasets:[
      {{label:'前N-1局胜率 %',data:{_chart_json(omg.get('prev_wrs',[]))},backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1}},
      {{label:'末局胜率 %',data:{_chart_json(omg.get('last_wrs',[]))},backgroundColor:'rgba(236,72,153,0.7)',borderColor:'#ec4899',borderWidth:1}},
      {{label:'整体平均胜率 ({omg_avg}%)',data:{_chart_json(omg_avg_line)},type:'line',borderColor:'#c8aa6e',borderWidth:2,borderDash:[6,4],pointRadius:0,fill:false,order:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{y:{{max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # Carry依赖度画像
    cp = r.get("carry_profile", {})
    parts.append(f"""new Chart(document.getElementById('chart-carry-profile'),{{
  type:'bar',
  data:{{labels:['胜局分类','败局分类'],
    datasets:[
      {{label:'硬Carry',data:[{cp.get('win_data',[0,0,0])[0] if cp.get('win_data') else 0},0],backgroundColor:'rgba(245,158,11,0.8)',borderColor:'#f59e0b',borderWidth:1}},
      {{label:'稳定参与',data:[{cp.get('win_data',[0,0,0])[1] if cp.get('win_data') else 0},0],backgroundColor:'rgba(74,158,255,0.7)',borderColor:'#4a9eff',borderWidth:1}},
      {{label:'躺赢',data:[{cp.get('win_data',[0,0,0])[2] if cp.get('win_data') else 0},0],backgroundColor:'rgba(149,165,166,0.7)',borderColor:'#95a5a6',borderWidth:1}},
      {{label:'尽力局(SVP)',data:[0,{cp.get('loss_data',[0,0,0])[0] if cp.get('loss_data') else 0}],backgroundColor:'rgba(168,85,247,0.7)',borderColor:'#a855f7',borderWidth:1}},
      {{label:'普通败局',data:[0,{cp.get('loss_data',[0,0,0])[1] if cp.get('loss_data') else 0}],backgroundColor:'rgba(46,204,113,0.5)',borderColor:'#2ecc71',borderWidth:1}},
      {{label:'崩盘局',data:[0,{cp.get('loss_data',[0,0,0])[2] if cp.get('loss_data') else 0}],backgroundColor:'rgba(231,76,60,0.7)',borderColor:'#e74c3c',borderWidth:1}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{x:{{stacked:true,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}},y:{{stacked:true,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 多杀含金量
    mk = r.get("multi_kill_impact", {})
    parts.append(f"""new Chart(document.getElementById('chart-multikill'),{{
  type:'bar',
  data:{{labels:{_chart_json(mk.get('labels',[]))},
    datasets:[
      {{label:'胜率 %',data:{_chart_json(mk.get('winrates',[]))},backgroundColor:'rgba(245,158,11,0.7)',borderColor:'#f59e0b',borderWidth:1,yAxisID:'y'}},
      {{label:'场次',data:{_chart_json(mk.get('counts',[]))},backgroundColor:'rgba(168,85,247,0.3)',borderColor:'#a855f7',borderWidth:1,yAxisID:'y1',type:'line',tension:0.3}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{labels:{{color:'#8b95a5'}}}}}},
    scales:{{
      y:{{type:'linear',position:'left',title:{{display:true,text:'胜率 %',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},max:100}},
      y1:{{type:'linear',position:'right',title:{{display:true,text:'场次',color:'#8b95a5'}},ticks:{{color:'#8b95a5'}},grid:{{display:false}}}},
      x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}
    }}
  }}
}});""")


    # 时间热力图（纯JS渲染 — 胜率，12列每列2小时）
    pt = r.get("prime_time_matrix", {})
    if pt.get("cells"):
        cells_json = _chart_json(pt.get("cells", []))
        game_cells_json = _chart_json(pt.get("game_cells", []))
        day_labels_json = _chart_json(pt.get("day_labels", []))
        hour_labels_json = _chart_json(pt.get("hour_labels", []))
        parts.append(f"""(function(){{
  var cells={cells_json};
  var gameCells={game_cells_json};
  var dayLabels={day_labels_json};
  var hourLabels={hour_labels_json};
  var numSlots=hourLabels.length;

  // 胜率热力图
  (function(){{
    if(!cells.length)return;
    var container=document.getElementById('heatmap-prime-time');
    var table=document.createElement('table');
    table.style.cssText='border-collapse:collapse;table-layout:fixed;width:100%;font-size:11px';
    var thead='<tr><th style="padding:4px 6px;color:#5a6575"></th>';
    for(var h=0;h<numSlots;h++) thead+='<th style="padding:4px;color:#5a6575;font-weight:400;text-align:center">'+hourLabels[h]+'</th>';
    thead+='</tr>';
    var rows='';
    for(var d=0;d<7;d++){{
      rows+='<tr><td style="padding:4px 6px;color:#8b95a5;font-weight:600;white-space:nowrap">'+dayLabels[d]+'</td>';
      for(var h=0;h<numSlots;h++){{
        var found=cells.find(function(c){{return c.day===d&&c.hour===h;}});
        if(found){{
          var wr=found.wr;
          // 颜色: 红(<45%) → 黄(45-55%) → 绿(>55%)
          var hue,sat,light;
          if(wr>=55){{hue=120;sat=22+Math.min(35,(wr-55)*0.7);light=50-Math.min(12,(wr-55)*0.24);}}
          else if(wr>=45){{hue=40;sat=22+Math.min(35,Math.abs(wr-50)*7);light=50-Math.abs(wr-50)*0.18;}}
          else{{hue=0;sat=22+Math.min(35,(45-wr)*0.7);light=50-Math.min(12,(45-wr)*0.24);}}
          var bg='hsl('+hue+','+sat+'%,'+light+'%)';
          var textColor=light>46?'#0a0e14':'#d4d8dd';
          rows+='<td style="padding:4px;text-align:center;background:'+bg+';color:'+textColor+';cursor:pointer" title="'+dayLabels[d]+' '+hourLabels[h]+' - 胜率 '+wr+'% ('+found.games+'场)">'+Math.round(wr)+'</td>';
        }}else{{
          rows+='<td style="padding:4px;text-align:center;color:#2a3a4a">·</td>';
        }}
      }}
      rows+='</tr>';
    }}
    table.innerHTML=thead+rows;
    container.appendChild(table);
  }})();

  // 对局数量热力图
  (function(){{
    if(!gameCells.length)return;
    var container=document.getElementById('heatmap-game-count');
    if(!container)return;
    var table=document.createElement('table');
    table.style.cssText='border-collapse:collapse;table-layout:fixed;width:100%;font-size:11px';
    var thead='<tr><th style="padding:4px 6px;color:#5a6575"></th>';
    for(var h=0;h<numSlots;h++) thead+='<th style="padding:4px;color:#5a6575;font-weight:400;text-align:center">'+hourLabels[h]+'</th>';
    thead+='</tr>';
    // 计算最大游戏数用于归一化颜色
    var maxGames=0;
    gameCells.forEach(function(c){{if(c.games>maxGames)maxGames=c.games;}});
    var rows='';
    for(var d=0;d<7;d++){{
      rows+='<tr><td style="padding:4px 6px;color:#8b95a5;font-weight:600;white-space:nowrap">'+dayLabels[d]+'</td>';
      for(var h=0;h<numSlots;h++){{
        var found=gameCells.find(function(c){{return c.day===d&&c.hour===h;}});
        if(found&&found.games>0){{
          var intensity=Math.min(1,found.games/maxGames*0.85+0.15);
          var bg='hsl(215,35%,'+(60-intensity*35)+'%)';
          var textColor=intensity>0.6?'#d4d8dd':'#8b95a5';
          rows+='<td style="padding:4px;text-align:center;background:'+bg+';color:'+textColor+';cursor:pointer" title="'+dayLabels[d]+' '+hourLabels[h]+' - '+found.games+'场">'+found.games+'</td>';
        }}else{{
          rows+='<td style="padding:4px;text-align:center;color:#2a3a4a">·</td>';
        }}
      }}
      rows+='</tr>';
    }}
    table.innerHTML=thead+rows;
    container.appendChild(table);
  }})();
}})();""")

    # 赛季段位演进
    stt = r.get("season_tier_timeline", {})
    if stt.get("labels"):
        tier_labels_map = _chart_json(_SEASON_TIER_LABELS)
        parts.append(f"""new Chart(document.getElementById('chart-season-tier-timeline'),{{
  type:'line',
  data:{{labels:{_chart_json(stt.get('labels',[]))},
    datasets:[
      {{label:'单双排段位',data:{_chart_json(stt.get('solo_tiers',[]))},borderColor:'#c8aa6e',backgroundColor:'rgba(200,170,110,0.08)',fill:true,stepped:true,pointRadius:5,pointBackgroundColor:'#c8aa6e',pointBorderColor:'#c8aa6e',borderWidth:2}},
      {{label:'组排段位',data:{_chart_json(stt.get('flex_tiers',[]))},borderColor:'#a855f7',backgroundColor:'rgba(168,85,247,0.05)',fill:true,stepped:true,pointRadius:5,pointBackgroundColor:'#a855f7',pointBorderColor:'#a855f7',borderWidth:2,borderDash:[6,3]}}
    ]
  }},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2.5,
    plugins:{{legend:{{labels:{{color:'#8b95a5',usePointStyle:true,padding:20}}}}}},
    scales:{{
      y:{{min:0,max:8,
        ticks:{{color:'#8b95a5',stepSize:1,
          callback:function(v){{var m={tier_labels_map};return m[v]||'';}}
        }},
        grid:{{color:'#2a3a4a'}},
        title:{{display:true,text:'段位',color:'#8b95a5'}}
      }},
      x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},
        title:{{display:true,text:'赛季',color:'#8b95a5'}}
      }}
    }}
  }}
}});""")

    # ── 生涯全景图表 ──────────────────────────────────────────────────────────
    sa = r.get("summoner_profile_analysis", {})
    md = sa.get("mode_distribution", {}) if sa.get("has_career") else {}
    modes = md.get("modes", [])
    if modes:
        # 全模式生涯分布（纵向柱状图，顺序与胜率对比一致）
        mode_labels = _chart_json([m["name"] for m in modes])
        mode_data = _chart_json([m["games"] for m in modes])
        mode_colors = _chart_json([
            "rgba(74,158,255,0.8)", "rgba(46,204,113,0.8)", "rgba(245,158,11,0.8)",
            "rgba(168,85,247,0.8)", "rgba(149,165,166,0.8)", "rgba(236,72,153,0.8)",
        ][:len(modes)])
        parts.append(f"""new Chart(document.getElementById('chart-career-mode-dist'),{{
  type:'bar',
  data:{{labels:{mode_labels},datasets:[{{label:'场次',data:{mode_data},backgroundColor:{mode_colors},borderWidth:0}}]}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{ticks:{{color:'#8b95a5',stepSize:1}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'场次',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

        # 各模式胜率对比（条形图）
        wr_labels = _chart_json([m["name"] for m in modes if m["win_rate"] is not None])
        wr_data = _chart_json([m["win_rate"] for m in modes if m["win_rate"] is not None])
        wr_colors = _chart_json(["rgba(46,204,113,0.7)" if v >= 50 else "rgba(231,76,60,0.7)" for v in [m["win_rate"] for m in modes if m["win_rate"] is not None]])
        parts.append(f"""new Chart(document.getElementById('chart-career-mode-wr'),{{
  type:'bar',
  data:{{labels:{wr_labels},datasets:[{{label:'胜率 %',data:{wr_data},backgroundColor:{wr_colors},borderWidth:0}}]}},
  options:{{responsive:true,maintainAspectRatio:true,aspectRatio:2,
    plugins:{{legend:{{display:false}}}},
    scales:{{y:{{min:0,max:100,ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}},title:{{display:true,text:'胜率 %',color:'#8b95a5'}}}},x:{{ticks:{{color:'#8b95a5'}},grid:{{color:'#2a3a4a'}}}}}}
  }}
}});""")

    # 将每个图表的 aspectRatio 同步到父容器 CSS，确保 canvas 填满时不拉伸
    parts.append("""document.querySelectorAll('.chart-wrap canvas').forEach(function(c){
  var ch=Chart.getChart(c);
  if(ch&&ch.options.aspectRatio){c.parentElement.style.aspectRatio=ch.options.aspectRatio;}
});""")
    return "\n".join(parts)

def _build_html(results: dict) -> str:
    ov = results.get("overview", {})
    champion_id = ov.get("most_played_champ", 0)
    hero_name = ov.get("most_played_champ_name", "")
    if not champion_id:
        pool = results.get("champion_pool", {})
        pool_freq = pool.get("freq", [])
        if pool_freq:
            top = pool_freq[0]
            champion_id = top.get("champion_id", 0) or 0
            hero_name = top.get("name", "")
    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css = _build_css()
    nav = _build_nav()
    hero = _build_hero(results)
    sections = "".join([
        _build_section_winrate(results),
        _build_section_game_rhythm(results),
        _build_section_psychology(results),
        _build_section_player_level(results),
        _build_section_attendance(results),
    ])
    charts_js = _build_all_charts(results)
    footer = _build_footer(ov.get("total_games", 0), export_time)
    initial_skin_url = f"https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/{champion_id}-001.jpg" if champion_id else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOL 对局历史数据分析报告</title>
<style>{css}</style>
</head>
<body style="--bg-image: url('{initial_skin_url}');">
{nav}
<main>
{hero}
{sections}
</main>
{footer}
<script>
(function(){{
  var CDNS=[
    'https://cdn.bootcdn.net/ajax/libs/Chart.js/4.4.1/chart.umd.min.js',
    'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
    'https://unpkg.com/chart.js@4.4.7/dist/chart.umd.min.js',
  ];
  function tryCDN(i){{
    if(i>=CDNS.length){{document.querySelectorAll('.chart-card .chart-wrap').forEach(function(el){{el.innerHTML='<p style=color:#e74c3c;text-align:center;padding:20px>⚠ Chart.js 加载失败，请检查网络连接</p>';}});return;}}
    var s=document.createElement('script');
    s.src=CDNS[i];
    s.onerror=function(){{s.remove();tryCDN(i+1);}};
    s.onload=function(){{initCharts();}};
    document.head.appendChild(s);
  }}
  function initCharts(){{
    Chart.defaults.font.size=12;
    Chart.defaults.font.family='"Microsoft YaHei","PingFang SC",sans-serif';
{charts_js}
  }}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',function(){{tryCDN(0);}});
  else tryCDN(0);
  // 招牌英雄皮肤背景管理
  var _skinCid={champion_id};
  var _skinPool=[];
  var _skinReady=false;
  var _curSid='001';
  var _heroName='{hero_name}';
  function _setBg(sid){{
    _curSid=sid;
    document.body.style.setProperty('--bg-image','url(https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/'+_skinCid+'-'+sid+'.jpg)');
  }}
  function _updateTooltip(){{
    if(_skinBtn)_skinBtn.title='你的招牌英雄'+_heroName+'有'+_skinPool.length+'个皮肤';
  }}
  var _skinBtn=document.getElementById('skinSwitchBtn');
  if(_skinBtn){{
    _skinBtn.addEventListener('click',function(){{
      if(!_skinReady){{alert('皮肤资源检测中，请稍等…');return;}}
      if(_skinPool.length<=1)return;
      var idx=_skinPool.indexOf(_curSid);
      idx=(idx+1)%_skinPool.length;
      _setBg(_skinPool[idx]);
    }});
  }}
  function _detectSkins(){{
    if(!_skinCid)return;
    var total=21,done=0;
    function ck(sid,ok){{
      if(ok)_skinPool.push(sid);
      done++;
      if(done>=total){{
        _skinReady=true;
        if(_skinBtn){{
          _skinBtn.classList.remove('loading');
          _updateTooltip();
        }}
        if(_skinPool.indexOf('001')===-1&&_skinPool.indexOf('000')!==-1)_setBg('000');
        else if(_skinPool.length===0)document.body.style.setProperty('--bg-image','none');
      }}
    }}
    for(var i=0;i<=20;i++){{
      (function(sid){{
        var img=new Image();
        img.onload=function(){{ck(sid,true);}};
        img.onerror=function(){{ck(sid,false);}};
        img.src='https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/'+_skinCid+'-'+sid+'.jpg';
      }})(('00'+i).slice(-3));
    }}
  }}
  if(document.readyState==='complete')_detectSkins();
  else window.addEventListener('load',_detectSkins);
}})();
</script>
</body>
</html>"""

def _build_html_multi(area_data: dict[int, dict], combined_first: bool = False) -> str:
    """生成多区报告 HTML：使用 per-area chart init 函数 + JS 切换器。

    当 combined_first=True 时，area_data 的第一个 key 应为 0（全区数据分析），
    将被设为首个选项和默认选中。"""
    from ._data import get_game_area_name

    area_ids = list(area_data.keys())
    first_id = area_ids[0]
    first = area_data[first_id]

    export_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    css = _build_css() + """
nav .area-switch-nav { display:inline-flex; align-items:center; gap:4px; margin-right:16px; }
nav .area-switch-nav label { color:#8b95a5; font-size:12px; cursor:default; }
nav .area-switch-nav select {
  background:rgba(26,34,48,0.8); color:#c8aa6e; border:1px solid #2a3a4a;
  border-radius:4px; padding:3px 6px; font-size:13px; cursor:pointer;
  font-family:inherit;
}
nav .area-switch-nav select:hover { border-color:#c8aa6e; }
nav .area-switch-nav select:focus { outline:none; border-color:#c8aa6e; }
"""

    ov = first["results"].get("overview", {})
    champion_id = ov.get("most_played_champ", 0)
    hero_name = ov.get("most_played_champ_name", "")
    if not champion_id:
        pool = first["results"].get("champion_pool", {})
        pool_freq = pool.get("freq", [])
        if pool_freq:
            top = pool_freq[0]
            champion_id = top.get("champion_id", 0) or 0
            hero_name = top.get("name", "")
    # 构建大区切换器（嵌入导航栏）
    area_switcher_html = '<span class="area-switch-nav"><label>🎯</label><select id="areaSwitcher" onchange="switchArea(this.value)">' + \
        "".join(f'<option value="{aid}">{area_data[aid]["name"]}</option>' for aid in area_ids) + \
        '</select></span>'
    nav = _build_nav(area_switcher_html)
    footer = _build_footer(0, export_time)
    initial_skin_url = f"https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/{champion_id}-001.jpg" if champion_id else ""

    # 为每个大区生成独立的图表初始化代码 + HTML 内容块
    area_chart_blocks: dict[int, str] = {}
    area_html_blocks: dict[int, str] = {}
    for aid in area_ids:
        results = area_data[aid]["results"]
        area_chart_blocks[aid] = _build_all_charts(results)
        area_html_blocks[aid] = "".join([
            _build_hero(results),
            _build_section_winrate(results),
            _build_section_game_rhythm(results),
            _build_section_psychology(results),
            _build_section_player_level(results),
            _build_section_attendance(results),
        ])

    import json
    area_html_json = json.dumps(area_html_blocks, ensure_ascii=True)

    # 为每个大区计算招牌英雄 ID 和名称（用于背景皮肤切换）
    area_skin_cid: dict[int, int] = {}
    area_hero_name: dict[int, str] = {}
    for aid, ad in area_data.items():
        a_ov = ad["results"].get("overview", {})
        cid = a_ov.get("most_played_champ", 0)
        hname = a_ov.get("most_played_champ_name", "")
        if not cid:
            a_pool = ad["results"].get("champion_pool", {})
            a_freq = a_pool.get("freq", [])
            if a_freq:
                cid = a_freq[0].get("champion_id", 0) or 0
                hname = a_freq[0].get("name", "")
        area_skin_cid[aid] = cid
        area_hero_name[aid] = hname
    area_skin_cid_json = json.dumps(area_skin_cid, separators=(',', ':'))
    area_hero_name_json = json.dumps(area_hero_name, ensure_ascii=True)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LOL 对局历史数据分析报告（多区）</title>
<style>{css}</style>
</head>
<body style="--bg-image: url('{initial_skin_url}');">
{nav}
<main>
<div id="area-panel-content">
{area_html_blocks[first_id]}
</div>
</main>
{footer}
<script>
/* per-area HTML content blocks */
var _AREA_HTML = {area_html_json};

/* per-area champion data for skin background */
var _AREA_SKIN_CID = {area_skin_cid_json};
var _AREA_HERO_NAME = {area_hero_name_json};

/* per-area chart init functions */
function _initChartsArea_{first_id}() {{
  Chart.defaults.font.size = 12;
  Chart.defaults.font.family = '"Microsoft YaHei","PingFang SC",sans-serif';
  {area_chart_blocks[first_id]}
}}
{''.join(
    f'function _initChartsArea_{aid}() {{\n  Chart.defaults.font.size = 12;\n  Chart.defaults.font.family = \'"Microsoft YaHei","PingFang SC",sans-serif\';\n  {area_chart_blocks[aid]}\n}}'
    for aid in area_ids if aid != first_id
)}

var AREA_CHARTS = {{}};
var _chartId = 0;
var _curArea = {first_id};

function _saveChart(chart) {{ var id = _chartId++; AREA_CHARTS[id] = chart; return chart; }}

function _destroyAllCharts() {{
  Object.values(AREA_CHARTS).forEach(function(c) {{ try {{ c.destroy(); }} catch(e) {{ }} }});
  AREA_CHARTS = {{}}; _chartId = 0;
}}

function switchArea(aid) {{
  _curArea = parseInt(aid);
  _destroyAllCharts();
  document.getElementById('areaSwitcher').value = aid;
  document.getElementById('area-panel-content').innerHTML = _AREA_HTML[aid] || '';
  window['_initChartsArea_' + aid]();
  _initSkinForArea(aid);
}}

var CDNS = [
  'https://cdn.bootcdn.net/ajax/libs/Chart.js/4.4.1/chart.umd.min.js',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
  'https://unpkg.com/chart.js@4.4.7/dist/chart.umd.min.js',
];
function tryCDN(i) {{
  if (i >= CDNS.length) {{
    document.querySelectorAll('.chart-card .chart-wrap').forEach(function(el) {{
      el.innerHTML = '<p style=color:#e74c3c;text-align:center;padding:20px>⚠ Chart.js 加载失败</p>';
    }});
    return;
  }}
  var s = document.createElement('script');
  s.src = CDNS[i];
  s.onerror = function() {{ s.remove(); tryCDN(i + 1); }};
  s.onload = function() {{ _initChartsArea_{first_id}(); }};
  document.head.appendChild(s);
}}
if (document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', function() {{ tryCDN(0); }});
else tryCDN(0);

/* skin state (updated per area via _initSkinForArea) */
var _skinCid = _AREA_SKIN_CID[{first_id}];
var _skinPool = [];
var _skinReady = false;
var _curSid = '001';
var _heroName = _AREA_HERO_NAME[{first_id}];

function _setBg(sid) {{
  _curSid = sid;
  document.body.style.setProperty('--bg-image', 'url(https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/' + _skinCid + '-' + sid + '.jpg)');
}}
function _updateTooltip() {{
  var btn = document.getElementById('skinSwitchBtn');
  if (btn) btn.title = '招牌英雄' + _heroName + '有' + _skinPool.length + '个皮肤';
}}
function _detectSkins() {{
  if (!_skinCid) {{
    var btn = document.getElementById('skinSwitchBtn');
    if (btn) btn.style.display = 'none';
    return;
  }}
  var total = 21, done = 0;
  function ck(sid, ok) {{ if (ok) _skinPool.push(sid); done++; if (done >= total) {{ _skinReady = true; var btn = document.getElementById('skinSwitchBtn'); if (btn) {{ btn.classList.remove('loading'); _updateTooltip(); }} if (_skinPool.indexOf('001') === -1 && _skinPool.indexOf('000') !== -1) _setBg('000'); else if (_skinPool.length === 0) document.body.style.setProperty('--bg-image', 'none'); }} }}
  for (var i = 0; i <= 20; i++) {{ (function(sid) {{ var img = new Image(); img.onload = function() {{ ck(sid, true); }}; img.onerror = function() {{ ck(sid, false); }}; img.src = 'https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/' + _skinCid + '-' + sid + '.jpg'; }})(('00' + i).slice(-3)); }}
}}
function _initSkinForArea(aid) {{
  _skinCid = _AREA_SKIN_CID[aid] || 0;
  _heroName = _AREA_HERO_NAME[aid] || '';
  _skinPool = [];
  _skinReady = false;
  _curSid = '001';
  if (_skinCid) {{
    document.body.style.setProperty('--bg-image',
      'url(https://wegame.gtimg.com/g.26-r.c2d3c/helper/lol/assis/images/resources/skins/original/' + _skinCid + '-001.jpg)');
  }} else {{
    document.body.style.setProperty('--bg-image', 'none');
  }}
  var btn = document.getElementById('skinSwitchBtn');
  if (btn) {{
    btn.classList.add('loading');
    btn.title = '皮肤检测中…';
    btn.onclick = function() {{
      if (!_skinReady) {{ alert('皮肤资源检测中…'); return; }}
      if (_skinPool.length <= 1) return;
      var idx = _skinPool.indexOf(_curSid);
      idx = (idx + 1) % _skinPool.length;
      _setBg(_skinPool[idx]);
    }};
  }}
  _detectSkins();
}}
_initSkinForArea({first_id});
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

def _compute_all_results(
    matches: list[dict],
    champion_mastery: list[dict],
    season_history: list[dict],
    summoner_profile: dict | None,
    career_overview: dict | None,
    overview: dict,
    session_gap_hours: float = 2.0,
) -> dict:
    """调用所有分析函数并合并结果。"""
    return {
        "overview": overview,
        "win_rate_by_day": _analyze_win_rate_by_day_of_week(matches),
        "win_rate_by_hour": _analyze_win_rate_by_hour(matches),
        "win_rate_by_side": _analyze_win_rate_by_team_side(matches),
        "win_rate_by_position": _analyze_win_rate_by_position(matches),
        "win_rate_by_lp": _analyze_win_rate_by_lp_range(matches),
        "win_rate_by_duration": _analyze_win_rate_by_duration(matches),
        "mystery_factor": _analyze_mystery_factor(matches),
        "honors_impact": _analyze_honors_impact(matches),
        "champion_radar": _analyze_champion_radar(matches),
        "champion_pool": _analyze_champion_pool(matches, champion_mastery),
        "rank_progression": _analyze_rank_progression(matches),
        "attendance": _analyze_attendance(matches),
        "sessions": _analyze_sessions(matches, session_gap_hours),
        "tilt": _analyze_tilt(matches),
        "streaks": _analyze_streaks(matches),
        "consistency": _analyze_consistency(matches),
        "surrender": _analyze_surrender(matches),
        "afk_impact": _analyze_afk_impact(matches),
        "gold_efficiency": _analyze_gold_efficiency(matches),
        "boomerang_effect": _analyze_boomerang_effect(matches),
        "one_more_game": _analyze_one_more_game(matches),
        "carry_profile": _analyze_carry_profile(matches),
        "multi_kill_impact": _analyze_multi_kill_impact(matches),
        "prime_time_matrix": _analyze_prime_time_matrix(matches),
        "season_tier_timeline": _analyze_season_tier_timeline(season_history),
        "season_stats": _analyze_season_stats(season_history),
        "summoner_profile_analysis": _analyze_summoner_profile(
            summoner_profile, career_overview, overview,
        ),
    }


def generate_report(
    db_path: str = "wegame_matches.db",
    output_path: str = "report.html",
    session_gap_hours: float = 2.0,
    area_ids: list[int] | None = None,
) -> str:
    db_abs = str(Path(db_path).resolve())
    if not Path(db_path).exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_abs}")

    # 输出文件名添加日期后缀
    out_path = Path(output_path)
    date_suffix = datetime.now().strftime("%Y-%m-%d")
    stem = out_path.stem
    ext = out_path.suffix
    dated_output = out_path.with_name(f"{stem}_{date_suffix}{ext}")

    from ._data import get_game_area_name

    # 单区模式 — 加载该区数据，生成普通报告
    if area_ids and len(area_ids) == 1:
        aid = area_ids[0]
        area_name = get_game_area_name(aid)
        matches = _load_matches(db_path, area_ids=[aid])
        champion_mastery = _load_champion_mastery(db_path, area_ids=[aid])
        season_history = _load_season_history(db_path, area_ids=[aid])
        summoner_profile = _load_summoner_profile(db_path, area_ids=[aid])
        career_overview = _load_career_overview(db_path, area_ids=[aid])
        if not any([matches, champion_mastery, season_history, summoner_profile, career_overview]):
            html = _build_empty_report(db_abs)
            dated_output.write_text(html, encoding="utf-8")
            return str(dated_output.resolve())
        overview = _analyze_overview(matches, summoner_profile)
        results = _compute_all_results(matches, champion_mastery, season_history,
                                       summoner_profile, career_overview, overview,
                                       session_gap_hours)
        html = _build_html(results)
        dated_output.write_text(html, encoding="utf-8")
        return str(dated_output.resolve())

    # 多区模式
    if area_ids and len(area_ids) > 1:
        area_data: dict[int, dict] = {}
        for aid in area_ids:
            area_name = get_game_area_name(aid)
            print(f"  分析大区: {area_name}")
            a_matches = _load_matches(db_path, area_ids=[aid])
            a_cm = _load_champion_mastery(db_path, area_ids=[aid])
            a_sh = _load_season_history(db_path, area_ids=[aid])
            a_sp = _load_summoner_profile(db_path, area_ids=[aid])
            a_co = _load_career_overview(db_path, area_ids=[aid])
            if not any([a_matches, a_cm, a_sh, a_sp, a_co]):
                print(f"    (该大区完全无数据，跳过)")
                continue
            a_ov = _analyze_overview(a_matches, a_sp)
            a_results = _compute_all_results(a_matches, a_cm, a_sh, a_sp, a_co,
                                            a_ov, session_gap_hours)
            area_data[aid] = {"name": area_name, "results": a_results}

        if not area_data:
            html = _build_empty_report(db_abs)
            dated_output.write_text(html, encoding="utf-8")
            return str(dated_output.resolve())

        # ── 全区数据分析（仅当>=2个大区有数据时） ──
        if len(area_data) > 1:
            print(f"  计算全区数据分析（合并 {len(area_data)} 个大区）...")
            combined_matches = _load_matches(db_path, area_ids=area_ids)
            combined_cm_raw = _load_champion_mastery(db_path, area_ids=area_ids)
            combined_sh_raw = _load_season_history(db_path, area_ids=area_ids)
            combined_profiles = _load_summoner_profiles_all(db_path, area_ids=area_ids)
            combined_overviews = _load_career_overviews_all(db_path, area_ids=area_ids)

            combined_cm = _merge_champion_mastery(combined_cm_raw)
            combined_sh = _merge_season_history(combined_sh_raw)
            combined_sp = _merge_summoner_profiles(combined_profiles)
            combined_co = _merge_career_overviews(combined_overviews)

            combined_ov = _analyze_overview(combined_matches, combined_sp)
            combined_results = _compute_all_results(
                combined_matches, combined_cm, combined_sh,
                combined_sp, combined_co, combined_ov, session_gap_hours,
            )

            # 用 OrderedDict 确保全区排第一
            area_data_all = {0: {"name": "全区生涯数据", "results": combined_results}}
            area_data_all.update(area_data)
            area_data = area_data_all

        # 文件名取第一个区名，多于1个区加"等N区"（排除全区 key=0）
        real_area_data = {k: v for k, v in area_data.items() if k != 0} if 0 in area_data else area_data
        area_names = [d["name"].split("（")[0] for d in real_area_data.values()]
        first_name = area_names[0]
        if len(area_names) > 1:
            short_names = f"{first_name}等{len(area_names)}区"
        else:
            short_names = first_name
        dated_output = out_path.with_name(f"{stem}_{short_names}_{date_suffix}{ext}")

        combined_first = 0 in area_data
        html = _build_html_multi(area_data, combined_first=combined_first)
        dated_output.write_text(html, encoding="utf-8")
        return str(dated_output.resolve())

    # 无 area_ids（全部数据）
    matches = _load_matches(db_path)
    champion_mastery = _load_champion_mastery(db_path)
    season_history = _load_season_history(db_path)
    summoner_profile = _load_summoner_profile(db_path)
    career_overview = _load_career_overview(db_path)
    if not matches:
        html = _build_empty_report(db_abs)
        dated_output.write_text(html, encoding="utf-8")
        return str(dated_output.resolve())

    overview = _analyze_overview(matches, summoner_profile)
    results = _compute_all_results(matches, champion_mastery, season_history,
                                   summoner_profile, career_overview, overview,
                                   session_gap_hours)
    html = _build_html(results)
    dated_output.write_text(html, encoding="utf-8")
    return str(dated_output.resolve())
