"""lolhistory 入口点 — 英雄联盟对局历史导出工具。

用法:
    # 首先获取 Cookie（从 Fiddler/Charles 抓包导出文件中提取）
    python -m lolhistory --extract-cookies
    python -m lolhistory --extract-cookies ./wegame-api-export

    # WeGame API（无需客户端）
    python -m lolhistory --cookies cookies.json
    python -m lolhistory --cookies cookies.json -n 500 --detailed
    python -m lolhistory --cookies cookies.json --detail-game GAME_ID
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from ._data import get_queue_name, sanitize_filename

logger = logging.getLogger("lolhistory")

# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lolhistory",
        description="导出英雄联盟对局历史记录（WeGame API）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m lolhistory --cookies cookies.json
  python -m lolhistory --cookies cookies.json -n 500 --detailed
  python -m lolhistory --cookies cookies.json --detail-game 10979787952

  # 通过 CLI 参数直接传入认证信息
  python -m lolhistory --puin 1079564392 --pkey "0003..." --tgp-biz-ticket "0100..." --tgp-id 12460692
        """,
    )

    # ── WeGame 认证 ──────────────────────────────────────────────────────
    wg = p.add_argument_group("WeGame 认证")
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

    # ── 获取选项 ────────────────────────────────────────────────────────
    fetch = p.add_argument_group("获取选项")
    fetch.add_argument("-n", "--max-games", type=int, default=50000,
                       help="最大获取对局数（默认: 50000）")
    fetch.add_argument("--delay", type=int, default=None,
                       help="API 请求间隔毫秒数（默认: 200）")
    fetch.add_argument("--count-per-page", type=int, default=10,
                       help="WeGame 每页对局数（最大 10，默认: 10）")
    fetch.add_argument("--no-tft", action="store_true", default=True,
                       help="跳过云顶之弈对局（默认开启）")
    fetch.add_argument("--include-tft", action="store_true",
                       help="包含云顶之弈对局")

    # ── 详情 ─────────────────────────────────────────────────────────────
    detail = p.add_argument_group("对局详情")
    detail.add_argument("--detailed", action="store_true",
                        help="为每场对局获取完整详情 (GetBattleDetail)")
    detail.add_argument("--detail-game", metavar="GAME_ID",
                        help="获取并展示单场对局的完整详情，然后退出")

    # ── 输出 ─────────────────────────────────────────────────────────────
    out = p.add_argument_group("输出")
    out.add_argument("-f", "--format", dest="fmt", choices=["json", "csv", "both"],
                     default="both", help="导出格式（默认: both）")
    out.add_argument("-o", "--output-dir", default=".",
                     help="输出目录（默认: 当前目录）")
    out.add_argument("--output-prefix", default=None,
                     help="自定义文件名前缀（默认: wegame_matches）")
    out.add_argument("--no-sqlite", action="store_true",
                     help="跳过 SQLite 导出（仅导出 CSV）")

    # ── 断点续传 ─────────────────────────────────────────────────────────
    cp = p.add_argument_group("断点续传")
    cp.add_argument("--checkpoint", action="store_true",
                    help="保存/加载进度，便于中断后恢复")
    cp.add_argument("--checkpoint-file", default=None,
                    help="断点续传文件路径")

    # ── 数据分析 ─────────────────────────────────────────────────────────
    ana = p.add_argument_group("数据分析")
    ana.add_argument("--analyze", action="store_true",
                     help="从 SQLite 数据生成交互式 HTML 分析报告")
    ana.add_argument("--db", default="wegame_matches.db",
                     help="SQLite 数据库路径（默认: wegame_matches.db）")
    ana.add_argument("--output", dest="html_output", default="report.html",
                     help="HTML 报告输出路径（默认: report.html，自动添加日期后缀）")
    ana.add_argument("--session-gap", type=float, default=2.0,
                     help="游戏轮次判定间隔小时数（默认: 2.0）")

    # ── 其他 ─────────────────────────────────────────────────────────────
    p.add_argument("-v", "--verbose", action="store_true", help="详细日志输出")
    return p


