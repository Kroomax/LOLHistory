"""生成演示用模拟数据，用于项目展示。

用法:
    .venv/Scripts/python demo/demo_generate_data.py     # 生成 996 局多区 db + 报告
                                                        # 输出到 demo/demo_matches.db
                                                        #        demo/demo_report.html
    # 无传入参数，固定 996 局。如需调整请直接修改脚本。
"""

import sys
import json
import sqlite3
import random
import os
from datetime import datetime, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中，以便 from lolhistory 导入
# 当脚本在 demo/ 子目录中运行时，sys.path[0] 是 demo/ 而非项目根目录
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# ── 常量 ────────────────────────────────────────────────────────────────────

# 英雄池（15个常用英雄）：id, 名称, 位置, 权重
HERO_POOL = [
    (157, "Yasuo 亚索", "MIDDLE", 20),
    (64, "LeeSin 李青", "JUNGLE", 15),
    (238, "Zed 劫", "MIDDLE", 14),
    (103, "Ahri 阿狸", "MIDDLE", 13),
    (81, "Ezreal 伊泽瑞尔", "BOTTOM", 12),
    (222, "Jinx 金克丝", "BOTTOM", 10),
    (122, "Darius 德莱厄斯", "TOP", 10),
    (92, "Riven 锐雯", "TOP", 8),
    (412, "Thresh 锤石", "UTILITY", 8),
    (89, "Leona 蕾欧娜", "UTILITY", 7),
    (11, "MasterYi 易", "JUNGLE", 7),
    (55, "Katarina 卡特琳娜", "MIDDLE", 6),
    (67, "Vayne 薇恩", "BOTTOM", 6),
    (141, "Kayn 凯隐", "JUNGLE", 5),
    (39, "Irelia 艾瑞莉娅", "TOP", 5),
]

# 所有英雄熟练度数据（forge ~60个英雄的熟练度）
MASTERY_POOL = [
    (157, 120, 68, 56.7, 85000), (64, 85, 45, 52.9, 62000),
    (238, 72, 38, 52.8, 58000), (103, 55, 30, 54.5, 45000),
    (81, 48, 25, 52.1, 38000), (222, 40, 21, 52.5, 32000),
    (122, 35, 18, 51.4, 28000), (92, 30, 16, 53.3, 25000),
    (412, 28, 14, 50.0, 22000), (89, 25, 13, 52.0, 20000),
    (11, 22, 12, 54.5, 18000), (55, 20, 10, 50.0, 16000),
    (67, 18, 9, 50.0, 14000), (141, 15, 8, 53.3, 12000),
    (39, 15, 7, 46.7, 11000),
    (86, 12, 6, 50.0, 9000), (84, 10, 5, 50.0, 8000),
    (1, 10, 5, 50.0, 7500), (4, 8, 4, 50.0, 6000),
    (24, 8, 4, 50.0, 6000), (5, 7, 3, 42.9, 5000),
    (114, 7, 4, 57.1, 5000), (41, 6, 3, 50.0, 4500),
    (31, 6, 3, 50.0, 4000), (57, 5, 2, 40.0, 3500),
    (14, 5, 2, 40.0, 3000), (36, 5, 3, 60.0, 3000),
    (75, 5, 2, 40.0, 2800), (28, 4, 2, 50.0, 2500),
    (77, 4, 2, 50.0, 2200), (102, 4, 1, 25.0, 2000),
    (23, 4, 2, 50.0, 2000), (106, 3, 1, 33.3, 1800),
    (150, 3, 1, 33.3, 1500), (68, 3, 2, 66.7, 1500),
    (98, 3, 1, 33.3, 1400), (80, 3, 2, 66.7, 1200),
    (120, 3, 1, 33.3, 1200), (91, 3, 1, 33.3, 1000),
    (107, 3, 2, 66.7, 1000), (60, 2, 1, 50.0, 800),
    (266, 2, 0, 0.0, 700), (17, 2, 1, 50.0, 700),
    (18, 2, 1, 50.0, 600), (21, 2, 1, 50.0, 600),
    (35, 2, 0, 0.0, 500), (22, 2, 1, 50.0, 500),
    (26, 1, 0, 0.0, 400), (62, 1, 1, 100.0, 400),
    (131, 1, 1, 100.0, 350), (63, 1, 0, 0.0, 300),
    (110, 1, 0, 0.0, 300), (99, 1, 1, 100.0, 300),
    (54, 1, 0, 0.0, 250), (78, 1, 1, 100.0, 250),
    (134, 1, 0, 0.0, 200), (104, 1, 0, 0.0, 200),
]

# 位置映射
POSITION_NAMES = {
    "TOP": "上单", "JUNGLE": "打野", "MIDDLE": "中单",
    "BOTTOM": "ADC", "UTILITY": "辅助",
}

