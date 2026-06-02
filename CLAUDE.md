# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在此仓库中工作时提供指引。

## 运行命令

```bash
.venv/Scripts/pip install -r requirements.txt   # 唯一依赖: requests

# 获取 Cookie（从 Fiddler/Charles 抓包导出文件中提取）
.venv/Scripts/python -m lolhistory --extract-cookies                    # 扫描 wegame-api-export/
.venv/Scripts/python -m lolhistory --extract-cookies ./my-exports       # 自定义目录
.venv/Scripts/python -m lolhistory --extract-cookies -c cookies.json    # 指定输出文件名

# 方法3 — WeGame API（默认，推荐，无需客户端）
.venv/Scripts/python -m lolhistory --cookies cookies.json
.venv/Scripts/python -m lolhistory --cookies cookies.json -n 500 --detailed
.venv/Scripts/python -m lolhistory --cookies cookies.json --detail-game GAME_ID

# 方法1+2 — LCU API（需客户端运行）
.venv/Scripts/python -m lolhistory --method lcu
.venv/Scripts/python -m lolhistory --method lcu --game-dir "D:\Software\Wegame\英雄联盟(26)"
```

无测试、lint 或构建步骤。

## 架构

MVP 结构，4 个模块各司其职，方法之间互不引用：

| 文件 | 用途 |
|------|------|
| `__main__.py` | CLI（argparse）+ 方法路由 |
| `_data.py` | 共享常量：`QUEUE_NAMES`(96)、`MAP_NAMES`(17)、`TFT_QUEUE_IDS`、工具函数 |
| `_lcu.py` | 方法1+2：lockfile 4策略发现 → LCU ApiClient → 分页获取 → 解析 |
| `_wegame.py` | 方法3：Cookie 认证 → WegameApiClient → `GetBattleList`(分页) + `GetBattleDetail`(详情) |
| `_cookie_extract.py` | 方法3 Cookie获取：从 Fiddler/Charles 导出的 HAR/raw/curl 文件中提取 cookie |
| `_export.py` | 导出：CSV（UTF-8 BOM）+ SQLite（`match_summary` 35列 + `match_detail` 32列） |

方法4（Riot官方API，国服不可用）未实现。LCU约100~200场，WeGame约500场且含段位/10人装备符文。

## LCU API 关键点

- **自签名证书** — 全局 `verify=False`
- **Lockfile** — 格式 `name:PID:port:password:https`，每次客户端重启变化；国服 WeGame 启动时 lockfile 常为空
- **空 lockfile** — `_lcu.py` 的 `_scan_process_cmdline()` 自动从进程命令行提取 `--app-port` 和 `--remoting-auth-token`
- **响应双格式** — `{"games": {"games": [...]}}` 或 `{"games": [...]}`
- **国服 403** — 反作弊拦截非白名单进程，绕过：`python.exe` → `RiotGamesApi.exe`

> `Riot Client Data/User Data/Config/lockfile`（port 9918）是 Riot Client，无法访问 LCU 端点。

## WeGame API 关键点

### 两个端点

| 端点 | 用途 | account_type | id 字段 |
|------|------|:---:|:---:|
| `GetBattleList` | 分页对局列表（基础KDA/位置/输赢） | 1 | `puin`（数字UID） |
| `GetBattleDetail` | 单局10人完整数据（装备/符文/ban） | 2 | `openid`（Base64） |

### 认证

Cookie（与 WeGame 助手页共享 session），必需 4 个：`puin`, `pkey`, `tgp_biz_ticket`, `tgp_id`。

**获取方式：**

1. `python -m lolhistory --extract-cookies` — 从抓包导出文件自动提取（最简单）
   - Fiddler: 右键请求 → Export → Raw Files（.txt），放入 `wegame-api-export/`
   - Charles: 右键请求 → Export → HAR（.har），放入 `wegame-api-export/`
   - 浏览器: DevTools → Network → 右键请求 → Copy as cURL，粘贴到 .txt 文件
   - 工具自动扫描目录 → 提取最新文件的 cookie → 保存 `cookies.json`

2. Fiddler/Charles 手动抓包 `www.wegame.com.cn` 的 Cookie 请求头，手写 JSON `{"puin":"...", "pkey":"...", ...}`

3. （可选）`python wegame_cookie_helper.py --scan` — 从 WeGame.exe 进程内存提取

### 已知限制

- `count` 最大 10（超过返回 `8000002`）；offset ≥ 500 返回空
- Cookie 过期返回 `8025009`（登录信息过期），需重新获取
