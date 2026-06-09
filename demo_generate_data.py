"""生成演示用模拟数据，用于项目展示。

用法:
    .venv/Scripts/python generate_demo_data.py              # 生成 db + 报告
    .venv/Scripts/python generate_demo_data.py --db-only    # 仅生成数据库
    .venv/Scripts/python generate_demo_data.py --games 500  # 自定义对局数
"""

import sqlite3
import random
import os
from datetime import datetime, timedelta
from pathlib import Path

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

# WeGame 段位 → 索引
TIER_MAP = {0: 0, 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 7, 7: 8, 8: 9}
# WeGame 段位 (3=铂金, 4=黄金, 2=翡翠, 1=钻石)

BASE_DATE = datetime(2026, 3, 15, 14, 0, 0)  # 数据起始日
END_DATE = datetime(2026, 6, 8, 23, 0, 0)     # 数据结束日
PUIN = "10086"
OPENID = "demo_openid_base64_xxx"

random.seed(42)

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
    puin                 TEXT PRIMARY KEY,
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
    last_fetch_time      TEXT
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


def pick_hero() -> tuple[int, str, str]:
    """按权重随机选择英雄。"""
    hero = weighted_choice(HERO_POOL, [h[3] for h in HERO_POOL])
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


def generate_matches(num_games: int = 250) -> list[dict]:
    """生成模拟对局数据，包含明显的连续游戏轮次（session）。

    约70%的对局属于某个连续轮次（session内间隔15-90分钟），
    约30%是孤立对局（session间间隔4-72小时）。
    """
    matches = []
    current_date = BASE_DATE
    # 段位演进：从黄金4 (tier=4, lp=20) 慢慢爬到铂金2 (tier=3, lp=60)
    current_tier = 4     # WeGame: 4=黄金
    current_lp = 20
    current_rank = "III"

    ranked_games_count = 0
    game_counter = 1000000000
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
        # 在 current_date 之后随机偏移天数
        if i == 0:
            # 首局：从 BASE_DATE 开始
            day_offset = 0
        else:
            # session 之间间隔 4-72 小时
            day_offset = random.choices(
                [0, 1, 2, 3],
                weights=[30, 35, 25, 10]  # 多数在 0-2 天内
            )[0]
            # 额外加小时偏移
            extra_hours = random.randint(0, 23)
            current_date += timedelta(days=day_offset, hours=extra_hours)

        # 选择这个 session 的起始小时
        weekday = current_date.weekday()
        session_start_hour = _pick_game_hour(weekday)
        session_start = current_date.replace(
            hour=session_start_hour,
            minute=random.randint(0, 59),
            second=0, microsecond=0
        )
        # 确保不早于 current_date
        if session_start < current_date:
            session_start = current_date

        session_dt = session_start

        # ── 生成 session 内的每局对局 ──
        for j in range(session_size):
            i += 1
            game_counter += 1
            game_id = str(game_counter)

            # 决定队列类型 — session 内偏好一致（如排位session vs 大乱斗session）
            if j == 0:
                # session 首局决定主类型
                queue_roll = random.random()
                if queue_roll < 0.55:
                    session_queue_type = "ranked"
                elif queue_roll < 0.70:
                    session_queue_type = "normal"
                elif queue_roll < 0.92:
                    session_queue_type = "aram"
                else:
                    session_queue_type = "flex"

            # 在 session 类型基础上，10% 概率切换类型
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

            # 生成对局时间（session 内第1局用 session_start，后续局累加间隔）
            if j == 0:
                dt = session_dt
            else:
                # session 内间隔：游戏时长(15-42min) + 排队/结算时间(5-25min)
                session_dt += timedelta(
                    minutes=random.randint(20, 40),  # 一局游戏+排队
                    seconds=random.randint(0, 3599)
                )
                dt = session_dt

            # 推进 session 内时间
            session_dt = dt + timedelta(minutes=random.randint(15, 35))

            # ── 选择英雄 ──
            if queue_id == 450:
                hero_id = random.choice([h[0] for h in HERO_POOL[:10]])
                hero_name = next(h[1] for h in HERO_POOL if h[0] == hero_id)
                position = "Invalid"
            else:
                hero_id, hero_name, position = pick_hero()

            # ── 游戏时长 ──
            if queue_id == 450:
                duration = random.randint(900, 1800)
            else:
                duration = random.choices(
                    [15*60, 20*60, 25*60, 28*60, 30*60, 32*60, 35*60, 38*60, 42*60],
                    weights=[3, 8, 15, 20, 20, 15, 8, 3, 1]
                )[0] + random.randint(-120, 180)

            # ── 胜负 ──
            if is_ranked:
                win_prob = 0.52
            elif queue_id == 450:
                win_prob = 0.50
            else:
                win_prob = 0.53
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
                    if current_tier == 4:
                        if random.random() < 0.7:
                            current_tier = 3
                            current_lp = random.randint(5, 25)
                            current_rank = random.choice(["II", "III"])
                        else:
                            current_lp = 75 + random.randint(0, 15)
                    elif current_tier == 3:
                        if ranked_games_count > 80 and random.random() < 0.6:
                            current_tier = 2
                            current_lp = random.randint(3, 20)
                            current_rank = "IV"
                        else:
                            current_lp = 70 + random.randint(0, 20)
                    else:
                        current_lp = random.randint(70, 99)
                elif current_lp <= 0:
                    current_lp = random.randint(5, 30)
                    if current_tier == 3 and random.random() < 0.1:
                        current_tier = 4
                        current_lp = 75
                        current_rank = "I"

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
                "game_version": version, "area": 1,
            })

        # ── session 结束，推进 current_date ──
        current_date = session_dt

    # 按时间排序
    matches.sort(key=lambda m: m["_dt"])
    return matches


