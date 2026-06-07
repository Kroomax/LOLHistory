"""方法3: WeGame API — Cookie 认证、对局列表与详情获取、解析。

推荐方式。服务端数据，无需运行 League 客户端。
仅使用 _data.py 中的共享常量。
"""

import json
import logging
import sys
import time
from datetime import datetime
from urllib.parse import unquote
from typing import Optional

import requests
import urllib3

from ._data import get_queue_name, get_map_name, calculate_kda, TFT_QUEUE_IDS

urllib3.disable_warnings()

logger = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────────────────────────

WEGAME_API_BASE = "https://www.wegame.com.cn"
BATTLE_LIST_PATH = "/api/v1/wegame.pallas.game.LolBattle/GetBattleList"
BATTLE_DETAIL_PATH = "/api/v1/wegame.pallas.game.LolBattle/GetBattleDetail"
SUMMONER_INFO_PATH = "/api/v1/wegame.pallas.game.LolBattle/GetSummonerInfo"
PLAYER_RECENT_STAT_PATH = "/api/v1/wegame.pallas.game.LolBattle/GetPlayerRecentStat"
CHAMPION_PATH = "/api/v1/wegame.pallas.game.LolBattle/GetChampion"
BATTLE_REPORT_PATH = "/api/v1/wegame.pallas.game.LolBattle/GetBattleReport"

WEGAME_UA = (
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/109.0.5414.120 Safari/537.36 "
    "qblink wegame.exe WeGame/6.5.2.5120 ChannelId/0 "
    "QBCore/109.0.0-HEAD.2720+g8dd4c19+chromium-109.0.5414.120 "
    "QQBrowser/9.0.2524.400"
)

REQUIRED_COOKIE_KEYS = ["puin", "pkey", "tgp_biz_ticket", "tgp_id"]


# ──────────────────────────────────────────────────────────────────────────
# WeGame API 客户端
# ──────────────────────────────────────────────────────────────────────────

class WegameApiError(Exception):
    def __init__(self, status_code: int, message: str, url: str = ""):
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"[{status_code}] {message} (URL: {url})")


