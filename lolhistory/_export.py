"""导出模块：CSV（UTF-8 BOM）和 SQLite（match_summary + match_detail 两张表）。"""

import csv
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── CSV 字段定义（中文列头） ──────────────────────────────────────────────

CSV_FIELDNAMES = [
    "对局ID", "日期", "时间", "游戏时长(分钟)", "游戏时长(秒)",
    "队列类型", "队列ID", "地图", "地图ID",
    "英雄ID", "位置", "队伍ID", "胜利", "胜负",
    "击杀", "死亡", "助攻", "KDA", "评分", "金币",
    "双杀", "三杀", "四杀", "五杀",
    "MVP", "SVP", "投降", "挂机",
    "击杀最多", "助攻最多", "金币最多",
    "伤害最高", "承受伤害最高", "推塔最多",
    "段位", "胜点", "段位等级",
    "对局类型", "组队人数", "游戏版本",
]


def export_csv(parsed_battles: list[dict], filepath: str) -> str:
    """将解析后的对局摘要导出为 CSV（UTF-8 BOM 编码，兼容 Excel）。

    如果目标文件已存在，则按 ``对局ID`` 去重后追加新对局——
    重新运行工具时只会插入之前未导出过的对局。

    Args:
        parsed_battles: 解析后的对局摘要字典列表（来自 parse_battle_summary）。
        filepath: 输出 .csv 路径。

    Returns:
        创建/更新后的 CSV 文件的绝对路径。
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    # ── 读取已有数据（如果有） ──────────────────────────────────────────
    existing_rows: list[dict] = []
    existing_ids: set[str] = set()
    try:
        with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gid = row.get("对局ID", "")
                if gid:
                    existing_ids.add(gid)
                    existing_rows.append(row)
        logger.info("CSV 已有: %d 行", len(existing_rows))
    except FileNotFoundError:
        logger.info("CSV 新文件: %s", filepath)
    except Exception:
        logger.warning("CSV 读取失败，将覆盖: %s", filepath, exc_info=True)

    # ── 过滤仅保留新对局 ────────────────────────────────────────────────
    new_battles = [b for b in parsed_battles
                   if str(b.get("对局ID", "")) not in existing_ids]
    logger.info("CSV 新增: %d / 本次获取: %d", len(new_battles), len(parsed_battles))

    # ── 合并并排序 ──────────────────────────────────────────────────────
    all_rows = existing_rows + new_battles
    all_rows.sort(
        key=lambda x: float(x.get("game_start_time", 0)) if x.get("game_start_time") else 0,
        reverse=True,
    )

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info("CSV 已导出: %d 行（%d 已有 + %d 新增） → %s",
                len(all_rows), len(existing_rows), len(new_battles), filepath)
    return str(Path(filepath).absolute())


# ── SQLite 导出 ────────────────────────────────────────────────────────────

SQL_CREATE_MATCH_SUMMARY = """
CREATE TABLE IF NOT EXISTS match_summary (
    game_id         TEXT PRIMARY KEY,
    game_start_time TEXT,
    game_time_played INT,
    game_queue_id   INT,
    queue_name      TEXT,
    map_id          INT,
    map_name        TEXT,
    champion_id     INT,
    position        TEXT,
    team_id         INT,
    win             INT,
    kills           INT,
    deaths          INT,
    assists         INT,
    kda             REAL,
    game_score      INT,
    gold_earned     INT,
    double_kills    INT,
    triple_kills    INT,
    quadra_kills    INT,
    penta_kills     INT,
    was_mvp         INT,
    was_svp         INT,
    was_surrender   INT,
    was_afk         INT,
    most_kills      INT,
    most_assists    INT,
    most_gold       INT,
    most_damage     INT,
    most_taken      INT,
    most_turrets    INT,
    tier            TEXT,
    league_points   INT,
    rank            TEXT,
    game_version    TEXT
)
"""

SQL_CREATE_MATCH_DETAIL = """
CREATE TABLE IF NOT EXISTS match_detail (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT NOT NULL,
    summoner_name   TEXT,
    champion_id     INT,
    team_id         INT,
    win             INT,
    kills           INT,
    deaths          INT,
    assists         INT,
    kda             REAL,
    item0           INT,  item1 INT,  item2 INT,
    item3           INT,  item4 INT,  item5 INT,  item6 INT,
    spell1_id       INT,
    spell2_id       INT,
    perk0           INT,  perk1 INT,  perk2 INT,
    perk3           INT,  perk4 INT,  perk5 INT,
    total_damage    INT,
    total_taken     INT,
    gold_earned     INT,
    minions_killed  INT,
    vision_score    INT,
    cc_score        INT,
    is_self         INT,
    FOREIGN KEY (game_id) REFERENCES match_summary(game_id)
)
"""

SQL_CREATE_SUMMONER_PROFILE = """
CREATE TABLE IF NOT EXISTS summoner_profile (
    puin                 TEXT PRIMARY KEY,
    -- 召唤师基本信息 (GetSummonerInfo)
    summoner_id          INTEGER,
    summoner_name        TEXT,
    name_tag             TEXT,
    level                INTEGER,
    experience           INTEGER,
    icon_id              INTEGER,
    praise               INTEGER,
    discredit            INTEGER,
    top_of_canyon        INTEGER,
    openid               TEXT,
    area                 INTEGER,
    -- 赛季数据 (GetSummonerInfo.summoner.season)
    season_sid           INTEGER,
    season_total         INTEGER,
    season_wins          INTEGER,
    season_losses        INTEGER,
    season_tier          INTEGER,
    season_win_point     INTEGER,
    season_queue         INTEGER,
    -- 近30天数据 (GetPlayerRecentStat.recent_state)
    kill_30days          INTEGER,
    death_30days         INTEGER,
    assist_30days        INTEGER,
    recent_win_times     INTEGER,
    recent_play_times    INTEGER,
    last_game_id         TEXT,
    recent_kda_score     INTEGER,
    last_game_time       TEXT,
    common_champions     TEXT,
    common_positions     TEXT,
    -- 生涯总计 (GetPlayerRecentStat.game_career)
    total_mvp_times      INTEGER,
    total_svp_times      INTEGER,
    total_god_likes      INTEGER,
    total_penta_kills    INTEGER,
    total_quadra_kills   INTEGER,
    total_triple_kills   INTEGER,
    max_consecutive_wins INTEGER,
    highest_game_score   INTEGER,
    most_kills_num       INTEGER,
    most_assists_num     INTEGER,
    most_spree_kills_num INTEGER,
    most_damage_num      INTEGER,
    most_damage_taken_num INTEGER,
    most_gold_earned_num INTEGER,
    most_minions_kill_num INTEGER,
    most_turrets_kill_num INTEGER,
    total_kills          INTEGER,
    total_assists        INTEGER,
    total_ward_placed    INTEGER,
    longest_game_num     INTEGER,
    shortest_game_num    INTEGER,
    -- 元数据
    last_fetch_time      TEXT
)
"""

SQL_CREATE_SUMMONER_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS summoner_snapshot (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    puin             TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    level            INTEGER,
    season_tier      INTEGER,
    season_win_point INTEGER,
    season_total     INTEGER,
    season_wins      INTEGER,
    season_losses    INTEGER,
    praise           INTEGER,
    discredit        INTEGER,
    total_kills      INTEGER,
    total_assists    INTEGER,
    total_mvp_times  INTEGER,
    total_svp_times  INTEGER,
    recent_win_times INTEGER,
    recent_play_times INTEGER
)
"""