# 队列类型（主要使用的）
QUEUE_TYPES = [
    (420, "Ranked Solo", 11),       # 单双排 → 召唤师峡谷
    (430, "Normal Blind", 11),      # 匹配模式
    (450, "ARAM", 12),              # 大乱斗
    (440, "Ranked Flex", 11),       # 组排（较少）
]

# WeGame 段位编码（所有赛季一致）：1=钻石, 2=铂金, 3=黄金, 4=白银, 5=青铜, 9=翡翠
# 与 _data.py WEGAME_TIER_NAMES 对齐
TIER_MAP = {0: 0, 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 7, 7: 8, 8: 9}

BASE_DATE = datetime(2026, 3, 15, 14, 0, 0)  # 数据起始日
END_DATE = datetime(2026, 6, 8, 23, 0, 0)     # 数据结束日
PUIN = "10086"
OPENID = "demo_openid_base64_xxx"

random.seed(42)

# ── 大区配置（3 个区，按权重分配局数）──────────────────────────────────────
# 每区独立参数：起始段位、胜率、英雄偏好，让报告数据有明显差异化
AREA_CONFIGS = [
    {
        "area_id": 1,
        "name": "艾欧尼亚",
        "name_tag": "电信一",
        "game_id_offset": 0,                     # game_id 前缀偏移（防冲突）
        "weight": 60,                            # 总局数占比 %
        "win_prob": {"ranked": 0.54, "normal": 0.55, "aram": 0.52},
        "start_tier": 3, "start_lp": 15, "start_rank": "IV",   # 铂金起步
        "hero_weights": {"MIDDLE": 1.8, "JUNGLE": 1.5,
                         "BOTTOM": 0.5, "TOP": 0.5, "UTILITY": 0.3},
        "summoner_name": "DemoPlayerOne",
        "level": 287,
    },
    {
        "area_id": 3,
        "name": "祖安",
        "name_tag": "网通二",
        "game_id_offset": 1,
        "weight": 25,
        "win_prob": {"ranked": 0.50, "normal": 0.51, "aram": 0.49},
        "start_tier": 4, "start_lp": 25, "start_rank": "III",  # 黄金起步
        "hero_weights": {"BOTTOM": 1.6, "TOP": 1.4,
                         "MIDDLE": 0.7, "JUNGLE": 0.6, "UTILITY": 0.4},
        "summoner_name": "DemoPlayerZan",
        "level": 156,
    },
    {
        "area_id": 14,
        "name": "黑色玫瑰",
        "name_tag": "电信十",
        "game_id_offset": 2,
        "weight": 15,
        "win_prob": {"ranked": 0.47, "normal": 0.48, "aram": 0.48},
        "start_tier": 5, "start_lp": 10, "start_rank": "IV",   # 白银起步
        "hero_weights": {"UTILITY": 2.0, "TOP": 1.3,
                         "MIDDLE": 0.6, "JUNGLE": 0.5, "BOTTOM": 0.5},
        "summoner_name": "DemoPlayerRose",
        "level": 98,
    },
]

# 按 area_id 建立索引
_AREA_CONFIG_BY_ID = {ac["area_id"]: ac for ac in AREA_CONFIGS}

# ── SQL 建表 ─────────────────────────────────────────────────────────────────

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
    game_version    TEXT,
    area            INTEGER DEFAULT 1
)
"""

SQL_CREATE_SUMMONER_PROFILE = """
CREATE TABLE IF NOT EXISTS summoner_profile (
    puin                 TEXT NOT NULL,
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
    season_sid           INTEGER,
    season_total         INTEGER,
    season_wins          INTEGER,
    season_losses        INTEGER,
    season_tier          INTEGER,
    season_win_point     INTEGER,
    season_queue         INTEGER,
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
    last_fetch_time      TEXT,
    PRIMARY KEY (puin, area)
)
"""

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
    area            INTEGER DEFAULT 1,
    sid_total       INTEGER,
    sid_wins        INTEGER,
    sid_exp         INTEGER,
    lanes_json      TEXT,
    last_fetch_time TEXT,
    PRIMARY KEY (puin, champion_id, area)
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
    area            INTEGER DEFAULT 1,
    last_fetch_time TEXT,
    PRIMARY KEY (puin, sid, area)
)
"""

SQL_CREATE_CAREER_OVERVIEW = """
CREATE TABLE IF NOT EXISTS career_overview (
    puin                TEXT NOT NULL,
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
    area                INTEGER DEFAULT 1,
    last_fetch_time     TEXT,
    PRIMARY KEY (puin, area)
)
"""

def weighted_choice(items, weights):
    """按权重随机选择。"""
    total = sum(weights)
    r = random.random() * total
    cumulative = 0
    for item, w in zip(items, weights):
        cumulative += w
        if r <= cumulative:
            return item
    return items[-1]


