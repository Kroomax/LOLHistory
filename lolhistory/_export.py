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

# ── 注释元数据表 ─────────────────────────────────────────────────────────
# SQLite 不支持原生 COMMENT ON，通过元数据表存储表注释和字段注释。
# 新建数据库时自动创建并写入注释，已有数据库可通过 add_db_comments.py 补充。

SQL_CREATE_TABLE_COMMENTS = """
CREATE TABLE IF NOT EXISTS table_comments (
    table_name  TEXT PRIMARY KEY,
    comment     TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

SQL_CREATE_COLUMN_COMMENTS = """
CREATE TABLE IF NOT EXISTS column_comments (
    table_name  TEXT NOT NULL,
    column_name TEXT NOT NULL,
    comment     TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (table_name, column_name)
)
"""

# 表注释字典
_TABLE_COMMENTS = {
    "match_summary": (
        "对局摘要表。"
        "数据来源: WeGame API GetBattleList。"
        "以玩家视角记录每局比赛的核心数据，每局一行，game_id 主键唯一。"
        "包含 KDA、经济、荣誉标记、段位快照等 35 列。"
        "写入策略: INSERT OR REPLACE。"
    ),
    "match_detail": (
        "对局详情表。"
        "数据来源: WeGame API GetBattleDetail。"
        "记录每局 10 位玩家的完整数据，每局最多 10 行，每位玩家一行。"
        "包含装备(7件)、召唤师技能(2个)、符文(6个)、伤害/经济/视野等 32 列。"
        "通过 game_id 关联 match_summary 表。"
        "写入策略: INSERT OR IGNORE (通过 (game_id, summoner_name) 唯一索引去重)。"
    ),
    "summoner_profile": (
        "召唤师资料表。"
        "数据来源: GetSummonerInfo + GetPlayerRecentStat。"
        "用户当前状态的完整快照，55列。包含基本信息、赛季段位、近30天统计、生涯总数据。"
        "每次运行覆盖更新。写入策略: INSERT OR REPLACE (以 puin 为主键)。"
    ),
    "champion_mastery": (
        "英雄熟练度表。"
        "数据来源: WeGame API GetChampion (flag=2, 需 openid)。"
        "全部 172 个英雄的熟练度当前快照，每英雄一行，13列。"
        "包含场次、胜率、常用分路、赛季数据等。"
        "写入策略: INSERT OR REPLACE (以 (puin, champion_id) 复合主键去重)。"
    ),
    "season_history": (
        "赛季历史表。"
        "数据来源: WeGame API GetBattleReport (sids=[255] 获取所有赛季)。"
        "记录每个赛季的排位(单双排)和组排数据，每赛季一行，15列。"
        "包含场次、段位、胜点等信息。写入策略: INSERT OR REPLACE (以 (puin, sid) 复合主键去重)。"
    ),
    "career_overview": (
        "生涯全模式总览表。"
        "数据来源: WeGame API GetBattleReport.battle_count。"
        "记录用户在各游戏模式下(匹配/大乱斗/单双排/组排/人机/Clash/全部)的总场次、胜场、负场统计。"
        "每用户一行，19列。写入策略: INSERT OR REPLACE (以 puin 为主键)。"
    ),
}

# 字段注释字典
_COLUMN_COMMENTS = {
    "match_summary": {
        "game_id": "[主键] 对局唯一ID (WeGame game_id)",
        "game_start_time": "对局开始时间 (ISO 格式, 从 Unix 时间戳转换)",
        "game_time_played": "游戏时长 (秒)",
        "game_queue_id": "队列类型ID (参见 QUEUE_NAMES, 共96种)",
        "queue_name": "队列类型中文名 (如'单双排'、'匹配模式'、'极地大乱斗')",
        "map_id": "地图ID (参见 MAP_NAMES, 共17种)",
        "map_name": "地图中文名 (如'召唤师峡谷'、'嚎哭深渊')",
        "champion_id": "玩家使用英雄ID",
        "position": "玩家位置 (上单/打野/中单/下路/辅助)",
        "team_id": "队伍ID (100=蓝方, 200=红方)",
        "win": "是否胜利 (1=胜, 0=负)",
        "kills": "击杀数",
        "deaths": "死亡数",
        "assists": "助攻数",
        "kda": "KDA比率: (击杀+助攻)/max(死亡,1), 保留2位小数",
        "game_score": "游戏评分 (WeGame 评分系统)",
        "gold_earned": "获得金币总量",
        "double_kills": "双杀次数",
        "triple_kills": "三杀次数",
        "quadra_kills": "四杀次数",
        "penta_kills": "五杀次数",
        "was_mvp": "是否获得MVP (1=是, 0=否)",
        "was_svp": "是否获得SVP (1=是, 0=否, 败方最佳)",
        "was_surrender": "是否投降 (1=是, 0=否)",
        "was_afk": "是否挂机 (1=是, 0=否)",
        "most_kills": "击杀最多 (1=是, 0=否, 本局10人中该项最高)",
        "most_assists": "助攻最多 (1=是, 0=否, 本局10人中该项最高)",
        "most_gold": "金币最多 (1=是, 0=否, 本局10人中该项最高)",
        "most_damage": "伤害最高 (1=是, 0=否, 本局10人中该项最高)",
        "most_taken": "承受伤害最高 (1=是, 0=否, 本局10人中该项最高)",
        "most_turrets": "推塔最多 (1=是, 0=否, 本局10人中该项最高)",
        "tier": "段位名称 (如'黄金'、'铂金', 来自 game_level JSON)",
        "league_points": "胜点 (0-100, 对局时的段位快照)",
        "rank": "段位等级 (如'III'、'IV', 对局时的段位快照)",
        "game_version": "游戏版本号 (如 14.10.xxx)",
    },
    "match_detail": {
        "id": "[主键] 自增行ID",
        "game_id": "对局ID (外键 -> match_summary.game_id)",
        "summoner_name": "召唤师名称",
        "champion_id": "英雄ID",
        "team_id": "队伍ID (100=蓝方, 200=红方)",
        "win": "是否胜利 (1=胜, 0=负)",
        "kills": "击杀数",
        "deaths": "死亡数",
        "assists": "助攻数",
        "kda": "KDA比率: (击杀+助攻)/max(死亡,1)",
        "item0": "装备栏1 物品ID",
        "item1": "装备栏2 物品ID",
        "item2": "装备栏3 物品ID",
        "item3": "装备栏4 物品ID",
        "item4": "装备栏5 物品ID",
        "item5": "装备栏6 物品ID",
        "item6": "饰品栏 物品ID",
        "spell1_id": "召唤师技能1 ID (如 4=闪现, 14=点燃)",
        "spell2_id": "召唤师技能2 ID",
        "perk0": "主系基石符文ID",
        "perk1": "主系第一排符文ID",
        "perk2": "主系第二排符文ID",
        "perk3": "主系第三排符文ID",
        "perk4": "副系第一排符文ID",
        "perk5": "副系第二排符文ID (属性碎片)",
        "total_damage": "对英雄造成总伤害",
        "total_taken": "承受总伤害",
        "gold_earned": "获得金币总量",
        "minions_killed": "补刀数 (小兵+野怪)",
        "vision_score": "视野得分",
        "cc_score": "控制得分 (硬控/软控)",
        "is_self": "是否为自己 (1=是, 0=否, 通过 openid 匹配)",
    },
    "summoner_profile": {
        "puin": "[主键] WeGame 用户唯一标识 (数字UID)",
        "summoner_id": "召唤师数字ID (来自 WeGame 服务端)",
        "summoner_name": "召唤师名称 (不含 #tag)",
        "name_tag": "召唤师标签 (#后的部分)",
        "level": "召唤师等级",
        "experience": "经验值",
        "icon_id": "头像ID",
        "praise": "点赞数 (荣誉系统)",
        "discredit": "点踩数",
        "top_of_canyon": "是否峡谷之巅玩家 (1=是, 0=否)",
        "openid": "加密 openid (用于 account_type=2 的 API 调用)",
        "area": "服务器大区编号 (1=艾欧尼亚, 默认1)",
        "season_sid": "当前赛季ID",
        "season_total": "当前赛季总场次",
        "season_wins": "当前赛季胜场",
        "season_losses": "当前赛季负场",
        "season_tier": "当前赛季段位 (WeGame编号: 1钻石 2翡翠 3铂金 4黄金 5白银 6大师 7宗师 8王者)",
        "season_win_point": "当前赛季胜点 (0-100)",
        "season_queue": "当前赛季队列类型 (单双排/组排)",
        "kill_30days": "近30天击杀总数",
        "death_30days": "近30天死亡总数",
        "assist_30days": "近30天助攻总数",
        "recent_win_times": "近30天胜场",
        "recent_play_times": "近30天总场次",
        "last_game_id": "最近一场对局ID",
        "recent_kda_score": "近30天KDA评分",
        "last_game_time": "最后对局时间",
        "common_champions": "常用英雄列表 (JSON 字符串数组)",
        "common_positions": "常用位置列表 (JSON 字符串数组)",
        "total_mvp_times": "生涯MVP总次数",
        "total_svp_times": "生涯SVP总次数 (败方最佳)",
        "total_god_likes": "生涯超神次数 (连续击杀不作死亡)",
        "total_penta_kills": "生涯五杀次数",
        "total_quadra_kills": "生涯四杀次数",
        "total_triple_kills": "生涯三杀次数",
        "max_consecutive_wins": "生涯最长连胜场次",
        "highest_game_score": "生涯单局最高评分",
        "most_kills_num": "生涯单局最高击杀数",
        "most_assists_num": "生涯单局最高助攻数",
        "most_spree_kills_num": "生涯单局最高连杀数",
        "most_damage_num": "生涯单局最高伤害",
        "most_damage_taken_num": "生涯单局最高承伤",
        "most_gold_earned_num": "生涯单局最高经济",
        "most_minions_kill_num": "生涯单局最高补刀",
        "most_turrets_kill_num": "生涯单局最高推塔",
        "total_kills": "生涯总击杀",
        "total_assists": "生涯总助攻",
        "total_ward_placed": "生涯总插眼数",
        "longest_game_num": "生涯最长对局时长 (秒)",
        "shortest_game_num": "生涯最短对局时长 (秒)",
        "last_fetch_time": "最后数据获取时间 (ISO 格式)",
    },
    "champion_mastery": {
        "puin": "WeGame 用户唯一标识",
        "champion_id": "英雄ID",
        "total_games": "该英雄总场次",
        "wins": "该英雄胜场",
        "win_rate": "该英雄胜率 (百分比, 如 55.3 表示 55.3%)",
        "mastery_exp": "熟练度经验值 (用于计算熟练度等级)",
        "expire_day": "熟练度到期天数 (-1=永久)",
        "instance_id": "当前装备的皮肤实例ID",
        "sid_total": "当前赛季使用该英雄总场次",
        "sid_wins": "当前赛季使用该英雄胜场",
        "sid_exp": "当前赛季该英雄经验值",
        "lanes_json": "常用分路列表 (JSON 字符串, 如 [\"中路\",\"上路\"])",
        "last_fetch_time": "最后数据获取时间 (ISO 格式)",
    },
    "season_history": {
        "puin": "WeGame 用户唯一标识",
        "sid": "赛季ID (数值, 如 26)",
        "total_games": "该赛季单双排总场次",
        "wins": "该赛季单双排胜场",
        "losses": "该赛季单双排负场",
        "tier": "该赛季单双排段位 (WeGame编号, 255=未定级)",
        "win_point": "该赛季单双排胜点 (0-100)",
        "queue": "单双排队列类型编号",
        "team_total": "该赛季组排总场次",
        "team_wins": "该赛季组排胜场",
        "team_losses": "该赛季组排负场",
        "team_tier": "该赛季组排段位 (WeGame编号, 255=未定级)",
        "team_win_point": "该赛季组排胜点 (0-100)",
        "team_queue": "组排队列类型编号",
        "last_fetch_time": "最后数据获取时间 (ISO 格式)",
    },
    "career_overview": {
        "puin": "[主键] WeGame 用户唯一标识",
        "total_match_games": "匹配模式总场次",
        "total_match_wins": "匹配模式胜场",
        "total_match_losses": "匹配模式负场",
        "total_aram_games": "大乱斗总场次",
        "total_aram_wins": "大乱斗胜场",
        "total_aram_losses": "大乱斗负场",
        "total_rank_games": "单双排总场次",
        "total_rank_wins": "单双排胜场",
        "total_rank_losses": "单双排负场",
        "total_teamrank_games": "组排总场次",
        "total_teamrank_wins": "组排胜场",
        "total_teamrank_losses": "组排负场",
        "total_all_games": "全部模式总场次",
        "total_all_wins": "全部模式胜场",
        "total_all_losses": "全部模式负场",
        "total_ai_games": "人机模式总场次",
        "total_ai_wins": "人机模式胜场",
        "total_clash_games": "Clash (冠军杯) 总场次",
        "last_fetch_time": "最后数据获取时间 (ISO 格式)",
    },
}


def _ensure_table_comments(db: sqlite3.Connection):
    """确保数据库中已创建注释元数据表并写入全部注释。

    每次运行时调用，INSERT OR REPLACE 保证幂等性——
    不会因为多次运行产生重复数据，也不会覆盖手动修改的注释。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(SQL_CREATE_TABLE_COMMENTS)
    db.execute(SQL_CREATE_COLUMN_COMMENTS)

    for table_name, comment in _TABLE_COMMENTS.items():
        db.execute(
            "INSERT OR REPLACE INTO table_comments (table_name, comment, updated_at) VALUES (?, ?, ?)",
            (table_name, comment, now),
        )

    for table_name, columns in _COLUMN_COMMENTS.items():
        for col_name, comment in columns.items():
            db.execute(
                "INSERT OR REPLACE INTO column_comments (table_name, column_name, comment, updated_at) VALUES (?, ?, ?, ?)",
                (table_name, col_name, comment, now),
            )


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