class WegameApiClient:
    """WeGame LOL 对局 API 的 HTTP 客户端。通过 Cookie 认证。"""

    def __init__(self, cookies: dict[str, str], timeout: int = 15):
        self._cookies = cookies
        self._timeout = timeout
        self._openid: Optional[str] = None
        self.puin = cookies.get("puin", "")

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "User-Agent": WEGAME_UA,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json",
            "Referer": "https://www.wegame.com.cn/helper/lol/index.html",
            "trpc-caller": "wegame.pallas.web.LolBattle",
        })
        for k, v in cookies.items():
            self.session.cookies.set(k, v)

    @property
    def openid(self) -> Optional[str]:
        return self._openid

    def set_openid(self, oid: str):
        self._openid = oid

    def _post(self, path: str, body: dict, timeout: int | None = None,
              extra_headers: dict | None = None) -> dict:
        url = f"{WEGAME_API_BASE}{path}"
        t = timeout or self._timeout

        # 临时覆盖请求头（如 GetSummonerInfo 需要 trpc-caller: TftBattle）
        saved = {}
        if extra_headers:
            for k, v in extra_headers.items():
                saved[k] = self.session.headers.get(k)
                self.session.headers[k] = v

        try:
            resp = self.session.post(url, json=body, timeout=t)
            resp.raise_for_status()
            data = resp.json()
        except requests.HTTPError as e:
            sc = e.response.status_code if e.response is not None else 0
            raise WegameApiError(sc, str(e), url) from e
        except requests.ConnectionError as e:
            raise WegameApiError(0, f"连接被拒绝: {e}", url) from e
        except requests.Timeout as e:
            raise WegameApiError(0, f"请求超时 ({t}s): {e}", url) from e
        finally:
            if extra_headers:
                for k, v in saved.items():
                    if v is None:
                        del self.session.headers[k]
                    else:
                        self.session.headers[k] = v

        result = data.get("result", {})
        if result.get("error_code", 0) != 0:
            raise WegameApiError(
                result.get("error_code", -1),
                result.get("error_message", "未知错误"),
                url,
            )
        return data

    def get_battle_list(self, area: int = 1, offset: int = 0,
                        count: int = 10, filter_str: str = "") -> dict:
        """POST GetBattleList — 分页获取对局摘要列表。"""
        return self._post(BATTLE_LIST_PATH, {
            "account_type": 1,
            "area": area,
            "id": self.puin,
            "count": count,
            "filter": filter_str,
            "offset": offset,
            "from_src": "lol_helper",
        })

    def get_battle_detail(self, game_id: str, area: int = 1,
                          openid: str | None = None) -> dict:
        """POST GetBattleDetail — 获取单局 10 人完整对局数据。

        首次调用时如果未提供 openid 则自动探测。
        """
        uid = openid or self._openid
        if not uid:
            uid = self._discover_openid(game_id, area)

        data = self._post(BATTLE_DETAIL_PATH, {
            "account_type": 2,
            "area": area,
            "id": uid,
            "game_id": str(game_id),
            "from_src": "lol_helper",
        })

        resp_openid = data.get("openid", "")
        if resp_openid and not self._openid:
            self._openid = resp_openid
            logger.info("已探测到 openid: %s...", resp_openid[:20])
        return data

    def _discover_openid(self, game_id: str, area: int) -> str:
        """尝试通过 account_type=1 回退方式探测 openid。"""
        try:
            data = self._post(BATTLE_DETAIL_PATH, {
                "account_type": 1, "area": area,
                "id": self.puin, "game_id": str(game_id),
                "from_src": "lol_helper",
            })
            oid = data.get("openid", "")
            if oid:
                self._openid = oid
                logger.info("通过 account_type=1 探测到 openid: %s...", oid[:20])
                return oid
        except WegameApiError:
            pass

        raise WegameApiError(0,
            "无法探测 openid。请通过 --openid 显式提供。"
            "可在 WeGame 助手页面的网络请求中找到 "
            "（GetBattleDetail POST 请求体 → 'id' 字段）。"
        )

    def get_summoner_info(self, area: int = 1) -> dict:
        """POST GetSummonerInfo — 获取召唤师基本信息、赛季段位与 openid。

        注意：此接口的 trpc-caller 头为 wegame.pallas.web.TftBattle，
        与其他接口不同。
        """
        return self._post(SUMMONER_INFO_PATH, {
            "account_type": 1,
            "area": area,
            "id": self.puin,
            "from_src": "lol_helper",
        }, extra_headers={"trpc-caller": "wegame.pallas.web.TftBattle"})

    def get_player_recent_stat(self, openid: str, area: int = 1) -> dict:
        """POST GetPlayerRecentStat — 获取近30天数据与生涯总统计。

        需要 openid（可从 GetSummonerInfo 或 --openid 获取）。
        使用 account_type=2。
        """
        return self._post(PLAYER_RECENT_STAT_PATH, {
            "account_type": 2,
            "area": area,
            "id": openid,
            "from_src": "lol_helper",
        })

    def get_champions(self, openid: str, area: int = 1) -> dict:
        """POST GetChampion — 获取全部 172 个英雄的熟练度数据。

        需要 openid（可从 GetSummonerInfo 或 --openid 获取）。
        使用 account_type=2, flag=2。
        """
        return self._post(CHAMPION_PATH, {
            "account_type": 2,
            "area": area,
            "id": openid,
            "flag": 2,
            "from_src": "lol_helper",
        })

    def get_battle_report(self, area: int = 1) -> dict:
        """POST GetBattleReport — 获取全模式战斗总览统计与赛季段位历史。

        使用 account_type=1, id=puin。
        sids=[255] 表示获取所有赛季数据。
        """
        return self._post(BATTLE_REPORT_PATH, {
            "account_type": 1,
            "area": area,
            "id": self.puin,
            "sids": [255],
            "from_src": "lol_helper",
        })

    def test_connection(self) -> bool:
        try:
            data = self.get_battle_list(offset=0, count=1)
            return len(data.get("battles", [])) >= 0
        except WegameApiError as e:
            logger.error("连接测试失败: %s", e)
            return False

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


# ──────────────────────────────────────────────────────────────────────────
# 数据解析
# ──────────────────────────────────────────────────────────────────────────