# ── 数据库写入 ────────────────────────────────────────────────────────────────

def create_database(matches: list[dict], db_path: str = "demo_matches.db"):
    """创建 demo SQLite 数据库。"""
    if Path(db_path).exists():
        os.remove(db_path)

    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=WAL")

    db.execute(SQL_CREATE_MATCH_SUMMARY)
    db.execute(SQL_CREATE_SUMMONER_PROFILE)
    db.execute(SQL_CREATE_CHAMPION_MASTERY)
    db.execute(SQL_CREATE_SEASON_HISTORY)
    db.execute(SQL_CREATE_CAREER_OVERVIEW)

    # ── 1. match_summary ──
    summary_cols = [
        "game_id", "game_start_time", "game_time_played", "game_queue_id",
        "queue_name", "map_id", "map_name", "champion_id", "position", "team_id",
        "win", "kills", "deaths", "assists", "kda", "game_score", "gold_earned",
        "double_kills", "triple_kills", "quadra_kills", "penta_kills",
        "was_mvp", "was_svp", "was_surrender", "was_afk",
        "most_kills", "most_assists", "most_gold", "most_damage",
        "most_taken", "most_turrets",
        "tier", "league_points", "rank", "game_version", "area",
    ]
    placeholders = ", ".join("?" * len(summary_cols))
    insert_sql = f"INSERT INTO match_summary ({', '.join(summary_cols)}) VALUES ({placeholders})"

    rows = []
    for m in matches:
        row = tuple(m.get(col, 0) if col not in ("tier", "rank", "queue_name",
                                                  "map_name", "game_start_time",
                                                  "game_version", "position")
                    else m.get(col, "") for col in summary_cols)
        rows.append(row)
    db.executemany(insert_sql, rows)
    print(f"  match_summary: {len(rows)} 行")

    # ── 2. summoner_profile ──
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
    max_kills = max(m["kills"] for m in matches)
    max_assists = max(m["assists"] for m in matches)
    max_gold = max(m["gold_earned"] for m in matches)

    # 计算最长连胜
    longest_streak = 0
    cur = 0
    for m in sorted(matches, key=lambda x: x["_dt"]):
        if m["win"]:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 找出最后段位
    last_ranked = ranked[-1] if ranked else None
    s_tier = int(last_ranked["tier"]) if last_ranked and last_ranked["tier"] else 3
    s_lp = last_ranked["league_points"] if last_ranked else 60
    s_total = len(ranked)
    s_wins = sum(1 for m in ranked if m["win"])

    # 近30天数据
    last_dt = matches[-1]["_dt"]
    thirty_days_ago = last_dt - timedelta(days=30)
    recent = [m for m in matches if m["_dt"] >= thirty_days_ago]
    r_kills = sum(m["kills"] for m in recent)
    r_deaths = sum(m["deaths"] for m in recent)
    r_assists = sum(m["assists"] for m in recent)
    r_wins = sum(1 for m in recent if m["win"])

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
        "puin": PUIN, "summoner_id": 12345678, "summoner_name": "DemoPlayer",
        "name_tag": "CN1", "level": 287, "experience": 150000,
        "icon_id": 23, "praise": 342, "discredit": 12, "top_of_canyon": 0,
        "openid": OPENID, "area": 1,
        "season_sid": 26, "season_total": s_total,
        "season_wins": s_wins, "season_losses": s_total - s_wins,
        "season_tier": s_tier, "season_win_point": s_lp,
        "season_queue": 420,
        "kill_30days": r_kills, "death_30days": r_deaths,
        "assist_30days": r_assists,
        "recent_win_times": r_wins, "recent_play_times": len(recent),
        "last_game_id": matches[-1]["game_id"],
        "recent_kda_score": round((r_kills + r_assists) / max(r_deaths, 1) * 100),
        "last_game_time": matches[-1]["game_start_time"],
        "common_champions": '["亚索", "李青", "劫"]',
        "common_positions": '["中单", "打野"]',
        "total_mvp_times": total_mvp, "total_svp_times": total_svp,
        "total_god_likes": total_penta * 3 + 15,
        "total_penta_kills": total_penta, "total_quadra_kills": total_quadra,
        "total_triple_kills": total_triple,
        "max_consecutive_wins": longest_streak,
        "highest_game_score": max(m["game_score"] for m in matches),
        "most_kills_num": max_kills, "most_assists_num": max_assists,
        "most_spree_kills_num": max_kills,
        "most_damage_num": max(m.get("most_damage", 0) * random.randint(30000, 60000) for m in matches),
        "most_damage_taken_num": random.randint(40000, 80000),
        "most_gold_earned_num": max_gold,
        "most_minions_kill_num": random.randint(250, 400),
        "most_turrets_kill_num": 6,
        "total_kills": total_kills, "total_assists": total_assists,
        "total_ward_placed": total_games * random.randint(8, 20),
        "longest_game_num": max(m["game_time_played"] for m in matches),
        "shortest_game_num": min(m["game_time_played"] for m in matches),
        "last_fetch_time": now,
    }
    placeholders = ", ".join("?" * len(profile_cols))
    db.execute(
        f"INSERT INTO summoner_profile ({', '.join(profile_cols)}) VALUES ({placeholders})",
        tuple(profile.get(col, "") for col in profile_cols)
    )
    print("  summoner_profile: 1 行")

    # ── 3. champion_mastery ──
    mastery_cols = [
        "puin", "champion_id", "total_games", "wins", "win_rate",
        "mastery_exp", "expire_day", "instance_id",
        "sid_total", "sid_wins", "sid_exp", "lanes_json", "last_fetch_time",
    ]
    for cid, tg, w, wr, exp in MASTERY_POOL:
        lanes = next((h[2] for h in HERO_POOL if h[0] == cid), "MIDDLE")
        lanes_json = f'["{POSITION_NAMES.get(lanes, lanes)}"]'
        db.execute(
            f"INSERT INTO champion_mastery ({', '.join(mastery_cols)}) "
            f"VALUES ({', '.join('?' * len(mastery_cols))})",
            (PUIN, cid, tg, w, wr, exp, -1, "", tg, w, exp // 10, lanes_json, now)
        )
    print(f"  champion_mastery: {len(MASTERY_POOL)} 行")

    # ── 4. season_history ──
    season_cols = [
        "puin", "sid", "total_games", "wins", "losses",
        "tier", "win_point", "queue",
        "team_total", "team_wins", "team_losses",
        "team_tier", "team_win_point", "team_queue", "last_fetch_time",
    ]
    # 模拟 8 个赛季的数据
    seasons_data = [
        (19, 45, 20, 25, 5, 55, 420, 10, 4, 6, 5, 45, 440),
        (20, 52, 26, 26, 4, 45, 420, 12, 6, 6, 4, 36, 440),
        (21, 60, 32, 28, 4, 65, 420, 15, 8, 7, 4, 55, 440),
        (22, 58, 30, 28, 4, 28, 420, 8, 4, 4, 4, 22, 440),
        (23, 65, 34, 31, 3, 72, 420, 18, 10, 8, 3, 60, 440),
        (24, 70, 36, 34, 3, 48, 420, 20, 11, 9, 3, 42, 440),
        (25, 72, 38, 34, 3, 35, 420, 22, 12, 10, 3, 28, 440),
        (26, s_total, s_wins, s_total - s_wins, s_tier, s_lp, 420, 15, 8, 7, 3, 30, 440),
    ]
    for sid, tg, w, l, tier, wp, q, tt, tw, tl, ttier, twp, tq in seasons_data:
        db.execute(
            f"INSERT INTO season_history ({', '.join(season_cols)}) "
            f"VALUES ({', '.join('?' * len(season_cols))})",
            (PUIN, sid, tg, w, l, tier, wp, q, tt, tw, tl, ttier, twp, tq, now)
        )
    print(f"  season_history: {len(seasons_data)} 行")

    # ── 5. career_overview ──
    career_cols = [
        "puin", "total_match_games", "total_match_wins", "total_match_losses",
        "total_aram_games", "total_aram_wins", "total_aram_losses",
        "total_rank_games", "total_rank_wins", "total_rank_losses",
        "total_teamrank_games", "total_teamrank_wins", "total_teamrank_losses",
        "total_all_games", "total_all_wins", "total_all_losses",
        "total_ai_games", "total_ai_wins", "total_clash_games",
        "last_fetch_time",
    ]
    rank_g = sum(1 for m in matches if m["game_queue_id"] == 420)
    rank_w = sum(1 for m in matches if m["game_queue_id"] == 420 and m["win"])
    match_g = sum(1 for m in matches if m["game_queue_id"] == 430)
    match_w = sum(1 for m in matches if m["game_queue_id"] == 430 and m["win"])
    aram_g = sum(1 for m in matches if m["game_queue_id"] == 450)
    aram_w = sum(1 for m in matches if m["game_queue_id"] == 450 and m["win"])
    flex_g = sum(1 for m in matches if m["game_queue_id"] == 440)
    flex_w = sum(1 for m in matches if m["game_queue_id"] == 440 and m["win"])
    total_all = total_games
    total_all_w = total_wins
    # 加上一些未记录的人机场次
    ai_g = random.randint(20, 40)
    clash_g = random.randint(5, 15)

    db.execute(
        f"INSERT INTO career_overview ({', '.join(career_cols)}) "
        f"VALUES ({', '.join('?' * len(career_cols))})",
        (PUIN, match_g, match_w, match_g - match_w,
         aram_g, aram_w, aram_g - aram_w,
         rank_g, rank_w, rank_g - rank_w,
         flex_g, flex_w, flex_g - flex_w,
         total_all, total_all_w, total_all - total_all_w,
         ai_g, ai_g, clash_g, now)
    )
    print("  career_overview: 1 行")

    db.commit()
    db.close()
    print(f"\n[OK] 数据库已创建: {db_path} ({os.path.getsize(db_path) / 1024:.1f} KB)")


# ── 主入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="生成 LOLhistory 演示数据")
    ap.add_argument("--games", type=int, default=250,
                    help="模拟对局数（默认 250）")
    ap.add_argument("--db-only", action="store_true",
                    help="仅生成数据库，不生成报告")
    ap.add_argument("--db", default="demo_matches.db",
                    help="数据库输出路径（默认: demo_matches.db）")
    ap.add_argument("--output", default="demo_report.html",
                    help="报告输出路径（默认: demo_report.html）")
    args = ap.parse_args()

    print(f"正在生成 {args.games} 场模拟对局数据...")
    matches = generate_matches(args.games)

    print(f"\n正在写入数据库...")
    create_database(matches, args.db)

    if not args.db_only:
        print(f"\n正在生成分析报告...")
        # 修改 sys.argv 来调用 _analysis.generate_report
        from lolhistory._analysis import generate_report
        path = generate_report(db_path=args.db, output_path=args.output)
        print(f"\n[OK] 演示报告已生成: {path}")
        print(f"   在浏览器中打开即可查看。")
    else:
        print(f"\n[OK] 数据库已就绪，运行以下命令生成报告：")
        print(f"   .venv/Scripts/python -m lolhistory --analyze --db {args.db} --output {args.output}")
