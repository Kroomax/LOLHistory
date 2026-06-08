"""方法1+2: LCU API — lockfile 发现、对局获取、解析、导出。

与 _wegame.py 完全独立。仅使用 _data.py 中的共享常量。
"""

import base64
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ._data import get_queue_name, get_map_name, calculate_kda, format_duration, TFT_QUEUE_IDS

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Lockfile 发现
# ──────────────────────────────────────────────────────────────────────────

class LockfileNotFoundError(Exception):
    """未找到有效 lockfile 时抛出。"""


def _read_lockfile(filepath: str) -> dict | None:
    """解析 lockfile，返回 {process_name, pid, port, password, protocol} 或 None。"""
    try:
        p = Path(filepath)
        if not p.exists():
            return None
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return None
        parts = content.split(":")
        if len(parts) != 5:
            return None
        return {
            "process_name": parts[0],
            "pid": int(parts[1]),
            "port": int(parts[2]),
            "password": parts[3],
            "protocol": parts[4],
        }
    except (OSError, ValueError, IndexError):
        return None


def _get_default_lockfile_paths() -> list[str]:
    """返回需要检查的已知 lockfile 路径列表。"""
    paths = []
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        paths.append(os.path.join(localappdata, "Riot Games", "Riot Client", "Config", "lockfile"))
    for drive in ("C:", "D:", "E:", "F:", "G:"):
        paths.append(os.path.join(drive, os.sep, "Riot Games", "League of Legends", "lockfile"))
        paths.append(os.path.join(drive, os.sep, "英雄联盟", "lockfile"))
        paths.append(os.path.join(drive, os.sep, "Program Files", "英雄联盟", "lockfile"))
        paths.append(os.path.join(drive, os.sep, "腾讯游戏", "英雄联盟", "lockfile"))
    return paths


def _search_game_dir(game_dir: str) -> dict | None:
    """在游戏安装目录下搜索 lockfile。"""
    for sub in ("", "Game", "TCLS", "LeagueClient"):
        result = _read_lockfile(os.path.join(game_dir, sub, "lockfile"))
        if result:
            return result
    return None


def _scan_process_cmdline() -> dict | None:
    """从 LeagueClientUx.exe 进程命令行中提取 LCU 端口与令牌。"""
    output = ""
    try:
        r = subprocess.run(
            ["wmic", "PROCESS", "WHERE", "name='LeagueClientUx.exe'",
             "GET", "commandline", "/FORMAT:csv"],
            capture_output=True, text=True, timeout=10,
        )
        output = r.stdout or ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    if not output:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\" | "
                 "Select-Object -ExpandProperty CommandLine"],
                capture_output=True, text=True, timeout=10,
            )
            output = r.stdout or ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    port_match = re.search(r'--app-port=(\d+)', output)
    token_match = re.search(r'--remoting-auth-token=([\w\-]+)', output)
    if port_match and token_match:
        return {
            "process_name": "LeagueClient",
            "pid": 0,
            "port": int(port_match.group(1)),
            "password": token_match.group(1),
            "protocol": "https",
        }
    return None


def discover_lockfile(explicit_path: str | None = None,
                      game_dir: str | None = None) -> dict:
    """发现 League 客户端 lockfile。返回包含 port、password、protocol 的字典。

    搜索顺序：显式路径 → 游戏目录 → 已知路径 → 进程命令行扫描。
    所有策略均失败时抛出 LockfileNotFoundError。
    """
    if explicit_path:
        result = _read_lockfile(explicit_path)
        if result:
            return result
        raise LockfileNotFoundError(f"未找到 lockfile: {explicit_path}")

    if game_dir:
        result = _search_game_dir(game_dir)
        if result:
            return result
        raise LockfileNotFoundError(f"在游戏目录中未找到 lockfile: {game_dir}")

    for path in _get_default_lockfile_paths():
        result = _read_lockfile(path)
        if result:
            return result

    result = _scan_process_cmdline()
    if result:
        return result

    raise LockfileNotFoundError(
        "未找到 lockfile。请确认 LeagueClientUx.exe 正在运行。\n"
        "使用 --lockfile PATH 或 --game-dir PATH 手动指定路径。"
    )


# ──────────────────────────────────────────────────────────────────────────
# LCU API 客户端
# ──────────────────────────────────────────────────────────────────────────

class LCUApiError(Exception):
    def __init__(self, status_code: int, message: str, url: str = ""):
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"[{status_code}] {message} (URL: {url})")


