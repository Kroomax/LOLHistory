"""lolhistory 入口点 — 英雄联盟对局历史导出工具。

用法:
    # 首先获取 Cookie（从 Fiddler/Charles 抓包导出文件中提取）
    python -m lolhistory --extract-cookies
    python -m lolhistory --extract-cookies ./wegame-api-export

    # 方法3（默认，推荐）: WeGame API
    python -m lolhistory --cookies cookies.json
    python -m lolhistory --cookies cookies.json -n 500 --detailed
    python -m lolhistory --cookies cookies.json --detail-game GAME_ID

    # 方法1+2: LCU API（需要运行 League 客户端）
    python -m lolhistory --method lcu
    python -m lolhistory --method lcu -n 200 -f csv
    python -m lolhistory --method lcu --lockfile PATH
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from ._data import get_queue_name, sanitize_filename

logger = logging.getLogger("lolhistory")

# ── 国服 403 反作弊拦截提示横幅 ──────────────────────────────────────────

CN_403_BANNER = """
╔══════════════════════════════════════════════════════════════════════╗
║  访问被拒绝 — 国服反作弊拦截 (403)                                  ║
╠══════════════════════════════════════════════════════════════════════╣
║  解决方法:                                                          ║
║  A) 将 python.exe 重命名为 RiotGamesApi.exe（推荐）                 ║
║     copy .venv\\Scripts\\python.exe .venv\\Scripts\\RiotGamesApi.exe   ║
║     .venv\\Scripts\\RiotGamesApi.exe -m lolhistory --method lcu        ║
║  B) 从游戏目录运行: --game-dir "D:\\\\英雄联盟"                       ║
║  C) 编辑 TCLS/config/dirserver.xml 切测试服，登录后再改回            ║
╚══════════════════════════════════════════════════════════════════════╝
"""


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lolhistory",
        description="导出英雄联盟对局历史记录。"
                    "默认: WeGame API（方法3，推荐使用）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # WeGame（推荐）— 无需客户端
  python -m lolhistory --cookies cookies.json
  python -m lolhistory --cookies cookies.json -n 500 --detailed
  python -m lolhistory --cookies cookies.json --detail-game 10979787952

  # LCU API — 需要 League 客户端运行
  python -m lolhistory --method lcu
  python -m lolhistory --method lcu -n 200 -f csv
  python -m lolhistory --method lcu --lockfile "D:\\\\英雄联盟\\\\lockfile"

  # 通过 CLI 参数直接传入认证信息
  python -m lolhistory --puin 1079564392 --pkey "0003..." --tgp-biz-ticket "0100..." --tgp-id 12460692
        """,
    )

    # 方法选择
    p.add_argument("--method", choices=["wegame", "lcu"], default="wegame",
                   help="数据来源: wegame（默认，推荐）或 lcu")

    # ── WeGame 认证 ──────────────────────────────────────────────────────
    wg = p.add_argument_group("WeGame 认证 (method=wegame)")
    wg.add_argument("--cookies", "-c", help="包含 WeGame Cookie 的 JSON 文件路径")
    wg.add_argument("--extract-cookies", dest="extract_cookies", metavar="DIR",
                    nargs="?", const="wegame-api-export",
                    help="从抓包导出文件中提取 WeGame Cookie。"
                         "扫描 DIR 目录（默认: wegame-api-export/）中最新的 "
                         "HAR/raw/curl 文件，提取后保存为 cookies.json 并退出。")
    wg.add_argument("--puin", help="WeGame puin cookie")
    wg.add_argument("--pkey", help="WeGame pkey cookie")
    wg.add_argument("--tgp-biz-ticket", help="WeGame tgp_biz_ticket cookie")
    wg.add_argument("--tgp-id", help="WeGame tgp_id cookie")
    wg.add_argument("--openid", help="加密后的 openid，用于详情 API（省略则自动探测）")
    wg.add_argument("--area", type=int, default=1,
                    help="服务器大区（1=艾欧尼亚，默认: 1）")

    # ── LCU 认证 ─────────────────────────────────────────────────────────
    lcu = p.add_argument_group("LCU 认证 (method=lcu)")
    lcu.add_argument("--lockfile", help="League 客户端 lockfile 的显式路径")
    lcu.add_argument("--game-dir", help="英雄联盟安装目录（有助于查找 lockfile）")

    # ── 获取选项 ────────────────────────────────────────────────────────
    fetch = p.add_argument_group("获取选项")
    fetch.add_argument("-n", "--max-games", type=int, default=50000,
                       help="最大获取对局数（默认: wegame 为 50000，lcu 为 5000）")
    fetch.add_argument("--delay", type=int, default=None,
                       help="API 请求间隔毫秒数（默认: wegame 200，lcu 300）")
    fetch.add_argument("--count-per-page", type=int, default=10,
                       help="WeGame 每页对局数（最大 10，默认: 10）")
    fetch.add_argument("--no-tft", action="store_true", default=True,
                       help="跳过云顶之弈对局（默认开启）")
    fetch.add_argument("--include-tft", action="store_true",
                       help="包含云顶之弈对局")

    # ── 详情 ─────────────────────────────────────────────────────────────
    detail = p.add_argument_group("对局详情")
    detail.add_argument("--detailed", action="store_true",
                        help="为每场对局获取完整详情 "
                             "(WeGame 对应 GetBattleDetail，LCU 对应 /games/{id})")
    detail.add_argument("--detail-game", metavar="GAME_ID",
                        help="获取并展示单场对局的完整详情，然后退出")

    # ── 输出 ─────────────────────────────────────────────────────────────
    out = p.add_argument_group("输出")
    out.add_argument("-f", "--format", dest="fmt", choices=["json", "csv", "both"],
                     default="both", help="导出格式（默认: both）")
    out.add_argument("-o", "--output-dir", default=".",
                     help="输出目录（默认: 当前目录）")
    out.add_argument("--output-prefix", default=None,
                     help="自定义文件名前缀（默认: wegame_matches / lol_matches）")
    out.add_argument("--no-sqlite", action="store_true",
                     help="跳过 SQLite 导出（仅导出 CSV）")

    # ── 断点续传 ─────────────────────────────────────────────────────────
    cp = p.add_argument_group("断点续传")
    cp.add_argument("--checkpoint", action="store_true",
                    help="保存/加载进度，便于中断后恢复")
    cp.add_argument("--checkpoint-file", default=None,
                    help="断点续传文件路径")

    # ── 其他 ─────────────────────────────────────────────────────────────
    p.add_argument("-v", "--verbose", action="store_true", help="详细日志输出")
    return p