def _parse_game_level(gl_str: str) -> dict:
    """解析嵌套的 game_level JSON 字符串。"""
    try:
        return json.loads(gl_str) if gl_str else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _decode_name(url_encoded: str) -> str:
    if not url_encoded:
        return "Unknown"
    try:
        return unquote(url_encoded)
    except Exception:
        return url_encoded


def _split_name_tag(full_name: str) -> tuple[str, str]:
    """将 '召唤师名#tag' 拆分为 (名称, 标签)。"""
    if not full_name:
        return ("", "")
    if "#" in full_name:
        parts = full_name.rsplit("#", 1)
        return (parts[0], parts[1])
    return (full_name, "")


def parse_summoner_info(data: dict) -> dict:
    """解析 GetSummonerInfo 响应为扁平字典（中文键）。

    包含召唤师基本信息、赛季段位数据和 openid。
    openid 可缓存用于后续 GetBattleDetail / GetPlayerRecentStat 调用。
    """
    s = data.get("summoner", {})
    season = s.get("season", {})

    raw_name = s.get("name", "")
    name_part, tag_part = _split_name_tag(raw_name)

    return {
        "召唤师ID": s.get("id", 0),
        "召唤师名称": name_part,
        "标签": tag_part,
        "原始名称": raw_name,
        "等级": s.get("level", 0),
        "经验值": s.get("experience", 0),
        "头像ID": s.get("icon_id", 0),
        "点赞": s.get("praise", 0),
        "点踩": s.get("discredit", 0),
        "峡谷之巅": s.get("top_of_canyon", False),
        "openid": s.get("openid", ""),
        "大区": s.get("area", 0),
        # 赛季数据
        "赛季ID": season.get("sid", 0),
        "赛季总场次": season.get("total", 0),
        "赛季胜场": season.get("wins", 0),
        "赛季负场": season.get("losses", 0),
        "段位": season.get("tier", 0),
        "胜点": season.get("win_point", 0),
        "单双排": season.get("queue", 0),
        # 组排数据
        "组排总场": season.get("team_total", 0),
        "组排胜场": season.get("team_wins", 0),
        "组排负场": season.get("team_losses", 0),
        "组排段位": season.get("team_tier", 255),
        "组排胜点": season.get("team_win_point", 0),
    }


def parse_player_recent_stat(data: dict) -> dict:
    """解析 GetPlayerRecentStat 响应为扁平字典（中文键）。

    合并 recent_state（近30天）和 game_career（生涯总计）两个子对象。
    常用英雄/位置以 JSON 字符串形式存储。
    """
    rs = data.get("recent_state", {})
    gc = data.get("game_career", {})

    common_champs = rs.get("common_use_champions", [])
    common_pos = rs.get("common_position", [])

    return {
        # 近30天统计
        "近30天击杀": rs.get("kill_30days", 0),
        "近30天死亡": rs.get("death_30days", 0),
        "近30天助攻": rs.get("assist_30days", 0),
        "近期胜场": rs.get("win_times", 0),
        "近期场次": rs.get("play_times", 0),
        "最近对局ID": str(rs.get("last_game_id", "")),
        "近期KDA分数": rs.get("kda", 0),
        "最后对局时间": rs.get("last_game_time", ""),
        "常用英雄JSON": json.dumps(common_champs, ensure_ascii=False) if common_champs else "[]",
        "常用位置JSON": json.dumps(common_pos, ensure_ascii=False) if common_pos else "[]",
        # 生涯总计
        "生涯MVP": gc.get("total_mvp_times", 0),
        "生涯SVP": gc.get("total_svp_times", 0),
        "生涯超神": gc.get("total_god_likes", 0),
        "生涯五杀": gc.get("total_penta_kills", 0),
        "生涯四杀": gc.get("total_quadra_kills", 0),
        "生涯三杀": gc.get("total_triple_kills", 0),
        "最长连胜": gc.get("max_consecutive_wins", 0),
        "最高评分": gc.get("highest_game_score", 0),
        "单局最高击杀": gc.get("most_kills_num", 0),
        "单局最高助攻": gc.get("most_assists_num", 0),
        "单局最高连杀": gc.get("most_spree_kills_num", 0),
        "单局最高伤害": gc.get("most_damage_num", 0),
        "单局最高承伤": gc.get("most_damage_taken_num", 0),
        "单局最高经济": gc.get("most_gold_earned_num", 0),
        "单局最高补刀": gc.get("most_minions_kill_num", 0),
        "单局最高推塔": gc.get("most_turrets_kill_num", 0),
        "生涯总击杀": gc.get("total_kills", 0),
        "生涯总助攻": gc.get("total_assists", 0),
        "生涯总插眼": gc.get("total_ward_placed", 0),
        "最长对局秒": gc.get("longest_game_num", 0),
        "最短对局秒": gc.get("shortest_game_num", 0),
    }