CHAMPION_MASTERY_COLUMNS = [
    "puin", "champion_id", "total_games", "wins", "win_rate",
    "mastery_exp", "expire_day", "instance_id",
    "sid_total", "sid_wins", "sid_exp",
    "lanes_json", "last_fetch_time",
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

    创建三张表:
      - match_summary: 每局一行（以玩家视角记录）
      - match_detail: 每局每位玩家一行（每局最多 10 行，来自 GetBattleDetail）
      - summoner_profile: 召唤师当前信息快照（来自 GetSummonerInfo + GetPlayerRecentStat）

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
    db.execute(SQL_CREATE_CHAMPION_MASTERY)
    db.execute(SQL_CREATE_SEASON_HISTORY)
    db.execute(SQL_CREATE_CAREER_OVERVIEW)

    # 清理旧表（v1 遗留，已不再使用）
    db.execute("DROP TABLE IF EXISTS champion_mastery_snapshot")
    db.execute("DROP TABLE IF EXISTS summoner_snapshot")

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

    # 写入注释元数据 (INSERT OR REPLACE, 幂等)
    _ensure_table_comments(db)

    db.commit()
    db.close()

    file_size_kb = os.path.getsize(filepath) / 1024
    logger.info("SQLite 已导出: %s (%.1f KB)", filepath, file_size_kb)
    return str(Path(filepath).absolute())