def pick_hero(area_config: dict | None = None) -> tuple[int, str, str]:
    """按权重随机选择英雄，area_config 中的 hero_weights 可调整各位置偏好。"""
    hero_weights = (area_config or {}).get("hero_weights", {})
    if not hero_weights:
        adjusted = HERO_POOL
    else:
        adjusted = [(h[0], h[1], h[2], h[3] * hero_weights.get(h[2], 1.0))
                    for h in HERO_POOL]
    hero = weighted_choice(adjusted, [h[3] for h in adjusted])
    return hero[0], hero[1], hero[2]  # id, name, position


def random_kda(is_win: bool) -> tuple[int, int, int, float]:
    """生成合理的 KDA 数据。"""
    if is_win:
        kills = random.choices([3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15],
                               weights=[3, 5, 8, 10, 12, 10, 8, 6, 4, 2, 1])[0]
        deaths = random.choices([0, 1, 2, 3, 4, 5, 6],
                                weights=[2, 5, 10, 12, 8, 3, 1])[0]
    else:
        kills = random.choices([0, 1, 2, 3, 4, 5, 6, 7, 8],
                               weights=[3, 5, 10, 12, 10, 7, 4, 2, 1])[0]
        deaths = random.choices([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                                weights=[2, 5, 8, 10, 12, 10, 8, 5, 3, 1])[0]
    assists = random.randint(max(0, kills - 2), kills + 5)
    kda = round((kills + assists) / max(deaths, 1), 2)
    return kills, deaths, assists, kda


def random_honors(kills: int, deaths: int, assists: int, gold: int,
                  is_win: bool) -> dict[str, int]:
    """随机生成荣誉标记。"""
    was_mvp = 1 if is_win and kills >= 8 and random.random() < 0.4 else 0
    if not was_mvp and is_win and kills >= 10:
        was_mvp = 1 if random.random() < 0.5 else 0
    was_svp = 1 if not is_win and kills >= 6 and random.random() < 0.3 else 0
    if not was_svp and not is_win and kills >= 8:
        was_svp = 1 if random.random() < 0.4 else 0

    return {
        "was_mvp": was_mvp,
        "was_svp": was_svp,
        "was_surrender": 1 if not is_win and random.random() < 0.08 else 0,
        "was_afk": 1 if random.random() < 0.015 else 0,
        "most_kills": 1 if kills >= 8 and random.random() < 0.4 else 0,
        "most_assists": 1 if assists >= 12 and random.random() < 0.5 else 0,
        "most_gold": 1 if gold > 14000 and random.random() < 0.3 else 0,
        "most_damage": 1 if kills >= 6 and random.random() < 0.35 else 0,
        "most_taken": 1 if deaths >= 5 and random.random() < 0.2 else 0,
        "most_turrets": 1 if is_win and kills >= 8 and random.random() < 0.3 else 0,
    }


def random_multikills(kills: int, is_win: bool) -> dict[str, int]:
    """随机生成多杀数据。"""
    return {
        "double_kills": min(kills // 2, random.randint(0, 3)),
        "triple_kills": 1 if kills >= 6 and random.random() < 0.5 else
                       (2 if kills >= 12 and random.random() < 0.3 else 0),
        "quadra_kills": 1 if kills >= 10 and random.random() < 0.15 else 0,
        "penta_kills": 1 if kills >= 12 and random.random() < 0.04 else 0,
    }


def _pick_game_hour(weekday: int) -> int:
    """根据星期几选择一个合理的游戏小时（周末和晚上更活跃）。"""
    if weekday >= 5:  # 周六日：全天活跃，下午到凌晨是高峰
        hour_weights = [0]*6 + [1, 2, 3, 5, 7, 9, 11, 14, 16, 17, 16, 14, 12, 10, 8, 5, 3, 1]
    else:  # 工作日：晚上才活跃
        hour_weights = [0]*12 + [0, 1, 1, 2, 3, 5, 8, 12, 15, 12, 8, 3]
    return random.choices(range(24), weights=hour_weights)[0]


def generate_matches(area_config: dict, num_games: int = 250) -> list[dict]:
    """生成模拟对局数据，包含明显的连续游戏轮次（session）。

    使用 area_config 控制胜率、段位起点、英雄偏好等差异化参数。
    约70%的对局属于某个连续轮次（session内间隔15-90分钟），
    约30%是孤立对局（session间间隔4-72小时）。
    """
    area_id = area_config["area_id"]
    matches = []
    current_date = BASE_DATE

    # 每区不同的段位起点（编码：3=铂金, 4=黄金, 5=白银）
    current_tier = area_config.get("start_tier", 4)
    current_lp = area_config.get("start_lp", 20)
    current_rank = area_config.get("start_rank", "III")

    # 每区不同的胜率
    win_prob_ranked = area_config.get("win_prob", {}).get("ranked", 0.52)
    win_prob_normal = area_config.get("win_prob", {}).get("normal", 0.53)
    win_prob_aram = area_config.get("win_prob", {}).get("aram", 0.50)

    ranked_games_count = 0
    game_counter = 1000000000 + area_config["game_id_offset"] * 1000000
    i = 0

    while i < num_games:
        # ── 决定本轮 session 大小 ──
        # 70% 概率生成一个 session（2-7局），30% 概率是孤立单局
        if random.random() < 0.70:
            session_size = random.choices(
                [2, 3, 4, 5, 6, 7],
                weights=[18, 25, 22, 15, 10, 10]
            )[0]
        else:
            session_size = 1

        # 不要超出总对局数
        remaining = num_games - i
        session_size = min(session_size, remaining)

        # ── 生成 session 起始时间 ──
        if i == 0:
            day_offset = 0
        else:
            day_offset = random.choices(
                [0, 1, 2, 3],
                weights=[30, 35, 25, 10]
            )[0]
            extra_hours = random.randint(0, 23)
            current_date += timedelta(days=day_offset, hours=extra_hours)

        weekday = current_date.weekday()
        session_start_hour = _pick_game_hour(weekday)
        session_start = current_date.replace(
            hour=session_start_hour,
            minute=random.randint(0, 59),
            second=0, microsecond=0
        )
        if session_start < current_date:
            session_start = current_date

        session_dt = session_start

        # ── 生成 session 内的每局对局 ──
        for j in range(session_size):
            i += 1
            game_counter += 1
            game_id = str(game_counter)

            # 决定队列类型
            if j == 0:
                queue_roll = random.random()
                if queue_roll < 0.55:
                    session_queue_type = "ranked"
                elif queue_roll < 0.70:
                    session_queue_type = "normal"
                elif queue_roll < 0.92:
                    session_queue_type = "aram"
                else:
                    session_queue_type = "flex"

            actual_type = session_queue_type
            if random.random() < 0.10:
                actual_type = random.choice(["ranked", "normal", "aram", "flex"])

            if actual_type == "ranked":
                queue_id, queue_name, map_id = QUEUE_TYPES[0]
            elif actual_type == "normal":
                queue_id, queue_name, map_id = QUEUE_TYPES[1]
            elif actual_type == "aram":
                queue_id, queue_name, map_id = QUEUE_TYPES[2]
            else:
                queue_id, queue_name, map_id = QUEUE_TYPES[3]

            is_ranked = queue_id == 420

            if j == 0:
                dt = session_dt
            else:
                session_dt += timedelta(
                    minutes=random.randint(20, 40),
                    seconds=random.randint(0, 3599)
                )
                dt = session_dt

            session_dt = dt + timedelta(minutes=random.randint(15, 35))

            # ── 选择英雄（每区不同偏好）──
            if queue_id == 450:
                hero_id = random.choice([h[0] for h in HERO_POOL[:10]])
                hero_name = next(h[1] for h in HERO_POOL if h[0] == hero_id)
                position = "Invalid"
            else:
                hero_id, hero_name, position = pick_hero(area_config)

            # ── 游戏时长 ──
            if queue_id == 450:
                duration = random.randint(900, 1800)
            else:
                duration = random.choices(
                    [15*60, 20*60, 25*60, 28*60, 30*60, 32*60, 35*60, 38*60, 42*60],
                    weights=[3, 8, 15, 20, 20, 15, 8, 3, 1]
                )[0] + random.randint(-120, 180)

            # ── 胜负（每区不同胜率）──
            if is_ranked:
                win_prob = win_prob_ranked
            elif queue_id == 450:
                win_prob = win_prob_aram
            else:
                win_prob = win_prob_normal
            if is_ranked and current_lp >= 80:
                win_prob -= 0.03
            is_win = random.random() < win_prob

            # ── KDA ──
            kills, deaths, assists, kda = random_kda(is_win)

            # ── 经济 ──
            if is_win:
                gold = int(duration / 60 * random.randint(300, 420))
            else:
                gold = int(duration / 60 * random.randint(220, 350))
            game_score = int(kda * 2000 + gold / 100 + kills * 500)
            if is_win:
                game_score = int(game_score * 1.3)

            # ── 荣誉 & 多杀 ──
            honors = random_honors(kills, deaths, assists, gold, is_win)
            mk = random_multikills(kills, is_win)

            # ── 段位快照 ──
            tier_str = str(current_tier) if is_ranked else ""
            lp_val = current_lp if is_ranked else 0
            rank_str = current_rank if is_ranked else ""

            # ── 更新段位 ──
            if is_ranked:
                ranked_games_count += 1
                if is_win:
                    lp_gain = random.choices(
                        [8, 10, 12, 14, 15, 16, 18, 20, 22, 25],
                        weights=[1, 2, 4, 5, 6, 5, 4, 2, 1, 0.5])[0]
                    current_lp += lp_gain
                else:
                    lp_loss = random.choices(
                        [8, 10, 12, 14, 15, 16, 18, 20, 22],
                        weights=[1, 2, 4, 6, 7, 5, 3, 1, 1])[0]
                    current_lp = max(0, current_lp - lp_loss)

                # 晋级/降级
                if current_lp >= 100:
                    if current_tier == 5 and random.random() < 0.5:
                        current_tier = 4; current_lp = random.randint(5, 20); current_rank = "IV"
                    elif current_tier == 4:
                        if random.random() < 0.6:
                            current_tier = 3
                            current_lp = random.randint(5, 25)
                            current_rank = random.choice(["II", "III"])
                        else:
                            current_lp = 75 + random.randint(0, 15)
                    elif current_tier == 3:
                        if ranked_games_count > 60 and random.random() < 0.5:
                            current_tier = 2
                            current_lp = random.randint(3, 20)
                            current_rank = "IV"
                        else:
                            current_lp = 70 + random.randint(0, 20)
                    else:
                        current_lp = random.randint(70, 99)
                elif current_lp <= 0:
                    current_lp = random.randint(5, 30)
                    if current_tier == 4 and random.random() < 0.1:
                        current_tier = 5; current_lp = 75; current_rank = "I"
                    elif current_tier == 3 and random.random() < 0.08:
                        current_tier = 4; current_lp = 75; current_rank = "I"

                # 小段晋升
                if current_lp > 60 and current_rank == "III" and random.random() < 0.05:
                    current_rank = "II"
                elif current_lp > 70 and current_rank == "II" and random.random() < 0.04:
                    current_rank = "I"

            # ── 写入记录 ──
            version = f"14.{random.randint(8, 15)}.{random.randint(100, 999)}"
            matches.append({
                "game_id": game_id,
                "game_start_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "_dt": dt,
                "game_time_played": duration,
                "game_queue_id": queue_id,
                "queue_name": queue_name,
                "map_id": map_id,
                "map_name": "Summoner's Rift" if map_id == 11 else "Howling Abyss",
                "champion_id": hero_id,
                "position": position,
                "team_id": random.choice([100, 200]),
                "win": 1 if is_win else 0,
                "kills": kills, "deaths": deaths, "assists": assists,
                "kda": kda, "game_score": game_score, "gold_earned": gold,
                **mk, **honors,
                "tier": tier_str, "league_points": lp_val, "rank": rank_str,
                "game_version": version, "area": area_id,
            })

        # ── session 结束 ──
        current_date = session_dt

    matches.sort(key=lambda m: m["_dt"])
    return matches


# ── 数据库写入 ────────────────────────────────────────────────────────────────

SUMMARY_COLS = [
    "game_id", "game_start_time", "game_time_played", "game_queue_id",
    "queue_name", "map_id", "map_name", "champion_id", "position", "team_id",
    "win", "kills", "deaths", "assists", "kda", "game_score", "gold_earned",
    "double_kills", "triple_kills", "quadra_kills", "penta_kills",
    "was_mvp", "was_svp", "was_surrender", "was_afk",
    "most_kills", "most_assists", "most_gold", "most_damage",
    "most_taken", "most_turrets",
    "tier", "league_points", "rank", "game_version", "area",
]
_SUMMARY_PLACEHOLDERS = ", ".join("?" * len(SUMMARY_COLS))


def _write_players_summary(db, matches: list[dict]):
    """写入对局摘要。"""
    rows = []
    for m in matches:
        rows.append(tuple(
            m.get(col, 0) if col not in ("tier", "rank", "queue_name",
                                          "map_name", "game_start_time",
                                          "game_version", "position")
            else m.get(col, "") for col in SUMMARY_COLS
        ))
    db.executemany(
        f"INSERT INTO match_summary ({', '.join(SUMMARY_COLS)}) VALUES ({_SUMMARY_PLACEHOLDERS})",
        rows,
    )
    print(f"    match_summary: {len(rows)} 行")


def _write_summoner_profile(db, area_config: dict, matches: list[dict], now: str):
    """写入召唤师资料（每区一行）。"""
    area = area_config["area_id"]
    ranked = [m for m in matches if m["game_queue_id"] == 420]
    total_games = len(matches)
    total_wins = sum(1 for m in matches if m["win"])
    total_kills = sum(m["kills"] for m in matches)
    total_assists = sum(m["assists"] for m in matches)
    total_mvp = sum(1 for m in matches if m["was_mvp"])
    total_svp = sum(1 for m in matches if m["was_svp"])
    total_penta = sum(m["penta_kills"] for m in matches)
    total_quadra = sum(m["quadra_kills"] for m in matches)
    total_triple = sum(m["triple_kills"] for m in matches)
    max_kills = max(m["kills"] for m in matches) if matches else 0
    max_assists = max(m["assists"] for m in matches) if matches else 0
    max_gold = max(m["gold_earned"] for m in matches) if matches else 0

    longest_streak = 0
    cur = 0
    for m in sorted(matches, key=lambda x: x["_dt"]):
        if m["win"]:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    last_ranked = ranked[-1] if ranked else None
    s_tier = int(last_ranked["tier"]) if last_ranked and last_ranked["tier"] else 3
    s_lp = last_ranked["league_points"] if last_ranked else 60
    s_total = len(ranked)
    s_wins = sum(1 for m in ranked if m["win"])

    last_dt = matches[-1]["_dt"] if matches else datetime.now()
    thirty_days_ago = last_dt - timedelta(days=30)
    recent = [m for m in matches if m["_dt"] >= thirty_days_ago]
    r_kills = sum(m["kills"] for m in recent)
    r_deaths = sum(m["deaths"] for m in recent)
    r_assists = sum(m["assists"] for m in recent)
    r_wins = sum(1 for m in recent if m["win"])

    # 根据每区英雄偏好生成 common_champions / common_positions
    hw = area_config["hero_weights"]
    best_poses = sorted(hw, key=hw.get, reverse=True)[:2]
    pos_names = [POSITION_NAMES[p] for p in best_poses]
    top_heroes = [h for h in HERO_POOL if h[2] in best_poses][:3]
    champ_names = [h[1].split()[-1] for h in top_heroes]

    profile_cols = [
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
    profile = {
        "puin": PUIN, "summoner_id": 10000000 + area,
        "summoner_name": area_config["summoner_name"],
        "name_tag": area_config["name_tag"],
        "level": area_config["level"],
        "experience": area_config["level"] * 500,
        "icon_id": random.randint(1, 50),
        "praise": random.randint(100, 800),
        "discredit": random.randint(0, 30),
        "top_of_canyon": 0,
        "openid": OPENID, "area": area,
        "season_sid": 26, "season_total": s_total,
        "season_wins": s_wins, "season_losses": s_total - s_wins,
        "season_tier": s_tier, "season_win_point": s_lp,
        "season_queue": 420,
        "kill_30days": r_kills, "death_30days": r_deaths,
        "assist_30days": r_assists,
        "recent_win_times": r_wins, "recent_play_times": len(recent),
        "last_game_id": matches[-1]["game_id"] if matches else "",
        "recent_kda_score": round((r_kills + r_assists) / max(r_deaths, 1) * 100),
        "last_game_time": matches[-1]["game_start_time"] if matches else "",
        "common_champions": json.dumps(champ_names),
        "common_positions": json.dumps(pos_names),
        "total_mvp_times": total_mvp, "total_svp_times": total_svp,
        "total_god_likes": total_penta * 3 + 15,
        "total_penta_kills": total_penta, "total_quadra_kills": total_quadra,
        "total_triple_kills": total_triple,
        "max_consecutive_wins": longest_streak,
        "highest_game_score": max(m["game_score"] for m in matches) if matches else 0,
        "most_kills_num": max_kills, "most_assists_num": max_assists,
        "most_spree_kills_num": max_kills,
        "most_damage_num": max(m.get("most_damage", 0) * random.randint(30000, 60000) for m in matches) if matches else 0,
        "most_damage_taken_num": random.randint(40000, 80000),
        "most_gold_earned_num": max_gold,
        "most_minions_kill_num": random.randint(200, 400),
        "most_turrets_kill_num": random.randint(3, 8),
        "total_kills": total_kills, "total_assists": total_assists,
        "total_ward_placed": total_games * random.randint(8, 20),
        "longest_game_num": max(m["game_time_played"] for m in matches) if matches else 0,
        "shortest_game_num": min(m["game_time_played"] for m in matches) if matches else 0,
        "last_fetch_time": now,
    }
    placeholders = ", ".join("?" * len(profile_cols))
    db.execute(
        f"INSERT INTO summoner_profile ({', '.join(profile_cols)}) VALUES ({placeholders})",
        tuple(profile.get(col, "") for col in profile_cols)
    )
    print(f"    summoner_profile（{area_config['name']}）: 1 行")


def _write_champion_mastery(db, area_config: dict, now: str):
    """写入英雄熟练度（每区不同偏好缩放）。"""
    area = area_config["area_id"]
    hw = area_config["hero_weights"]
    mastery_cols = [
        "puin", "champion_id", "total_games", "wins", "win_rate",
        "mastery_exp", "expire_day", "instance_id", "area",
        "sid_total", "sid_wins", "sid_exp", "lanes_json", "last_fetch_time",
    ]
    for cid, tg, w, wr, exp in MASTERY_POOL:
        hero = next((h for h in HERO_POOL if h[0] == cid), None)
        if hero:
            mul = hw.get(hero[2], 0.4)
            scaled_tg = max(1, int(tg * mul * 0.7))
            scaled_w = max(0, int(w * mul * 0.7))
            scaled_exp = max(100, int(exp * mul * 0.7))
            lanes = hero[2]
        else:
            scaled_tg = max(1, tg // 4)
            scaled_w = max(0, w // 4)
            scaled_exp = max(50, exp // 4)
            lanes = "MIDDLE"
        lanes_json = f'["{POSITION_NAMES.get(lanes, lanes)}"]'
        db.execute(
            f"INSERT INTO champion_mastery ({', '.join(mastery_cols)}) "
            f"VALUES ({', '.join('?' * len(mastery_cols))})",
            (PUIN, cid, scaled_tg, scaled_w, round(scaled_w / scaled_tg * 100, 1),
             scaled_exp, -1, "", area,
             scaled_tg, scaled_w, scaled_exp // 10, lanes_json, now)
        )
    print(f"    champion_mastery（{area_config['name']}）: {len(MASTERY_POOL)} 行")


def _write_season_history(db, area_config: dict, matches: list[dict], now: str):
    """写入赛季段位历史（每区独立的段位轨迹）。"""
    area = area_config["area_id"]
    ranked = [m for m in matches if m["game_queue_id"] == 420]
    s_total = len(ranked)
    s_wins = sum(1 for m in ranked if m["win"])
    last_ranked = ranked[-1] if ranked else None
    s_tier = int(last_ranked["tier"]) if last_ranked and last_ranked["tier"] else 3
    s_lp = last_ranked["league_points"] if last_ranked else 60

    season_cols = [
        "puin", "sid", "total_games", "wins", "losses",
        "tier", "win_point", "queue",
        "team_total", "team_wins", "team_losses",
        "team_tier", "team_win_point", "team_queue", "area", "last_fetch_time",
    ]
    # 根据起始段位生成 8 个赛季的递进数据
    base_tier = area_config["start_tier"]
    seasons_data = [
        (19, random.randint(30, 60), random.randint(12, 30), random.randint(12, 30),
         min(5, base_tier + 2), random.randint(20, 70), 420,
         random.randint(5, 20), random.randint(2, 10), random.randint(2, 10),
         min(5, base_tier + 2), random.randint(10, 60), 440),
        (20, random.randint(35, 65), random.randint(15, 33), random.randint(15, 33),
         min(5, base_tier + 1), random.randint(25, 75), 420,
         random.randint(5, 20), random.randint(3, 11), random.randint(2, 10),
         min(5, base_tier + 1), random.randint(15, 65), 440),
        (21, random.randint(40, 70), random.randint(18, 36), random.randint(18, 36),
         base_tier, random.randint(30, 80), 420,
         random.randint(8, 22), random.randint(4, 12), random.randint(3, 11),
         base_tier, random.randint(20, 70), 440),
        (22, random.randint(40, 70), random.randint(18, 36), random.randint(18, 36),
         base_tier, random.randint(25, 75), 420,
         random.randint(8, 22), random.randint(4, 12), random.randint(3, 11),
         base_tier, random.randint(15, 65), 440),
        (23, random.randint(45, 75), random.randint(20, 38), random.randint(20, 38),
         base_tier, random.randint(30, 80), 420,
         random.randint(10, 25), random.randint(5, 14), random.randint(4, 12),
         base_tier, random.randint(20, 70), 440),
        (24, random.randint(50, 80), random.randint(22, 42), random.randint(22, 42),
         max(2, base_tier - 1), random.randint(35, 85), 420,
         random.randint(10, 25), random.randint(5, 14), random.randint(4, 12),
         max(2, base_tier - 1), random.randint(25, 75), 440),
        (25, random.randint(50, 80), random.randint(22, 42), random.randint(22, 42),
         max(2, base_tier - 1), random.randint(30, 80), 420,
         random.randint(12, 28), random.randint(6, 15), random.randint(5, 14),
         max(2, base_tier - 1), random.randint(20, 70), 440),
        (26, s_total, s_wins, s_total - s_wins,
         s_tier, s_lp, 420,
         random.randint(10, 20), random.randint(4, 12), random.randint(4, 10),
         max(2, s_tier - 1), random.randint(15, 50), 440),
    ]
    for sid, tg, w, l, tier, wp, q, tt, tw, tl, ttier, twp, tq in seasons_data:
        db.execute(
            f"INSERT INTO season_history ({', '.join(season_cols)}) "
            f"VALUES ({', '.join('?' * len(season_cols))})",
            (PUIN, sid, tg, w, l, tier, wp, q, tt, tw, tl, ttier, twp, tq, area, now)
        )
    print(f"    season_history（{area_config['name']}）: {len(seasons_data)} 行")


def _write_career_overview(db, area_config: dict, matches: list[dict], now: str):
    """写入生涯总览（每区一行）。"""
    area = area_config["area_id"]
    total_games = len(matches)
    total_wins = sum(1 for m in matches if m["win"])
    rank_g = sum(1 for m in matches if m["game_queue_id"] == 420)
    rank_w = sum(1 for m in matches if m["game_queue_id"] == 420 and m["win"])
    match_g = sum(1 for m in matches if m["game_queue_id"] == 430)
    match_w = sum(1 for m in matches if m["game_queue_id"] == 430 and m["win"])
    aram_g = sum(1 for m in matches if m["game_queue_id"] == 450)
    aram_w = sum(1 for m in matches if m["game_queue_id"] == 450 and m["win"])
    flex_g = sum(1 for m in matches if m["game_queue_id"] == 440)
    flex_w = sum(1 for m in matches if m["game_queue_id"] == 440 and m["win"])

    career_cols = [
        "puin", "total_match_games", "total_match_wins", "total_match_losses",
        "total_aram_games", "total_aram_wins", "total_aram_losses",
        "total_rank_games", "total_rank_wins", "total_rank_losses",
        "total_teamrank_games", "total_teamrank_wins", "total_teamrank_losses",
        "total_all_games", "total_all_wins", "total_all_losses",
        "total_ai_games", "total_ai_wins", "total_clash_games", "area",
        "last_fetch_time",
    ]
    ai_g = random.randint(15, 40)
    clash_g = random.randint(3, 15)

    db.execute(
        f"INSERT INTO career_overview ({', '.join(career_cols)}) "
        f"VALUES ({', '.join('?' * len(career_cols))})",
        (PUIN, match_g, match_w, match_g - match_w,
         aram_g, aram_w, aram_g - aram_w,
         rank_g, rank_w, rank_g - rank_w,
         flex_g, flex_w, flex_g - flex_w,
         total_games, total_wins, total_games - total_wins,
         ai_g, ai_g, clash_g, area, now)
    )
    print(f"    career_overview（{area_config['name']}）: 1 行")


def create_database(area_matches: list[tuple[dict, list[dict]]],
                    db_path: str = "demo_matches.db"):
    """创建 demo SQLite 数据库（支持多区）。

    area_matches: list of (area_config, matches)
    """
    if Path(db_path).exists():
        os.remove(db_path)

    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")

    db.execute(SQL_CREATE_MATCH_SUMMARY)
    db.execute(SQL_CREATE_SUMMONER_PROFILE)
    db.execute(SQL_CREATE_CHAMPION_MASTERY)
    db.execute(SQL_CREATE_SEASON_HISTORY)
    db.execute(SQL_CREATE_CAREER_OVERVIEW)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_rows = 0

    for area_config, matches in area_matches:
        name = area_config["name"]
        print(f"\n  ── {name}（area={area_config['area_id']}）──")
        _write_players_summary(db, matches)
        _write_summoner_profile(db, area_config, matches, now)
        _write_champion_mastery(db, area_config, now)
        _write_season_history(db, area_config, matches, now)
        _write_career_overview(db, area_config, matches, now)
        total_rows += len(matches)

    db.commit()
    db.close()
    print(f"\n[OK] 数据库已创建: {db_path} ({os.path.getsize(db_path) / 1024:.1f} KB, 共 {total_rows} 局)")


# ── 主入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 固定参数：生成 996 局，3 个区，输出到 demo/ 目录
    NUM_GAMES = 996
    DB_PATH = Path(__file__).parent / "demo_matches.db"
    REPORT_PATH = Path(__file__).parent / "demo_report.html"

    # ── 解析大区配置 ──
    active_configs = AREA_CONFIGS

    # ── 按权重分配总局数 ──
    total_weight = sum(ac["weight"] for ac in active_configs)
    area_games = []
    for ac in active_configs:
        n = max(1, NUM_GAMES * ac["weight"] // total_weight)
        area_games.append(n)
    # 补足余数让总数精确
    diff = NUM_GAMES - sum(area_games)
    if diff > 0:
        area_games[-1] += diff

    # ── 生成每区数据（不同 seed 保证差异化）──
    all_area_matches: list[tuple[dict, list[dict]]] = []
    print(f"正在生成 {NUM_GAMES} 场模拟对局数据（{len(active_configs)} 个大区）...")
    for ac, n in zip(active_configs, area_games):
        random.seed(42 + ac["area_id"])
        print(f"  {ac['name']}（area={ac['area_id']}）: {n} 局")
        matches = generate_matches(ac, n)
        all_area_matches.append((ac, matches))

    # ── 写入数据库 ──
    print(f"\n正在写入数据库...")
    create_database(all_area_matches, str(DB_PATH))

    # ── 生成报告 ──
    print(f"\n正在生成分析报告...")
    from lolhistory._analysis import generate_report
    area_ids = [ac["area_id"] for ac in active_configs]
    path = generate_report(db_path=str(DB_PATH), output_path=str(REPORT_PATH),
                           area_ids=area_ids)
    print(f"\n[OK] 演示报告已生成: {path}")
    print(f"   在浏览器中打开即可查看。")