def parse_champions(data: dict) -> list[dict]:
    """解析 GetChampion 响应为英雄熟练度列表（每个英雄一个扁平字典，中文键）。

    返回列表，每项包含 champion_id, 总场次, 胜场, 胜率,
    常用分路, 赛季数据等。
    """
    champion_list = data.get("champion_list", [])
    results = []
    for c in champion_list:
        total = c.get("total", 0) or 0
        wins = c.get("wins", 0) or 0
        lanes = c.get("lanes", [])
        results.append({
            "英雄ID": c.get("champion_id", 0),
            "总场次": total,
            "胜场": wins,
            "胜率": round(wins / max(total, 1) * 100, 1),
            "熟练度": c.get("used_exp", 0) or 0,
            "到期天数": c.get("expire_day", 0) or 0,
            "皮肤实例": c.get("instance_id", ""),
            "赛季总场": c.get("sid_total", 0) or 0,
            "赛季胜场": c.get("sid_wins", 0) or 0,
            "赛季经验": c.get("sid_exp", 0) or 0,
            "常用分路JSON": json.dumps(lanes, ensure_ascii=False) if lanes else "[]",
        })
    return results


def parse_battle_report(data: dict) -> dict:
    """解析 GetBattleReport 响应为结构化数据。

    返回字典包含:
      - battle_count: 扁平化的全模式统计（中文键）
      - season_list: 赛季历史列表（每项已转换为中文键）
    """
    bc = data.get("battle_count", {})
    season_list_raw = data.get("season_list", [])

    # 扁平化 battle_count
    battle_count = {
        "匹配总场": bc.get("total_match_games", 0) or 0,
        "匹配胜场": bc.get("total_match_wins", 0) or 0,
        "匹配负场": bc.get("total_match_losts", 0) or 0,
        "大乱斗总场": bc.get("total_arm_games", 0) or 0,
        "大乱斗胜场": bc.get("total_arm_wins", 0) or 0,
        "大乱斗负场": bc.get("total_arm_losts", 0) or 0,
        "单双排总场": bc.get("total_rank_games", 0) or 0,
        "单双排胜场": bc.get("total_rank_wins", 0) or 0,
        "单双排负场": bc.get("total_rank_losts", 0) or 0,
        "组排总场": bc.get("total_teamrank_games", 0) or 0,
        "组排胜场": bc.get("total_teamrank_wins", 0) or 0,
        "组排负场": bc.get("total_teamrank_losts", 0) or 0,
        "全部总场": bc.get("total_games", 0) or 0,
        "全部胜场": bc.get("total_wins", 0) or 0,
        "全部负场": bc.get("total_losts", 0) or 0,
        "人机总场": bc.get("total_ai_games", 0) or 0,
        "人机胜场": bc.get("total_ai_wins", 0) or 0,
        "clash总场": bc.get("total_clash_games", 0) or 0,
    }

    # 转换赛季列表
    season_list = []
    for s in season_list_raw:
        season_list.append({
            "赛季ID": s.get("sid", 0),
            "总场次": s.get("total", 0) or 0,
            "胜场": s.get("wins", 0) or 0,
            "负场": s.get("losses", 0) or 0,
            "段位": s.get("tier", 255),
            "胜点": s.get("win_point", 0) or 0,
            "队列": s.get("queue", 0) or 0,
            "组排总场": s.get("team_total", 0) or 0,
            "组排胜场": s.get("team_wins", 0) or 0,
            "组排负场": s.get("team_losses", 0) or 0,
            "组排段位": s.get("team_tier", 255),
            "组排胜点": s.get("team_win_point", 0) or 0,
            "组排队列": s.get("team_queue", 0) or 0,
        })

    return {
        "battle_count": battle_count,
        "season_list": season_list,
    }


