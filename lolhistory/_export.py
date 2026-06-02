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
) -> str:
    """将对局摘要和详情导出到 SQLite 数据库。

    创建两张表:
      - match_summary: 每局一行（以玩家视角记录）
      - match_detail: 每局每位玩家一行（每局最多 10 行，来自 GetBattleDetail）

    Args:
        parsed_battles: 解析后的对局摘要字典列表（来自 parse_battle_summary）。
        details: 可选，game_id → 解析后的详情字典（来自 parse_battle_detail）。
        filepath: 输出 .db 路径。
        self_openid: 当前用户的 openid，用于在详情行中标记 is_self。

    Returns:
        创建的数据库文件的绝对路径。
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(filepath)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    db.execute(SQL_CREATE_MATCH_SUMMARY)
    db.execute(SQL_CREATE_MATCH_DETAIL)

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

    db.commit()
    db.close()

    file_size_kb = os.path.getsize(filepath) / 1024
    logger.info("SQLite 已导出: %s (%.1f KB)", filepath, file_size_kb)
    return str(Path(filepath).absolute())