SQL_INDEX_SNAPSHOT = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_puin_time
ON summoner_snapshot(puin, fetched_at)
"""

# ── 新增表: 英雄熟练度 & 赛季报告 ──────────────────────────────────────────

SQL_CREATE_CHAMPION_MASTERY = """
CREATE TABLE IF NOT EXISTS champion_mastery (
    puin            TEXT NOT NULL,
    champion_id     INTEGER NOT NULL,
    total_games     INTEGER,
    wins            INTEGER,
    win_rate        REAL,
    mastery_exp     INTEGER,
    expire_day      INTEGER,
    instance_id     TEXT,
    sid_total       INTEGER,
    sid_wins        INTEGER,
    sid_exp         INTEGER,
    lanes_json      TEXT,
    last_fetch_time TEXT,
    PRIMARY KEY (puin, champion_id)
)
"""

SQL_CREATE_CHAMPION_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS champion_mastery_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    puin            TEXT NOT NULL,
    champion_id     INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    total_games     INTEGER,
    wins            INTEGER,
    sid_total       INTEGER,
    sid_wins        INTEGER
)
"""

SQL_INDEX_CHAMPION_SNAPSHOT = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_champion_snapshot
ON champion_mastery_snapshot(puin, champion_id, fetched_at)
"""

SQL_CREATE_SEASON_HISTORY = """
CREATE TABLE IF NOT EXISTS season_history (
    puin            TEXT NOT NULL,
    sid             INTEGER NOT NULL,
    total_games     INTEGER,
    wins            INTEGER,
    losses          INTEGER,
    tier            INTEGER,
    win_point       INTEGER,
    queue           INTEGER,
    team_total      INTEGER,
    team_wins       INTEGER,
    team_losses     INTEGER,
    team_tier       INTEGER,
    team_win_point  INTEGER,
    team_queue      INTEGER,
    last_fetch_time TEXT,
    PRIMARY KEY (puin, sid)
)
"""

SQL_CREATE_CAREER_OVERVIEW = """
CREATE TABLE IF NOT EXISTS career_overview (
    puin                TEXT PRIMARY KEY,
    total_match_games   INTEGER,
    total_match_wins    INTEGER,
    total_match_losses  INTEGER,
    total_aram_games    INTEGER,
    total_aram_wins     INTEGER,
    total_aram_losses   INTEGER,
    total_rank_games    INTEGER,
    total_rank_wins     INTEGER,
    total_rank_losses   INTEGER,
    total_teamrank_games   INTEGER,
    total_teamrank_wins    INTEGER,
    total_teamrank_losses  INTEGER,
    total_all_games     INTEGER,
    total_all_wins      INTEGER,
    total_all_losses    INTEGER,
    total_ai_games      INTEGER,
    total_ai_wins       INTEGER,
    total_clash_games   INTEGER,
    last_fetch_time     TEXT
)
"""

SUMMARY_COLUMNS = [
    "game_id", "game_start_time", "game_time_played", "game_queue_id",
    "queue_name", "map_id", "map_name", "champion_id", "position", "team_id",
    "win", "kills", "deaths", "assists", "kda", "game_score", "gold_earned",
    "double_kills", "triple_kills", "quadra_kills", "penta_kills",
    "was_mvp", "was_svp", "was_surrender", "was_afk",
    "most_kills", "most_assists", "most_gold", "most_damage",
    "most_taken", "most_turrets",
    "tier", "league_points", "rank", "game_version",
]

DETAIL_COLUMNS = [
    "game_id", "summoner_name", "champion_id", "team_id", "win",
    "kills", "deaths", "assists", "kda",
    "item0", "item1", "item2", "item3", "item4", "item5", "item6",
    "spell1_id", "spell2_id",
    "perk0", "perk1", "perk2", "perk3", "perk4", "perk5",
    "total_damage", "total_taken", "gold_earned",
    "minions_killed", "vision_score", "cc_score", "is_self",
]

SUMMONER_PROFILE_COLUMNS = [
    "puin", "summoner_id", "summoner_name", "name_tag", "level",
    "experience", "icon_id", "praise", "discredit", "top_of_canyon",
    "openid", "area",
    "season_sid", "season_total", "season_wins", "season_losses",
    "season_tier", "season_win_point", "season_queue",
    "kill_30days", "death_30days", "assist_30days",
    "recent_win_times", "recent_play_times", "last_game_id",
    "recent_kda_score", "last_game_time",
    "common_champions", "common_positions",
    "total_mvp_times", "total_svp_times", "total_god_likes",
    "total_penta_kills", "total_quadra_kills", "total_triple_kills",
    "max_consecutive_wins", "highest_game_score",
    "most_kills_num", "most_assists_num", "most_spree_kills_num",
    "most_damage_num", "most_damage_taken_num",
    "most_gold_earned_num", "most_minions_kill_num", "most_turrets_kill_num",
    "total_kills", "total_assists", "total_ward_placed",
    "longest_game_num", "shortest_game_num", "last_fetch_time",
]

SUMMONER_SNAPSHOT_COLUMNS = [
    "puin", "fetched_at", "level", "season_tier", "season_win_point",
    "season_total", "season_wins", "season_losses", "praise", "discredit",
    "total_kills", "total_assists", "total_mvp_times", "total_svp_times",
    "recent_win_times", "recent_play_times",
]

CHAMPION_MASTERY_COLUMNS = [
    "puin", "champion_id", "total_games", "wins", "win_rate",
    "mastery_exp", "expire_day", "instance_id",
    "sid_total", "sid_wins", "sid_exp",
    "lanes_json", "last_fetch_time",
]

CHAMPION_SNAPSHOT_COLUMNS = [
    "puin", "champion_id", "fetched_at",
    "total_games", "wins", "sid_total", "sid_wins",
]

SEASON_HISTORY_COLUMNS = [
    "puin", "sid", "total_games", "wins", "losses",
    "tier", "win_point", "queue",
    "team_total", "team_wins", "team_losses",
    "team_tier", "team_win_point", "team_queue",
    "last_fetch_time",
]

CAREER_OVERVIEW_COLUMNS = [
    "puin", "total_match_games", "total_match_wins", "total_match_losses",
    "total_aram_games", "total_aram_wins", "total_aram_losses",
    "total_rank_games", "total_rank_wins", "total_rank_losses",
    "total_teamrank_games", "total_teamrank_wins", "total_teamrank_losses",
    "total_all_games", "total_all_wins", "total_all_losses",
    "total_ai_games", "total_ai_wins", "total_clash_games",
    "last_fetch_time",
]


def _map_summary_to_row(s: dict) -> dict:
    """将解析后的对局摘要字典映射为 SQLite 行数据。"""
    return {
        "game_id": str(s.get("对局ID", s.get("game_id", ""))),
        "game_start_time": _ts_to_iso(s.get("game_start_time")),
        "game_time_played": s.get("游戏时长(秒)", s.get("game_time_played", 0)) or 0,
        "game_queue_id": s.get("队列ID", s.get("game_queue_id", 0)) or 0,
        "queue_name": s.get("队列类型", s.get("queue_name", "")),
        "map_id": s.get("地图ID", s.get("map_id", 0)) or 0,
        "map_name": s.get("地图", s.get("map_name", "")),
        "champion_id": s.get("英雄ID", s.get("champion_id", 0)) or 0,
        "position": s.get("位置", s.get("position", "")),
        "team_id": s.get("队伍ID", s.get("team_id", 0)) or 0,
        "win": 1 if s.get("胜利") else 0,
        "kills": s.get("击杀", s.get("kills", 0)) or 0,
        "deaths": s.get("死亡", s.get("deaths", 0)) or 0,
        "assists": s.get("助攻", s.get("assists", 0)) or 0,
        "kda": s.get("KDA", s.get("kda", 0)) or 0,
        "game_score": s.get("评分", s.get("game_score", 0)) or 0,
        "gold_earned": s.get("金币", s.get("gold_earned", 0)) or 0,
        "double_kills": s.get("双杀", s.get("double_kills", 0)) or 0,
        "triple_kills": s.get("三杀", s.get("triple_kills", 0)) or 0,
        "quadra_kills": s.get("四杀", s.get("quadra_kills", 0)) or 0,
        "penta_kills": s.get("五杀", s.get("penta_kills", 0)) or 0,
        "was_mvp": 1 if s.get("MVP") else 0,
        "was_svp": 1 if s.get("SVP") else 0,
        "was_surrender": 1 if s.get("投降") else 0,
        "was_afk": 1 if s.get("挂机") else 0,
        "most_kills": 1 if s.get("击杀最多") else 0,
        "most_assists": 1 if s.get("助攻最多") else 0,
        "most_gold": 1 if s.get("金币最多") else 0,
        "most_damage": 1 if s.get("伤害最高") else 0,
        "most_taken": 1 if s.get("承受伤害最高") else 0,
        "most_turrets": 1 if s.get("推塔最多") else 0,
        "tier": s.get("段位", ""),
        "league_points": s.get("胜点", 0) or 0,
        "rank": s.get("段位等级", ""),
        "game_version": s.get("游戏版本", ""),
    }


def _map_detail_rows(game_id: str, players: list[dict], self_openid: str) -> list[dict]:
    """将玩家详情字典列表映射为 SQLite 行数据列表。"""
    rows = []
    for p in players:
        is_self = 1 if (self_openid and p.get("openid", "") == self_openid) else 0
        kills = p.get("kills", 0) or 0
        deaths = p.get("deaths", 0) or 0
        assists = p.get("assists", 0) or 0

        rows.append({
            "game_id": str(game_id),
            "summoner_name": p.get("summoner_name", ""),
            "champion_id": p.get("champion_id", 0) or 0,
            "team_id": p.get("team_id", 0) or 0,
            "win": 1 if p.get("win") == "Win" else 0,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kda": round((kills + assists) / max(deaths, 1), 2),
            "item0": p.get("item0", 0) or 0,
            "item1": p.get("item1", 0) or 0,
            "item2": p.get("item2", 0) or 0,
            "item3": p.get("item3", 0) or 0,
            "item4": p.get("item4", 0) or 0,
            "item5": p.get("item5", 0) or 0,
            "item6": p.get("item6", 0) or 0,
            "spell1_id": p.get("spell1_id", 0) or 0,
            "spell2_id": p.get("spell2_id", 0) or 0,
            "perk0": p.get("PERK0", 0) or 0,
            "perk1": p.get("PERK1", 0) or 0,
            "perk2": p.get("PERK2", 0) or 0,
            "perk3": p.get("PERK3", 0) or 0,
            "perk4": p.get("PERK4", 0) or 0,
            "perk5": p.get("PERK5", 0) or 0,
            "total_damage": p.get("total_damage_dealt", 0) or 0,
            "total_taken": p.get("total_damage_taken", 0) or 0,
            "gold_earned": p.get("gold_earned", 0) or 0,
            "minions_killed": p.get("minions_killed", 0) or 0,
            "vision_score": p.get("vision_score", 0) or 0,
            "cc_score": p.get("cc_score", 0) or 0,
            "is_self": is_self,
        })
    return rows


def _map_summoner_profile_to_row(info: dict, career: dict | None,
                                   puin: str, fetched_at: str) -> dict:
    """将解析后的召唤师信息+生涯统计映射为 summoner_profile 行。"""
    row = {
        "puin": puin,
        "summoner_id": info.get("召唤师ID", 0),
        "summoner_name": info.get("召唤师名称", ""),
        "name_tag": info.get("标签", ""),
        "level": info.get("等级", 0),
        "experience": info.get("经验值", 0),
        "icon_id": info.get("头像ID", 0),
        "praise": info.get("点赞", 0),
        "discredit": info.get("点踩", 0),
        "top_of_canyon": 1 if info.get("峡谷之巅") else 0,
        "openid": info.get("openid", ""),
        "area": info.get("大区", 0),
        "season_sid": info.get("赛季ID", 0),
        "season_total": info.get("赛季总场次", 0),
        "season_wins": info.get("赛季胜场", 0),
        "season_losses": info.get("赛季负场", 0),
        "season_tier": info.get("段位", 0),
        "season_win_point": info.get("胜点", 0),
        "season_queue": info.get("单双排", 0),
        "last_fetch_time": fetched_at,
    }
    if career:
        row.update({
            "kill_30days": career.get("近30天击杀", 0),
            "death_30days": career.get("近30天死亡", 0),
            "assist_30days": career.get("近30天助攻", 0),
            "recent_win_times": career.get("近期胜场", 0),
            "recent_play_times": career.get("近期场次", 0),
            "last_game_id": career.get("最近对局ID", ""),
            "recent_kda_score": career.get("近期KDA分数", 0),
            "last_game_time": career.get("最后对局时间", ""),
            "common_champions": career.get("常用英雄JSON", "[]"),
            "common_positions": career.get("常用位置JSON", "[]"),
            "total_mvp_times": career.get("生涯MVP", 0),
            "total_svp_times": career.get("生涯SVP", 0),
            "total_god_likes": career.get("生涯超神", 0),
            "total_penta_kills": career.get("生涯五杀", 0),
            "total_quadra_kills": career.get("生涯四杀", 0),
            "total_triple_kills": career.get("生涯三杀", 0),
            "max_consecutive_wins": career.get("最长连胜", 0),
            "highest_game_score": career.get("最高评分", 0),
            "most_kills_num": career.get("单局最高击杀", 0),
            "most_assists_num": career.get("单局最高助攻", 0),
            "most_spree_kills_num": career.get("单局最高连杀", 0),
            "most_damage_num": career.get("单局最高伤害", 0),
            "most_damage_taken_num": career.get("单局最高承伤", 0),
            "most_gold_earned_num": career.get("单局最高经济", 0),
            "most_minions_kill_num": career.get("单局最高补刀", 0),
            "most_turrets_kill_num": career.get("单局最高推塔", 0),
            "total_kills": career.get("生涯总击杀", 0),
            "total_assists": career.get("生涯总助攻", 0),
            "total_ward_placed": career.get("生涯总插眼", 0),
            "longest_game_num": career.get("最长对局秒", 0),
            "shortest_game_num": career.get("最短对局秒", 0),
        })
    return row


def _map_snapshot_to_row(info: dict, career: dict | None,
                          puin: str, fetched_at: str) -> dict:
    """提取需要历史追踪的字段映射为 summoner_snapshot 行。"""
    row = {
        "puin": puin,
        "fetched_at": fetched_at,
        "level": info.get("等级", 0),
        "season_tier": info.get("段位", 0),
        "season_win_point": info.get("胜点", 0),
        "season_total": info.get("赛季总场次", 0),
        "season_wins": info.get("赛季胜场", 0),
        "season_losses": info.get("赛季负场", 0),
        "praise": info.get("点赞", 0),
        "discredit": info.get("点踩", 0),
    }
    if career:
        row.update({
            "total_kills": career.get("生涯总击杀", 0),
            "total_assists": career.get("生涯总助攻", 0),
            "total_mvp_times": career.get("生涯MVP", 0),
            "total_svp_times": career.get("生涯SVP", 0),
            "recent_win_times": career.get("近期胜场", 0),
            "recent_play_times": career.get("近期场次", 0),
        })
    return row


def _map_champion_mastery_to_row(champion: dict, puin: str, fetched_at: str) -> dict:
    """将解析后的英雄熟练度字典映射为 champion_mastery 行。"""
    return {
        "puin": puin,
        "champion_id": champion.get("英雄ID", 0),
        "total_games": champion.get("总场次", 0),
        "wins": champion.get("胜场", 0),
        "win_rate": champion.get("胜率", 0),
        "mastery_exp": champion.get("熟练度", 0),
        "expire_day": champion.get("到期天数", 0),
        "instance_id": str(champion.get("皮肤实例", "")),
        "sid_total": champion.get("赛季总场", 0),
        "sid_wins": champion.get("赛季胜场", 0),
        "sid_exp": champion.get("赛季经验", 0),
        "lanes_json": champion.get("常用分路JSON", "[]"),
        "last_fetch_time": fetched_at,
    }


def _map_champion_snapshot_to_row(champion: dict, puin: str, fetched_at: str) -> dict:
    """提取随时间变化的关键英雄熟练度指标。"""
    return {
        "puin": puin,
        "champion_id": champion.get("英雄ID", 0),
        "fetched_at": fetched_at,
        "total_games": champion.get("总场次", 0),
        "wins": champion.get("胜场", 0),
        "sid_total": champion.get("赛季总场", 0),
        "sid_wins": champion.get("赛季胜场", 0),
    }


def _map_season_history_to_row(season: dict, puin: str, fetched_at: str) -> dict:
    """将解析后的赛季数据映射为 season_history 行。"""
    return {
        "puin": puin,
        "sid": season.get("赛季ID", 0),
        "total_games": season.get("总场次", 0),
        "wins": season.get("胜场", 0),
        "losses": season.get("负场", 0),
        "tier": season.get("段位", 255),
        "win_point": season.get("胜点", 0),
        "queue": season.get("队列", 0),
        "team_total": season.get("组排总场", 0),
        "team_wins": season.get("组排胜场", 0),
        "team_losses": season.get("组排负场", 0),
        "team_tier": season.get("组排段位", 255),
        "team_win_point": season.get("组排胜点", 0),
        "team_queue": season.get("组排队列", 0),
        "last_fetch_time": fetched_at,
    }


def _map_career_overview_to_row(battle_count: dict, puin: str, fetched_at: str) -> dict:
    """将解析后的战斗总览映射为 career_overview 行。"""
    return {
        "puin": puin,
        "total_match_games": battle_count.get("匹配总场", 0),
        "total_match_wins": battle_count.get("匹配胜场", 0),
        "total_match_losses": battle_count.get("匹配负场", 0),
        "total_aram_games": battle_count.get("大乱斗总场", 0),
        "total_aram_wins": battle_count.get("大乱斗胜场", 0),
        "total_aram_losses": battle_count.get("大乱斗负场", 0),
        "total_rank_games": battle_count.get("单双排总场", 0),
        "total_rank_wins": battle_count.get("单双排胜场", 0),
        "total_rank_losses": battle_count.get("单双排负场", 0),
        "total_teamrank_games": battle_count.get("组排总场", 0),
        "total_teamrank_wins": battle_count.get("组排胜场", 0),
        "total_teamrank_losses": battle_count.get("组排负场", 0),
        "total_all_games": battle_count.get("全部总场", 0),
        "total_all_wins": battle_count.get("全部胜场", 0),
        "total_all_losses": battle_count.get("全部负场", 0),
        "total_ai_games": battle_count.get("人机总场", 0),
        "total_ai_wins": battle_count.get("人机胜场", 0),
        "total_clash_games": battle_count.get("clash总场", 0),
        "last_fetch_time": fetched_at,
    }


def _ts_to_iso(ts) -> str:
    """将浮点秒数（或毫秒）时间戳转换为 ISO 日期时间字符串。"""
    if not ts:
        return ""
    try:
        t = float(ts)
        if t > 1e12:  # 毫秒时间戳
            t /= 1000.0
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return ""


def export_sqlite(
    parsed_battles: list[dict],
    details: dict[str, dict] | None,
    filepath: str,
    self_openid: str = "",
    summoner_info: dict | None = None,
    summoner_career: dict | None = None,
    puin: str = "",
    champions: list[dict] | None = None,
    battle_report: dict | None = None,
) -> str:
    """将对局摘要、详情和召唤师数据导出到 SQLite 数据库。

    创建四张表:
      - match_summary: 每局一行（以玩家视角记录）
      - match_detail: 每局每位玩家一行（每局最多 10 行，来自 GetBattleDetail）
      - summoner_profile: 召唤师当前信息快照（来自 GetSummonerInfo + GetPlayerRecentStat）
      - summoner_snapshot: 召唤师历史快照（每次运行追加，追踪段位/等级变化）

    Args:
        parsed_battles: 解析后的对局摘要字典列表（来自 parse_battle_summary）。
        details: 可选，game_id → 解析后的详情字典（来自 parse_battle_detail）。
        filepath: 输出 .db 路径。
        self_openid: 当前用户的 openid，用于在详情行中标记 is_self。
        summoner_info: 可选，解析后的召唤师信息（来自 parse_summoner_info）。
        summoner_career: 可选，解析后的生涯统计（来自 parse_player_recent_stat）。
        puin: 当前用户的 puin，用作 summoner_profile 主键。

    Returns:
        创建的数据库文件的绝对路径。
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(filepath)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    db.execute(SQL_CREATE_MATCH_SUMMARY)
    db.execute(SQL_CREATE_MATCH_DETAIL)
    db.execute(SQL_CREATE_SUMMONER_PROFILE)
    db.execute(SQL_CREATE_SUMMONER_SNAPSHOT)
    db.execute(SQL_INDEX_SNAPSHOT)
    db.execute(SQL_CREATE_CHAMPION_MASTERY)
    db.execute(SQL_CREATE_CHAMPION_SNAPSHOT)
    db.execute(SQL_CREATE_SEASON_HISTORY)
    db.execute(SQL_CREATE_CAREER_OVERVIEW)
    db.execute(SQL_INDEX_CHAMPION_SNAPSHOT)

    # 在 match_detail 上建立 (game_id, summoner_name) 唯一索引，
    # 便于重跑时通过 INSERT OR IGNORE 跳过已存在的玩家行。
    try:
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "idx_match_detail_game_player "
            "ON match_detail(game_id, summoner_name)"
        )
    except sqlite3.IntegrityError:
        logger.warning(
            "无法在 match_detail(game_id, summoner_name) 上创建唯一索引 "
            "—— 检测到已有重复数据。新增重复数据将"
            "通过应用层过滤拦截。"
        )

    # 写入对局摘要
    placeholders = ", ".join("?" * len(SUMMARY_COLUMNS))
    insert_summary = f"INSERT OR REPLACE INTO match_summary ({', '.join(SUMMARY_COLUMNS)}) VALUES ({placeholders})"

    summary_rows = []
    for b in parsed_battles:
        row = _map_summary_to_row(b)
        summary_rows.append(tuple(row[col] for col in SUMMARY_COLUMNS))

    db.executemany(insert_summary, summary_rows)
    logger.info("SQLite match_summary: %d 行", len(summary_rows))

    # 写入对局详情（含去重）
    if details:
        # 查询已有 (game_id, summoner_name) 对用于去重
        existing_detail_pairs: set[tuple[str, str]] = set()
        try:
            rows = db.execute(
                "SELECT game_id, summoner_name FROM match_detail"
            ).fetchall()
            existing_detail_pairs = {(r[0], r[1]) for r in rows}
        except sqlite3.OperationalError:
            pass  # 表可能尚不存在（理论上不会，但安全起见）

        detail_placeholders = ", ".join("?" * len(DETAIL_COLUMNS))
        insert_detail = (
            f"INSERT OR IGNORE INTO match_detail "
            f"({', '.join(DETAIL_COLUMNS)}) VALUES ({detail_placeholders})"
        )

        detail_rows = []
        skipped = 0
        for gid_str, detail in details.items():
            players = detail.get("all_players", [])
            if players:
                rows = _map_detail_rows(gid_str, players, self_openid)
                for r in rows:
                    pair = (r["game_id"], r["summoner_name"])
                    if pair in existing_detail_pairs:
                        skipped += 1
                        continue
                    detail_rows.append(tuple(r[col] for col in DETAIL_COLUMNS))
                    existing_detail_pairs.add(pair)  # 同时防止批次内重复

        if detail_rows:
            db.executemany(insert_detail, detail_rows)
        logger.info("SQLite match_detail: %d 新增行（%d 局），跳过 %d 行",
                     len(detail_rows), len(details), skipped)

    # 写入召唤师资料（当前快照 + 历史快照）
    if summoner_info:
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 写入 summoner_profile（INSERT OR REPLACE）
        profile_row = _map_summoner_profile_to_row(
            summoner_info, summoner_career, puin, fetched_at)
        profile_placeholders = ", ".join("?" * len(SUMMONER_PROFILE_COLUMNS))
        insert_profile = (
            f"INSERT OR REPLACE INTO summoner_profile "
            f"({', '.join(SUMMONER_PROFILE_COLUMNS)}) "
            f"VALUES ({profile_placeholders})"
        )
        db.execute(insert_profile,
                   tuple(profile_row[col] for col in SUMMONER_PROFILE_COLUMNS))
        logger.info("SQLite summoner_profile: 已更新")

        # 写入 summoner_snapshot（INSERT OR IGNORE，唯一索引防重）
        snapshot_row = _map_snapshot_to_row(
            summoner_info, summoner_career, puin, fetched_at)
        snapshot_placeholders = ", ".join("?" * len(SUMMONER_SNAPSHOT_COLUMNS))
        insert_snapshot = (
            f"INSERT OR IGNORE INTO summoner_snapshot "
            f"({', '.join(SUMMONER_SNAPSHOT_COLUMNS)}) "
            f"VALUES ({snapshot_placeholders})"
        )
        db.execute(insert_snapshot,
                   tuple(snapshot_row[col] for col in SUMMONER_SNAPSHOT_COLUMNS))
        logger.info("SQLite summoner_snapshot: 已记录")

    # 写入英雄熟练度数据
    if champions:
        champ_fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # champion_mastery: INSERT OR REPLACE
        champ_placeholders = ", ".join("?" * len(CHAMPION_MASTERY_COLUMNS))
        insert_champ = (
            f"INSERT OR REPLACE INTO champion_mastery "
            f"({', '.join(CHAMPION_MASTERY_COLUMNS)}) "
            f"VALUES ({champ_placeholders})"
        )
        champ_rows = [
            tuple(_map_champion_mastery_to_row(c, puin, champ_fetched_at)[col]
                  for col in CHAMPION_MASTERY_COLUMNS)
            for c in champions
        ]
        db.executemany(insert_champ, champ_rows)
        logger.info("SQLite champion_mastery: %d 行", len(champ_rows))

        # champion_mastery_snapshot: INSERT OR IGNORE
        snap_placeholders = ", ".join("?" * len(CHAMPION_SNAPSHOT_COLUMNS))
        insert_champ_snap = (
            f"INSERT OR IGNORE INTO champion_mastery_snapshot "
            f"({', '.join(CHAMPION_SNAPSHOT_COLUMNS)}) "
            f"VALUES ({snap_placeholders})"
        )
        snap_rows = [
            tuple(_map_champion_snapshot_to_row(c, puin, champ_fetched_at)[col]
                  for col in CHAMPION_SNAPSHOT_COLUMNS)
            for c in champions
        ]
        db.executemany(insert_champ_snap, snap_rows)
        logger.info("SQLite champion_mastery_snapshot: %d 行", len(snap_rows))

    # 写入赛季历史与战斗总览
    if battle_report:
        br_fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # season_history: INSERT OR REPLACE
        season_placeholders = ", ".join("?" * len(SEASON_HISTORY_COLUMNS))
        insert_season = (
            f"INSERT OR REPLACE INTO season_history "
            f"({', '.join(SEASON_HISTORY_COLUMNS)}) "
            f"VALUES ({season_placeholders})"
        )
        season_rows = [
            tuple(_map_season_history_to_row(s, puin, br_fetched_at)[col]
                  for col in SEASON_HISTORY_COLUMNS)
            for s in battle_report.get("season_list", [])
        ]
        if season_rows:
            db.executemany(insert_season, season_rows)
        logger.info("SQLite season_history: %d 行", len(season_rows))

        # career_overview: INSERT OR REPLACE
        career_placeholders = ", ".join("?" * len(CAREER_OVERVIEW_COLUMNS))
        insert_career = (
            f"INSERT OR REPLACE INTO career_overview "
            f"({', '.join(CAREER_OVERVIEW_COLUMNS)}) "
            f"VALUES ({career_placeholders})"
        )
        career_row = _map_career_overview_to_row(
            battle_report.get("battle_count", {}), puin, br_fetched_at)
        db.execute(insert_career,
                   tuple(career_row[col] for col in CAREER_OVERVIEW_COLUMNS))
        logger.info("SQLite career_overview: 已更新")

    db.commit()
    db.close()

    file_size_kb = os.path.getsize(filepath) / 1024
    logger.info("SQLite 已导出: %s (%.1f KB)", filepath, file_size_kb)
    return str(Path(filepath).absolute())