def parse_battle_summary(battle: dict) -> dict:
    """将 GetBattleList 返回的原始对局数据解析为扁平字典（中文键）。"""
    game_start_epoch = int(battle.get("game_start_time", "0")) / 1000.0
    game_duration = battle.get("game_time_played", 0) or 0
    game_level = _parse_game_level(battle.get("game_level", "{}"))

    win_str = battle.get("win", "Fail")
    kills = battle.get("kills", 0) or 0
    deaths = battle.get("deaths", 0) or 0
    assists = battle.get("assists", 0) or 0
    queue_id = battle.get("game_queue_id", 0) or 0
    map_id = battle.get("map_id", 0) or 0

    dt = datetime.fromtimestamp(game_start_epoch) if game_start_epoch > 0 else None

    return {
        "对局ID": str(battle.get("game_id", "")),
        "game_start_time": game_start_epoch,
        "日期": dt.strftime("%Y-%m-%d") if dt else "",
        "时间": dt.strftime("%H:%M:%S") if dt else "",
        "游戏时长(秒)": game_duration,
        "游戏时长(分钟)": round(game_duration / 60, 1) if game_duration else 0,
        "队列ID": queue_id,
        "队列类型": get_queue_name(queue_id),
        "地图ID": map_id,
        "地图": get_map_name(map_id),
        "英雄ID": battle.get("champion_id", 0) or 0,
        "位置": battle.get("position", ""),
        "队伍ID": int(battle.get("team_id", "0") or 0),
        "胜利": win_str == "Win",
        "胜负": win_str,
        "击杀": kills,
        "死亡": deaths,
        "助攻": assists,
        "KDA": calculate_kda(kills, deaths, assists),
        "评分": battle.get("game_score", 0) or 0,
        "金币": battle.get("gold_earned", 0) or 0,
        "双杀": battle.get("double_kills", 0) or 0,
        "三杀": battle.get("triple_kills", 0) or 0,
        "四杀": battle.get("quadra_kills", 0) or 0,
        "五杀": battle.get("penta_kills", 0) or 0,
        "MVP": bool(battle.get("was_mvp", 0)),
        "SVP": bool(battle.get("was_svp", 0)),
        "击杀最多": bool(battle.get("most_kills", 0)),
        "助攻最多": bool(battle.get("most_assists", 0)),
        "金币最多": bool(battle.get("most_gold_earned", 0)),
        "伤害最高": bool(battle.get("most_damage_dealt_to_champions", 0)),
        "承受伤害最高": bool(battle.get("most_total_damage_taken", 0)),
        "推塔最多": bool(battle.get("most_turrets_killed", 0)),
        "投降": bool(battle.get("was_surrender", 0)),
        "挂机": bool(battle.get("was_afk", 0)),
        "段位": game_level.get("tier", ""),
        "胜点": game_level.get("league_points", ""),
        "段位等级": game_level.get("rank", ""),
        "对局类型": battle.get("battle_type", 0) or 0,
        "组队人数": battle.get("team_made_size", 0) or 0,
        "游戏版本": battle.get("game_server_version", ""),
    }


def parse_battle_detail(detail_data: dict, my_openid: str = "") -> dict:
    """解析 GetBattleDetail 响应为结构化数据。

    返回字典，包含: game_id, game_start_time, game_time_played,
    map_id, game_queue_id, game_mode, game_type, game_server_version,
    was_early_surrender, teams, my_player, all_players。
    """
    bd = detail_data.get("battle_detail", detail_data)

    all_players = bd.get("player_details", [])
    my_player = None
    for p in all_players:
        if my_openid and p.get("openid", "") == my_openid:
            my_player = p
            break
    if not my_player and all_players:
        my_player = all_players[0]

    return {
        "game_id": bd.get("game_id", ""),
        "area_id": bd.get("area_id", ""),
        "game_start_time": int(bd.get("game_start_time", "0")) / 1000.0,
        "game_time_played": bd.get("game_time_played", 0),
        "map_id": bd.get("map_id", 0),
        "game_queue_id": bd.get("game_queue_id", 0),
        "game_mode": bd.get("game_mode", ""),
        "game_type": bd.get("game_type", ""),
        "game_server_version": bd.get("game_server_version", ""),
        "was_early_surrender": bd.get("was_early_surrender", 0),
        "teams": bd.get("team_details", []),
        "my_player": my_player,
        "all_players": all_players,
    }