class LCUApiClient:
    """League Client API 的认证 HTTP 客户端。"""

    def __init__(self, lockfile: dict, timeout: int = 15):
        self.base_url = f"https://127.0.0.1:{lockfile['port']}"
        credentials = f"riot:{lockfile['password']}"
        encoded = base64.b64encode(credentials.encode()).decode()

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        retry = Retry(total=3, backoff_factor=0.5,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._timeout = timeout

    def _get(self, path: str, **kw) -> dict:
        url = f"{self.base_url}{path}"
        t = kw.pop("timeout", self._timeout)
        try:
            resp = self.session.request("GET", url, timeout=t, **kw)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            sc = e.response.status_code if e.response is not None else 0
            raise LCUApiError(sc, str(e), url) from e
        except requests.ConnectionError as e:
            raise LCUApiError(0, f"连接被拒绝: {e}", url) from e
        except requests.Timeout as e:
            raise LCUApiError(0, f"请求超时: {e}", url) from e

    def test_connection(self) -> bool:
        try:
            self._get("/lol-summoner/v1/current-summoner")
            return True
        except Exception:
            return False

    def get_summoner(self) -> dict:
        """GET /lol-summoner/v1/current-summoner → 扁平化字典。"""
        data = self._get("/lol-summoner/v1/current-summoner")
        return {
            "puuid": data.get("puuid", ""),
            "account_id": data.get("accountId", 0),
            "summoner_id": data.get("summonerId", 0),
            "display_name": data.get("displayName", ""),
            "game_name": data.get("gameName", ""),
            "tag_line": data.get("tagLine", ""),
            "internal_name": data.get("internalName", ""),
            "summoner_level": data.get("summonerLevel", 0),
            "profile_icon_id": data.get("profileIconId", 0),
        }

    def get_matches(self, puuid: str, beg: int = 0, end: int = 100) -> dict:
        """GET /lol-match-history/v1/products/lol/{puuid}/matches"""
        return self._get(
            f"/lol-match-history/v1/products/lol/{puuid}/matches"
            f"?begIndex={beg}&endIndex={end}"
        )

    def get_match_detail(self, game_id: int) -> dict:
        """GET /lol-match-history/v1/games/{gameId}"""
        return self._get(f"/lol-match-history/v1/games/{game_id}")

    def get_champion_data(self) -> dict[int, str]:
        """GET /lol-game-data/assets/v1/champion-summary.json → {id: 名称}。"""
        try:
            data = self._get("/lol-game-data/assets/v1/champion-summary.json")
            champions = {}
            items = data if isinstance(data, list) else data.get("champions", [])
            for c in items:
                if isinstance(c, dict) and c.get("id") and c.get("name"):
                    champions[int(c["id"])] = c["name"]
            return champions
        except Exception:
            logger.warning("加载英雄数据失败，将使用 ID")
            return {}

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


# ──────────────────────────────────────────────────────────────────────────
# 对局获取与解析
# ──────────────────────────────────────────────────────────────────────────

def _extract_games(response: dict) -> list[dict]:
    """统一处理 LCU API 返回的两种 games 格式。"""
    if not response or not isinstance(response, dict):
        return []
    container = response.get("games", response)
    if isinstance(container, list):
        return container
    if isinstance(container, dict):
        return container.get("games", [])
    return []


def _is_tft(queue_id: int, game_mode: str = "", game_type: str = "") -> bool:
    if queue_id in TFT_QUEUE_IDS:
        return True
    if game_mode and "TFT" in game_mode.upper():
        return True
    return False


def fetch_matches(api: LCUApiClient, puuid: str,
                  max_games: int = 5000, skip_tft: bool = True,
                  delay_ms: int = 300) -> list[dict]:
    """分页获取 LCU 对局历史。返回原始对局字典列表。"""
    all_games = []
    seen_ids = set()
    beg = 0
    page_size = 100

    while len(all_games) < max_games:
        try:
            resp = api.get_matches(puuid, beg, beg + page_size)
        except LCUApiError as e:
            logger.error("API 错误 (索引 %d): %s", beg, e)
            if e.status_code in (404, 403):
                break
            time.sleep(1.0)
            continue

        games = _extract_games(resp)
        if not games:
            break

        if skip_tft:
            games = [g for g in games
                     if not _is_tft(g.get("queueId", 0),
                                    g.get("gameMode", ""),
                                    g.get("gameType", ""))]

        new_count = 0
        for g in games:
            gid = g.get("gameId", 0)
            if gid and gid not in seen_ids:
                seen_ids.add(gid)
                all_games.append(g)
                new_count += 1

        if new_count == 0:
            break  # LCU 分页已耗尽（返回了同一页）

        sys.stderr.write(f"\r  已获取: {len(all_games)} 场对局...")
        sys.stderr.flush()

        if len(games) < page_size:
            break

        beg += page_size
        if delay_ms:
            time.sleep(delay_ms / 1000.0)

    sys.stderr.write("\n")
    return all_games


def _find_participant(match: dict, puuid: str) -> dict | None:
    """在对局数据中按 PUUID 查找本局中的玩家条目。"""
    # 尝试 participantIdentities（旧格式）
    for ident in match.get("participantIdentities", []):
        player = ident.get("player", {})
        if player.get("puuid", "") == puuid:
            pid = ident.get("participantId", 0)
            merged = dict(ident)
            for p in match.get("participants", []):
                if p.get("participantId") == pid:
                    merged.update(p)
                    break
            for key in ("summonerName", "championId", "spell1Id",
                        "spell2Id", "teamId", "teamPosition"):
                merged.setdefault(key, player.get(key, ""))
            return merged

    # 尝试带嵌入式 puuid 的 participants
    for p in match.get("participants", []):
        if p.get("puuid", "") == puuid:
            p.setdefault("summonerName", "")
            return p
    return None


def parse_match_summary(match: dict, puuid: str, champion_map: dict[int, str]) -> dict | None:
    """将原始 LCU 对局字典解析为指定 puuid 的扁平摘要字典。"""
    player = _find_participant(match, puuid)
    if not player:
        return None

    participant_id = player.get("participantId", 0)
    game_id = match.get("gameId", 0)
    game_creation_epoch = match.get("gameCreation", 0)
    game_duration = match.get("gameDuration", 0)
    queue_id = match.get("queueId", 0) or 0
    map_id = match.get("mapId", 0) or 0
    champion_id = player.get("championId", 0) or 0

    # 查找统计数据
    stats = {}
    for p in match.get("participants", []):
        if p.get("participantId") == participant_id:
            stats = p.get("stats", p)
            break

    kills = stats.get("kills", 0) or 0
    deaths = stats.get("deaths", 0) or 0
    assists = stats.get("assists", 0) or 0

    # 解析位置
    team_position = (player.get("teamPosition") or "").upper()
    if not team_position:
        tl = player.get("timeline", {})
        lane = (tl.get("lane", "") or "").upper()
        role = (tl.get("role", "") or "").upper()
        team_position = lane if lane and lane != "NONE" else role

    # 解析召唤师名称
    summoner_name = player.get("summonerName", "") or ""
    if not summoner_name:
        gn = player.get("player", {}).get("gameName", "") or ""
        tl = player.get("player", {}).get("tagLine", "") or ""
        summoner_name = f"{gn}#{tl}" if gn else "Unknown"

    win = bool(stats.get("win", False))
    win_str = "Win" if win else "Fail"

    dt = datetime.fromtimestamp(game_creation_epoch / 1000.0) if game_creation_epoch else None

    total_minions = stats.get("totalMinionsKilled", 0) or 0
    neutral_minions = stats.get("neutralMinionsKilled", 0) or 0

    items = [stats.get(f"item{i}", 0) or 0 for i in range(7)]

    return {
        "对局ID": str(game_id),
        "game_start_time": game_creation_epoch / 1000.0,
        "日期": dt.strftime("%Y-%m-%d") if dt else "",
        "时间": dt.strftime("%H:%M:%S") if dt else "",
        "游戏时长(秒)": game_duration,
        "游戏时长(分钟)": round(game_duration / 60, 1) if game_duration else 0,
        "队列ID": queue_id,
        "队列类型": get_queue_name(queue_id),
        "地图ID": map_id,
        "地图": get_map_name(map_id),
        "英雄ID": champion_id,
        "英雄名称": champion_map.get(champion_id, f"Champ_{champion_id}"),
        "位置": team_position,
        "队伍ID": player.get("teamId", 0) or 0,
        "胜利": win,
        "胜负": win_str,
        "击杀": kills,
        "死亡": deaths,
        "助攻": assists,
        "KDA": calculate_kda(kills, deaths, assists),
        "评分": stats.get("gameScore", 0) or 0,
        "金币": stats.get("goldEarned", 0) or 0,
        "双杀": stats.get("doubleKills", 0) or 0,
        "三杀": stats.get("tripleKills", 0) or 0,
        "四杀": stats.get("quadraKills", 0) or 0,
        "五杀": stats.get("pentaKills", 0) or 0,
        "MVP": False,
        "SVP": False,
        "投降": False,
        "挂机": False,
        "击杀最多": False,
        "助攻最多": False,
        "金币最多": False,
        "伤害最高": False,
        "承受伤害最高": False,
        "推塔最多": False,
        "段位": "",
        "胜点": "",
        "段位等级": "",
        "对局类型": 0,
        "组队人数": 0,
        "游戏版本": match.get("gameVersion", ""),
        # LCU 特有额外字段（用于 CSV 导出）
        "国服特有_伤害": stats.get("totalDamageDealtToChampions", 0) or 0,
        "国服特有_承伤": stats.get("totalDamageTaken", 0) or 0,
        "国服特有_总伤": stats.get("totalDamageDealt", 0) or 0,
        "国服特有_治疗": stats.get("totalHeal", 0) or 0,
        "国服特有_补刀": total_minions + neutral_minions,
        "国服特有_视野": stats.get("visionScore", 0) or 0,
        "国服特有_装备0": items[0], "国服特有_装备1": items[1],
        "国服特有_装备2": items[2], "国服特有_装备3": items[3],
        "国服特有_装备4": items[4], "国服特有_装备5": items[5],
        "国服特有_装备6": items[6],
        "国服特有_召唤师技能1": player.get("spell1Id", 0) or 0,
        "国服特有_召唤师技能2": player.get("spell2Id", 0) or 0,
        "国服特有_召唤师": summoner_name,
    }