# ──────────────────────────────────────────────────────────────────────────
# LCU 方法
# ──────────────────────────────────────────────────────────────────────────

def run_lcu(args) -> int:
    """运行方法1+2: LCU API。"""
    from ._lcu import (
        LCUApiClient, LCUApiError, LockfileNotFoundError,
        discover_lockfile, fetch_matches, parse_match_summary,
    )
    from ._export import export_csv

    print("=" * 60)
    print("  英雄联盟对局历史导出 — LCU API（方法1+2）")
    print("=" * 60)

    # 步骤1: 发现 lockfile
    try:
        lf = discover_lockfile(args.lockfile, args.game_dir)
    except LockfileNotFoundError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        return 1

    print(f"\n✓ 已连接到 League 客户端")
    print(f"  端口: {lf['port']}, 协议: {lf['protocol']}")

    # 步骤2: 创建 API 客户端
    delay = args.delay if args.delay is not None else 300
    max_games = args.max_games if args.max_games != 50000 else 5000
    skip_tft = not args.include_tft

    try:
        with LCUApiClient(lf) as api:
            if not api.test_connection():
                print("\n[错误] 无法连接到 LCU API。League 客户端是否正在运行？",
                      file=sys.stderr)
                return 1

            # 获取召唤师信息
            print("\n正在获取召唤师信息...")
            summoner = api.get_summoner()
            name = summoner.get("display_name") or summoner.get("game_name", "Unknown")
            print(f"  召唤师: {name}（等级 {summoner['summoner_level']}）")
            print(f"  PUUID: {summoner['puuid']}")

            # 加载英雄数据
            print("\n正在加载英雄数据...")
            champ_map = api.get_champion_data()
            print(f"  已加载 {len(champ_map)} 个英雄")

            # 步骤3: 获取对局列表
            print(f"\n正在获取对局记录（最多 {max_games} 场）...")
            raw_matches = fetch_matches(
                api, summoner["puuid"],
                max_games=max_games, skip_tft=skip_tft, delay_ms=delay,
            )
            total = len(raw_matches)
            if total == 0:
                print("\n[提示] 未找到对局记录。")
                return 0
            print(f"\n共获取到: {total} 场对局")

            # 步骤4: 解析
            print("\n正在解析对局数据...")
            summaries = []
            for m in raw_matches:
                s = parse_match_summary(m, summoner["puuid"], champ_map)
                if s:
                    summaries.append(s)
            print(f"  已解析 {len(summaries)} 场对局")

            # 步骤5: 可选的详情获取
            details = None
            if args.detailed:
                game_ids = [m.get("gameId", 0) for m in raw_matches if m.get("gameId")]
                print(f"\n正在获取 {len(game_ids)} 场对局详情...")
                details = {}
                for i, gid in enumerate(game_ids, 1):
                    try:
                        details[gid] = api.get_match_detail(gid)
                    except LCUApiError as e:
                        logger.warning("详情获取失败 %s: %s", gid, e)
                    sys.stderr.write(f"\r  {i}/{len(game_ids)}...")
                    sys.stderr.flush()
                    if delay:
                        time.sleep(delay / 1000.0)
                sys.stderr.write("\n")

            # 步骤6: 导出
            clean = sanitize_filename(name) or "Unknown"
            date_str = datetime.now().strftime("%Y%m%d")
            prefix = args.output_prefix or f"lol_matches_{clean}_{date_str}"
            out = Path(args.output_dir)
            out.mkdir(parents=True, exist_ok=True)

            print(f"\n正在导出（格式: {args.fmt}）...")
            results = {}

            if args.fmt in ("csv", "both"):
                cp = str(out / f"{prefix}.csv")
                export_csv(summaries, cp)
                results["csv"] = cp

            if args.fmt in ("json", "both"):
                import json
                jp = str(out / f"{prefix}.json")

                # ── 读取已有 JSON 进行合并 ──────────────────────────────
                existing_matches = []
                existing_details = {}
                existing_ids = set()
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        prev = json.load(f)
                    existing_matches = prev.get("matches", [])
                    existing_details = prev.get("detailed_matches", {})
                    existing_ids = {str(m.get("gameId", "")) for m in existing_matches}
                    logger.info("JSON 已有: %d 场对局, %d 条详情",
                                len(existing_matches), len(existing_details))
                except FileNotFoundError:
                    logger.info("JSON 新文件: %s", jp)
                except (json.JSONDecodeError, OSError, KeyError):
                    logger.warning("JSON 读取失败，将覆盖: %s", jp, exc_info=True)

                # ── 过滤新对局并合并详情 ──────────────────────────────────
                new_matches = [m for m in raw_matches
                               if str(m.get("gameId", "")) not in existing_ids]
                merged_matches = existing_matches + new_matches

                merged_details = dict(existing_details)
                if details:
                    for k, v in details.items():
                        if str(k) not in merged_details:
                            merged_details[str(k)] = v

                export_data = {
                    "export_info": {
                        "exported_at": datetime.now().isoformat(),
                        "source": "LCU API",
                        "total_matches": len(merged_matches),
                    },
                    "summoner": summoner,
                    "matches": merged_matches,
                }
                if merged_details:
                    export_data["detailed_matches"] = merged_details
                with open(jp, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
                results["json"] = jp
                logger.info("JSON 已导出: %d 场对局（%d 已有 + %d 新增）",
                            len(merged_matches), len(existing_matches), len(new_matches))

            for fmt_name, filepath in results.items():
                print(f"  [{fmt_name.upper()}] → {filepath}")

            if not args.no_sqlite and details:
                from ._export import export_sqlite
                sp = str(out / f"{prefix}.db")
                export_sqlite(summaries, None, sp)  # LCU 详情非 WeGame 格式，暂不处理
            elif not args.no_sqlite:
                from ._export import export_sqlite
                sp = str(out / f"{prefix}.db")
                export_sqlite(summaries, None, sp)

            # 统计摘要
            wins = sum(1 for s in summaries if s.get("胜利"))
            losses = total - wins
            wr = (wins / total * 100) if total > 0 else 0
            print(f"\n{'=' * 60}")
            print(f"  导出完成！")
            print(f"  总计: {total} | 胜: {wins} | 负: {losses} | 胜率: {wr:.1f}%")
            print(f"{'=' * 60}\n")
            return 0

    except LCUApiError as e:
        if e.status_code == 403:
            print(CN_403_BANNER, file=sys.stderr)
        else:
            print(f"\n[API 错误] {e}", file=sys.stderr)
        return 1
    except ConnectionError as e:
        print(f"\n[连接错误] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n\n已中断。")
        return 130


# ──────────────────────────────────────────────────────────────────────────
# WeGame 方法
# ──────────────────────────────────────────────────────────────────────────

def run_wegame(args) -> int:
    """运行方法3: WeGame API。"""
    from ._wegame import (
        WegameApiClient, WegameApiError,
        load_cookies, validate_cookies, merge_cookies,
        fetch_battle_list, fetch_battle_details,
        parse_battle_summary, parse_battle_detail,
    )
    from ._export import export_csv, export_sqlite

    print("=" * 60)
    print("  英雄联盟对局历史导出 — WeGame API（方法3）")
    print("=" * 60)

    # ── 认证 ─────────────────────────────────────────────────────────────
    cookies = {}
    if args.cookies:
        cookies = load_cookies(args.cookies)
        logger.info("从 %s 加载了 %d 个 Cookie", len(cookies), args.cookies)

    overrides = {
        "puin": args.puin or "",
        "pkey": args.pkey or "",
        "tgp_biz_ticket": args.tgp_biz_ticket or "",
        "tgp_id": args.tgp_id or "",
    }
    cookies = merge_cookies(cookies, overrides)

    missing = validate_cookies(cookies)
    if missing:
        print(f"[错误] 缺少必需的 Cookie: {', '.join(missing)}", file=sys.stderr)
        print("请通过 --cookies 文件 或 --puin/--pkey/--tgp-biz-ticket/--tgp-id 提供。",
              file=sys.stderr)
        return 1

    delay = args.delay if args.delay is not None else 200
    skip_tft = not args.include_tft

    client = WegameApiClient(cookies)
    if args.openid:
        client.set_openid(args.openid)

    # ── 单场详情模式 ──────────────────────────────────────────────────
    if args.detail_game:
        print(f"\n正在获取对局 {args.detail_game} 的详情...")
        try:
            data = client.get_battle_detail(args.detail_game, area=args.area)
            detail = parse_battle_detail(data, client.openid or "")

            # 展示详情
            print(f"\n{'=' * 60}")
            print(f"  对局详情: {detail['game_id']}")
            print(f"{'=' * 60}")
            print(f"  模式: {detail['game_mode']}")
            print(f"  队列: {get_queue_name(detail['game_queue_id'])}")
            print(f"  时长: {detail['game_time_played']}秒")
            print(f"  版本: {detail['game_server_version']}")
            print(f"  提前投降: {bool(detail['was_early_surrender'])}")
            print(f"\n  队伍数据:")
            for team in detail["teams"]:
                print(f"    队伍 {team.get('team_id', '?')}: "
                      f"击杀={team.get('kills', 0)} 死亡={team.get('deaths', 0)} "
                      f"助攻={team.get('assists', 0)} | "
                      f"金币={team.get('gold_earned', 0)} | "
                      f"Bans={team.get('banInfoList', [])}")

            print(f"\n  玩家 ({len(detail['all_players'])} 人):")
            my_id = client.openid or ""
            for pl in detail["all_players"]:
                is_me = "← 你" if (my_id and pl.get("openid") == my_id) else ""
                name = pl.get("summoner_name", "Unknown")
                k = pl.get("kills", 0) or 0
                d = pl.get("deaths", 0) or 0
                a = pl.get("assists", 0) or 0
                champ = pl.get("champion_id", 0)
                items = [pl.get(f"item{i}", 0) for i in range(7)]
                print(f"    {name:<20s} 英雄={champ:<5d} "
                      f"击杀={k:<3d} 死亡={d:<3d} 助攻={a:<3d} "
                      f"装备={items} {is_me}")

            # 导出单场详情
            prefix = args.output_prefix or f"wegame_detail_{args.detail_game}"
            out = Path(args.output_dir)
            out.mkdir(parents=True, exist_ok=True)

            import json
            jp = str(out / f"{prefix}.json")
            with open(jp, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n  详情已保存 → {jp}")

            client.close()
            return 0
        except WegameApiError as e:
            print(f"\n[API 错误] {e}", file=sys.stderr)
            return 1

    # ── 常规模式: 获取对局列表 ──────────────────────────────────────────
    print(f"\n正在连接 WeGame API（大区={args.area}）...")
    if not client.test_connection():
        print("\n[错误] 连接失败。请检查:", file=sys.stderr)
        print("  1. Cookie 是否有效（未过期）", file=sys.stderr)
        print("  2. 网络连接是否正常", file=sys.stderr)
        return 1
    print("  [✓] 连接成功")

    # ── 断点续传 ───────────────────────────────────────────────────────
    cp_file = args.checkpoint_file or "wegame_checkpoint.json"
    cp_battles = []
    cp_details = {}

    if args.checkpoint:
        import json as _json
        if os.path.exists(cp_file):
            try:
                with open(cp_file, "r", encoding="utf-8") as f:
                    cp = _json.load(f)
                cp_battles = cp.get("battles", [])
                cp_details = cp.get("detailed", {})
                if cp_battles:
                    print(f"\n从断点恢复: {len(cp_battles)} 场对局")
            except (_json.JSONDecodeError, OSError):
                pass

    # ── 获取对局列表 ────────────────────────────────────────────────────
    if cp_battles:
        all_battles = cp_battles
    else:
        print(f"\n正在获取对局列表（最多 {args.max_games} 场）...")
        all_battles = fetch_battle_list(
            client, area=args.area, max_games=args.max_games,
            count_per_page=args.count_per_page, skip_tft=skip_tft,
            delay_ms=delay,
        )

    total = len(all_battles)
    print(f"\n共获取到: {total} 场对局")
    if total == 0:
        print("[提示] 未找到对局记录。")
        client.close()
        return 0

    # 快速统计
    wins = sum(1 for b in all_battles if b.get("win") == "Win")
    losses = total - wins
    wr = (wins / total * 100) if total > 0 else 0
    print(f"  胜: {wins} | 负: {losses} | 胜率: {wr:.1f}%")

    timestamps = []
    for b in all_battles:
        ts = int(b.get("game_start_time", "0")) / 1000.0
        if ts > 0:
            timestamps.append(ts)
    if timestamps:
        oldest = datetime.fromtimestamp(min(timestamps)).strftime("%Y-%m-%d")
        newest = datetime.fromtimestamp(max(timestamps)).strftime("%Y-%m-%d")
        print(f"  时间范围: {oldest} → {newest}")

    # 获取列表后保存断点
    if args.checkpoint:
        _save_cp(cp_file, all_battles, None)
        print(f"  断点已保存: {cp_file}")

    # ── 获取详情（可选）─────────────────────────────────────────────────
    detail_data = {}
    if args.detailed:
        if cp_details:
            detail_data = cp_details
            print(f"\n使用断点中已缓存的 {len(detail_data)} 条详情")
        else:
            game_ids = [str(b.get("game_id", "")) for b in all_battles if b.get("game_id")]
            print(f"\n正在获取 {len(game_ids)} 场对局详情...")
            est_min = len(game_ids) * delay / 1000 / 60
            if est_min > 1:
                print(f"  （预计约 {est_min:.0f} 分钟，延迟 {delay}ms）")
            detail_data = fetch_battle_details(
                client, game_ids, area=args.area, delay_ms=delay)
            if args.checkpoint:
                _save_cp(cp_file, all_battles, detail_data)

    # ── 解析与导出 ──────────────────────────────────────────────────────
    prefix = args.output_prefix or "wegame_matches"
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n正在导出（格式: {args.fmt}）...")
    parsed = [parse_battle_summary(b) for b in all_battles]
    results = {}

    if args.fmt in ("csv", "both"):
        cp = str(out / f"{prefix}.csv")
        export_csv(parsed, cp)
        results["csv"] = cp

    if args.fmt in ("json", "both"):
        import json as _json
        jp = str(out / f"{prefix}.json")

        # ── 读取已有 JSON 进行合并 ──────────────────────────────────────
        existing_battles = []
        existing_details = {}
        existing_ids = set()
        try:
            with open(jp, "r", encoding="utf-8") as f:
                prev = _json.load(f)
            existing_battles = prev.get("battles", [])
            existing_details = prev.get("detailed_matches", {})
            existing_ids = {str(b.get("game_id", "")) for b in existing_battles}
            logger.info("JSON 已有: %d 场对局, %d 条详情",
                        len(existing_battles), len(existing_details))
        except FileNotFoundError:
            logger.info("JSON 新文件: %s", jp)
        except (_json.JSONDecodeError, OSError, KeyError):
            logger.warning("JSON 读取失败，将覆盖: %s", jp, exc_info=True)

        # ── 过滤新对局并合并详情 ──────────────────────────────────────────
        new_battles = [b for b in all_battles
                       if str(b.get("game_id", "")) not in existing_ids]
        merged_battles = existing_battles + new_battles

        # 详情: 保留已有，仅添加新键
        merged_details = dict(existing_details)
        if detail_data:
            for k, v in detail_data.items():
                if str(k) not in merged_details:
                    merged_details[str(k)] = v

        export = {
            "export_info": {
                "exported_at": datetime.now().isoformat(),
                "source": "WeGame API",
                "puin": client.puin,
                "total_matches": len(merged_battles),
            },
            "battles": merged_battles,
        }
        if merged_details:
            export["detailed_matches"] = merged_details
        with open(jp, "w", encoding="utf-8") as f:
            _json.dump(export, f, ensure_ascii=False, indent=2, default=str)
        results["json"] = jp
        logger.info("JSON 已导出: %d 场对局（%d 已有 + %d 新增）",
                    len(merged_battles), len(existing_battles), len(new_battles))

    # SQLite 导出（默认总是执行，除非 --no-sqlite）
    if not args.no_sqlite:
        sp = str(out / f"{prefix}.db")
        export_sqlite(parsed, detail_data if detail_data else None, sp,
                      self_openid=client.openid or "")
        results["sqlite"] = sp

    for fmt_name, filepath in results.items():
        print(f"  [{fmt_name.upper()}] → {filepath}")

    # 成功完成后清理断点文件
    if args.checkpoint and os.path.exists(cp_file):
        try:
            os.remove(cp_file)
        except OSError:
            pass

    # ── 摘要 ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"  导出完成！")
    print(f"  数据来源: WeGame API（大区={args.area}）")
    print(f"  对局总数: {total}")
    print(f"  详情数据: {'有' if detail_data else '无'}")
    print(f"  SQLite: {'有' if not args.no_sqlite else '无'}")
    print(f"{'=' * 60}\n")

    client.close()
    return 0


def _save_cp(filepath: str, battles: list, details: dict | None):
    import json as _json
    cp = {"saved_at": datetime.now().isoformat(), "total": len(battles),
          "battles": battles}
    if details:
        cp["detailed"] = details
    with open(filepath, "w", encoding="utf-8") as f:
        _json.dump(cp, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────
# Cookie 提取（从 Fiddler/Charles 抓包导出文件）
# ──────────────────────────────────────────────────────────────────────────

def run_extract_cookies(args) -> int:
    """从抓包导出文件中提取 WeGame Cookie 并退出。"""
    from ._cookie_extract import auto_extract_and_save

    export_dir = args.extract_cookies  # str（默认 "wegame-api-export"）
    output_file = args.cookies or "cookies.json"

    print("=" * 60)
    print("  英雄联盟对局历史导出 — Cookie 提取工具")
    print("=" * 60)
    print(f"\n抓包导出目录: {export_dir}")
    print(f"输出文件:      {output_file}")

    try:
        _ = auto_extract_and_save(export_dir, output_file)
    except FileNotFoundError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        return 1

    print(f"\n{'=' * 60}")
    print(f"  提取完成！")
    print(f"  下一步: python -m lolhistory --cookies {output_file}")
    print(f"{'=' * 60}\n")
    return 0


# ──────────────────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Cookie 提取模式（不调用 API — 仅提取并退出）
    if args.extract_cookies is not None:
        return run_extract_cookies(args)

    if args.method == "lcu":
        return run_lcu(args)
    else:
        return run_wegame(args)


if __name__ == "__main__":
    sys.exit(main())