# ──────────────────────────────────────────────────────────────────────────
# 对局获取函数
# ──────────────────────────────────────────────────────────────────────────

def fetch_battle_list(client: WegameApiClient, area: int = 1,
                      max_games: int = 50000, count_per_page: int = 10,
                      skip_tft: bool = True, delay_ms: int = 200) -> list[dict]:
    """通过 GetBattleList 分页获取全部可用对局历史。

    返回原始对局字典列表（按时间倒序，最新在前）。
    """
    all_battles = []
    seen_ids = set()
    offset = 0
    empty_streak = 0

    while len(all_battles) < max_games:
        try:
            data = client.get_battle_list(
                area=area, offset=offset, count=count_per_page)
        except WegameApiError as e:
            logger.error("API 错误 (offset %d): %s", offset, e)
            if e.status_code in (401, 403) or e.status_code >= 8000000:
                break
            time.sleep(1.0)
            continue

        battles = data.get("battles", [])
        if not battles:
            empty_streak += 1
            if empty_streak >= 2:
                logger.info("offset %d 处无更多对局", offset)
                break
            offset += count_per_page
            continue

        empty_streak = 0
        new_count = 0
        for b in battles:
            gid = str(b.get("game_id", ""))
            if skip_tft and (b.get("game_queue_id", 0) or 0) in TFT_QUEUE_IDS:
                continue
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                all_battles.append(b)
                new_count += 1

        sys.stderr.write(f"\r  已获取: {len(all_battles)} 场对局...")
        sys.stderr.flush()

        if len(all_battles) >= max_games:
            break
        if new_count < count_per_page / 2:
            logger.info("稀疏页面 — 可能已到达数据末尾")
            break

        offset += count_per_page
        if delay_ms:
            time.sleep(delay_ms / 1000.0)

    sys.stderr.write("\n")
    return all_battles


def fetch_battle_details(client: WegameApiClient, game_ids: list[str],
                          area: int = 1, delay_ms: int = 200) -> dict[str, dict]:
    """通过 GetBattleDetail 批量获取对局详情。

    返回字典，键为 game_id，值为解析后的详情字典。
    """
    details = {}
    total = len(game_ids)
    for i, gid in enumerate(game_ids, 1):
        try:
            data = client.get_battle_detail(gid, area=area)
            details[str(gid)] = parse_battle_detail(data, client.openid or "")
        except WegameApiError as e:
            logger.warning("详情获取失败 %s: %s", gid, e)
            details[str(gid)] = {"error": str(e), "game_id": str(gid)}
        except Exception as e:
            logger.warning("意外错误 %s: %s", gid, e)
            details[str(gid)] = {"error": str(e), "game_id": str(gid)}

        sys.stderr.write(f"\r  获取详情: {i}/{total}...")
        sys.stderr.flush()
        if delay_ms:
            time.sleep(delay_ms / 1000.0)

    sys.stderr.write("\n")
    return details


# ──────────────────────────────────────────────────────────────────────────
# Cookie 辅助函数
# ──────────────────────────────────────────────────────────────────────────

def load_cookies(filepath: str) -> dict[str, str]:
    """从 JSON 文件加载 Cookie。

    接受两种格式: {"puin": "...", ...} 或 [{name, value}, ...]。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "puin" in data:
        return data
    if isinstance(data, list):
        return {item.get("name", ""): item.get("value", "")
                for item in data if item.get("name")}

    raise ValueError("无法解析 Cookie 文件。期望包含 'puin' 键的 JSON 对象。")


def validate_cookies(cookies: dict[str, str]) -> list[str]:
    """返回缺失的必需 Cookie 键列表。"""
    return [k for k in REQUIRED_COOKIE_KEYS if k not in cookies or not cookies[k]]


def merge_cookies(base: dict, overrides: dict) -> dict[str, str]:
    """合并多个 Cookie 来源并为可选键设置默认值。"""
    cookies = dict(base)
    cookies.update({k: v for k, v in overrides.items() if v})
    defaults = {"tgp_ticket": "", "tgp_user_type": "0", "tgp_env": "online",
                "netbar_enabled": "0"}
    for k, v in defaults.items():
        cookies.setdefault(k, v)
    return cookies