# ──────────────────────────────────────────────────────────────────────────
# WeGame 方法
# ──────────────────────────────────────────────────────────────────────────

def run_wegame(args) -> int:
    """运行 WeGame API 对局导出。"""
    from ._wegame import (
        WegameApiClient, WegameApiError,
        load_cookies, validate_cookies, merge_cookies,
        fetch_battle_list, fetch_battle_details,
        parse_battle_summary, parse_battle_detail,
        parse_summoner_info, parse_player_recent_stat,
        parse_champions, parse_battle_report,
    )
    from ._data import get_wegame_tier_name
    from ._export import export_csv, export_sqlite

    print("=" * 60)
    print("  英雄联盟对局历史导出 — WeGame API")
    print("=" * 60)

    # ── 认证 ─────────────────────────────────────────────────────────────
    cookies = {}
    if args.cookies:
        cookies = load_cookies(args.cookies)
        logger.info("从 %s 加载了 %d 个 Cookie", args.cookies, len(cookies))

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

    # ── 自动获取召唤师信息与生涯统计 ─────────────────────────────────
    # 在获取对局列表之前自动执行，无需用户管理。
    # 失败仅警告，不阻断对局导出流程。
    summoner_profile_data = None
    summoner_career_data = None
    try:
        logger.info("正在获取召唤师信息...")
        si_data = client.get_summoner_info(area=args.area)
        summoner_profile_data = parse_summoner_info(si_data)

        # 显示关键信息
        name = summoner_profile_data.get("召唤师名称", "Unknown")
        tag = summoner_profile_data.get("标签", "")
        level = summoner_profile_data.get("等级", 0)
        tier = summoner_profile_data.get("段位", 0)
        lp = summoner_profile_data.get("胜点", 0)
        season_wins = summoner_profile_data.get("赛季胜场", 0)
        season_total = summoner_profile_data.get("赛季总场次", 0)
        display_name = f"{name}#{tag}" if tag else name
        tier_display = get_wegame_tier_name(tier) if tier else "无段位"
        if lp and tier:
            tier_display = f"{tier_display} {lp}LP"
        wr = (season_wins / max(season_total, 1) * 100) if season_total > 0 else 0

        print(f"\n  召唤师: {display_name}")
        print(f"  等级: {level} | 段位: {tier_display}")
        if season_total > 0:
            print(f"  赛季: {season_wins}胜/{season_total - season_wins}负 "
                  f"({wr:.1f}%) | 总场次: {season_total}")

        # 缓存 openid 用于后续 GetBattleDetail / GetPlayerRecentStat 调用
        oid = summoner_profile_data.get("openid", "")
        if oid and not client.openid:
            client.set_openid(oid)
            logger.info("已缓存 openid（来自 GetSummonerInfo）")

        # 获取生涯统计（需要 openid）
        if oid:
            logger.info("正在获取生涯统计...")
            sc_data = client.get_player_recent_stat(oid, area=args.area)
            summoner_career_data = parse_player_recent_stat(sc_data)

            total_kills = summoner_career_data.get("生涯总击杀", 0)
            total_mvps = summoner_career_data.get("生涯MVP", 0)
            total_svps = summoner_career_data.get("生涯SVP", 0)
            total_pentas = summoner_career_data.get("生涯五杀", 0)
            max_wins = summoner_career_data.get("最长连胜", 0)
            recent = f"{summoner_career_data.get('近期胜场', 0)}W/{summoner_career_data.get('近期场次', 0)}场"
            print(f"  生涯: {total_kills}击杀 | MVP×{total_mvps} SVP×{total_svps} "
                  f"| 五杀×{total_pentas} | 最长连胜{max_wins}")
            print(f"  近30天: {recent}")

    except WegameApiError as e:
        logger.warning("获取召唤师/生涯信息失败（不影响对局导出）: %s", e)
    except Exception as e:
        logger.warning("获取召唤师/生涯信息时出现意外错误: %s", e)

    # ── 自动获取英雄熟练度（GetChampion） ─────────────────────────────────
    # 需要 openid，在 get_summoner_info 成功后自动执行。
    # 失败仅警告，不阻断主流程。
    champions_data = None
    oid = client.openid
    if oid:
        try:
            logger.info("正在获取英雄熟练度数据...")
            champ_raw = client.get_champions(oid, area=args.area)
            champions_data = parse_champions(champ_raw)
            champ_count = len(champions_data)
            # 简要统计：按熟练度排序，显示前 3
            top_champs = sorted(
                champions_data, key=lambda x: x.get("熟练度", 0), reverse=True
            )[:3]
            top_names = [f"英雄{ch['英雄ID']}({ch['熟练度']})" for ch in top_champs]
            print(f"  英雄熟练度: {champ_count}个英雄")
            print(f"  熟练度前3: {', '.join(top_names)}")
        except WegameApiError as e:
            logger.warning("获取英雄熟练度失败（不影响对局导出）: %s", e)
        except Exception as e:
            logger.warning("获取英雄熟练度时出现意外错误: %s", e)
    else:
        logger.info("跳过英雄熟练度获取（缺少 openid）")

    # ── 自动获取赛季战斗报告（GetBattleReport） ──────────────────────────
    # 使用 puin 认证，不依赖 openid。失败仅警告。
    battle_report_data = None
    try:
        logger.info("正在获取赛季战斗报告...")
        br_raw = client.get_battle_report(area=args.area)
        battle_report_data = parse_battle_report(br_raw)
        bc = battle_report_data.get("battle_count", {})
        seasons = battle_report_data.get("season_list", [])
        total_all = bc.get("全部总场", 0)
        print(f"  战斗报告: 全模式 {total_all} 场, {len(seasons)} 个赛季记录")
    except WegameApiError as e:
        logger.warning("获取赛季战斗报告失败（不影响对局导出）: %s", e)
    except Exception as e:
        logger.warning("获取赛季战斗报告时出现意外错误: %s", e)

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
        # 查询数据库中已有对局 ID，避免重复获取 API
        prefix = args.output_prefix or "wegame_matches"
        db_path = str(Path(args.output_dir) / f"{prefix}.db")
        existing_ids = set()
        if os.path.exists(db_path):
            import sqlite3
            conn = sqlite3.connect(db_path)
            # 旧库升级：确保 area 列存在
            try:
                conn.execute("ALTER TABLE match_summary ADD COLUMN area INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass
            rows = conn.execute(
                "SELECT game_id FROM match_summary WHERE area = ?", (args.area,)
            ).fetchall()
            existing_ids = {r[0] for r in rows}
            conn.close()
            if existing_ids:
                print(f"  数据库中已有 {len(existing_ids)} 条记录，将跳过重复获取")

        print(f"\n正在获取对局列表（最多 {args.max_games} 场）...")
        all_battles = fetch_battle_list(
            client, area=args.area, max_games=args.max_games,
            count_per_page=args.count_per_page, skip_tft=skip_tft,
            delay_ms=delay, existing_ids=existing_ids or None,
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
    parsed = [parse_battle_summary(b, area=args.area) for b in all_battles]
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
                      self_openid=client.openid or "",
                      summoner_info=summoner_profile_data,
                      summoner_career=summoner_career_data,
                      puin=client.puin,
                      champions=champions_data,
                      battle_report=battle_report_data,
                      area=args.area)
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

    # 数据分析模式
    if args.analyze:
        from ._analysis import generate_report
        try:
            path = generate_report(
                db_path=args.db,
                output_path=args.html_output,
                session_gap_hours=args.session_gap,
            )
            print(f"\n[OK] 分析报告已生成: {path}")
            print(f"   在浏览器中打开即可查看。")
        except FileNotFoundError as e:
            print(f"\n[错误] {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"\n[错误] 生成报告失败: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            return 1
        return 0

    return run_wegame(args)


if __name__ == "__main__":
    sys.exit(main())
