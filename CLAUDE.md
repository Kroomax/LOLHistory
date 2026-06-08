# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在此仓库中工作时提供指引。

## 运行命令

```bash
.venv/Scripts/pip install -r requirements.txt   # requests + mitmproxy

# 获取 Cookie — 一键抓包（推荐，无需手动操作抓包工具）
.venv/Scripts/python -m lolhistory --install-cert                       # 安装 mitmproxy 根证书（仅需一次）
.venv/Scripts/python -m lolhistory --capture-cookies                     # 一键抓包，登录 WeGame 即完成
.venv/Scripts/python -m lolhistory --capture-cookies -c cookies.json     # 自定义输出文件名

# 获取 Cookie — 从抓包导出文件提取（备选方案）
.venv/Scripts/python -m lolhistory --extract-cookies                    # 扫描 wegame-api-export/
.venv/Scripts/python -m lolhistory --extract-cookies ./my-exports       # 自定义目录
.venv/Scripts/python -m lolhistory --extract-cookies -c cookies.json    # 指定输出文件名

# WeGame API（无需客户端）
.venv/Scripts/python -m lolhistory --cookies cookies.json
.venv/Scripts/python -m lolhistory --cookies cookies.json -n 50 --detail
.venv/Scripts/python -m lolhistory --cookies cookies.json --detail-game GAME_ID

# 数据分析 — 从 SQLite 生成交互式 HTML 报告
.venv/Scripts/python -m lolhistory --analyze
.venv/Scripts/python -m lolhistory --analyze --db my_matches.db --output my_report.html
```

无测试、lint 或构建步骤。

## 架构

MVP 结构，7 个模块各司其职：

| 文件 | 用途 |
|------|------|
| `__main__.py` | CLI（argparse）+ WeGame 流程编排（含自动获取召唤师/英雄熟练度/赛季报告/生涯统计） |
| `_data.py` | 共享常量：`QUEUE_NAMES`(96)、`MAP_NAMES`(17)、`TFT_QUEUE_IDS`、`WEGAME_TIER_NAMES`(9)、工具函数 |
| `_wegame.py` | WeGame API：Cookie 认证 → WegameApiClient → 6 个 API 端点 + 6 个解析函数 |
| `_capture_cookies.py` | Cookie 一键抓包：内嵌 mitmproxy HTTP 代理，登录 WeGame 即自动提取 |
| `_cookie_extract.py` | Cookie 文件提取：从 Fiddler/Charles 导出的 HAR/raw/curl 文件中提取 cookie |
| `_export.py` | 导出：CSV（UTF-8 BOM）+ SQLite（6 张表） |
| `_analysis.py` | 数据分析：从 SQLite 读取 → 30+ 维度分析 → 生成单个交互式 HTML 报告（6 章，~30 图表） |

`archive/_lcu.py` 为已弃用的 LCU API 实现（方法1+2），保留作为技术参考。Riot 官方 API（方法4，国服不可用）未实现。

## WeGame API 关键点

### 六个端点

| 端点 | 用途 | account_type | id 字段 | 备注 |
|------|------|:---:|:---:|------|
| `GetBattleList` | 分页对局列表（基础KDA/位置/输赢） | 1 | `puin`（数字UID） | |
| `GetBattleDetail` | 单局10人完整数据（装备/符文/ban） | 2 | `openid`（Base64） | |
| `GetSummonerInfo` | 召唤师信息 + 赛季段位 + openid | 1 | `puin` | **trpc-caller: `TftBattle`**（非默认 `LolBattle`） |
| `GetPlayerRecentStat` | 近30天统计 + 生涯总数据 + 常用英雄/位置 | 2 | `openid` | 需要先获取 openid |
| `GetChampion` | 全部172英雄熟练度（场次/胜率/常用分路/赛季数据） | 2 | `openid`（Base64） | `flag=2`，需要 openid |
| `GetBattleReport` | 全模式总览统计 + 26赛季段位历史 | 1 | `puin` | `sids=[255]` 获取所有赛季 |

### 自动流程

运行时**自动执行**（无需用户管理）：

1. 连接测试 → **自动调用 `GetSummonerInfo`** → 显示召唤师等级/段位/胜率 → 缓存 openid
2. **自动调用 `GetChampion`**（使用 openid）→ 显示 172 英雄熟练度 Top 3
3. **自动调用 `GetBattleReport`**（使用 puin）→ 显示全模式总场次 + 赛季数
4. **自动调用 `GetPlayerRecentStat`**（使用 openid）→ 显示生涯击杀/MVP/五杀/连胜
5. 继续原有对局列表获取流程

步骤 2-4 失败仅 `logger.warning`，不阻断对局导出。数据自动写入 6 张 SQLite 表。

### 认证

Cookie（与 WeGame 助手页共享 session），必需 4 个：`puin`, `pkey`, `tgp_biz_ticket`, `tgp_id`。

**获取方式：**

1. `python -m lolhistory --capture-cookies` — **一键抓包（推荐）**
   - 内嵌 mitmproxy HTTP 代理 + Windows 系统代理
   - 首次使用需 `--install-cert` 安装根证书（仅需一次，certutil -user 无需管理员）
   - 代理启动后登录 WeGame 即自动捕获 Cookie → 保存 `cookies.json`
   - WeGame QBCore 使用**逗号**分隔 Cookie（非标准 `;`），解析函数已兼容

2. `python -m lolhistory --extract-cookies` — 从抓包导出文件提取（备选）
   - Fiddler: 右键请求 → Export → Raw Files（.txt），放入 `wegame-api-export/`
   - Charles: 右键请求 → Export → HAR（.har），放入 `wegame-api-export/`
   - 浏览器: DevTools → Network → 右键请求 → Copy as cURL，粘贴到 .txt 文件
   - 工具自动扫描目录 → 提取最新文件的 cookie → 保存 `cookies.json`

3. Fiddler/Charles 手动抓包 `www.wegame.com.cn` 的 Cookie 请求头，手写 JSON `{"puin":"...", "pkey":"...", ...}`

### 已知限制

- `count` 最大 10（超过返回 `8000002`）；offset ≥ 500 返回空
- Cookie 过期返回 `8025009`（登录信息过期），需重新获取

### `_post()` extra_headers 模式

`GetSummonerInfo` 需要 `trpc-caller: wegame.pallas.web.TftBattle`（其他接口用 `LolBattle`）。
通过 `_post(path, body, extra_headers={"trpc-caller": "..."})` 临时覆盖请求头，
内部用 save/restore + finally 保证不影响后续请求。

### SQLite 表结构（6 张表）

| 表 | 主键 | 策略 | 用途 |
|---|------|------|------|
| `match_summary` | game_id | INSERT OR REPLACE | 每局对局摘要（35列） |
| `match_detail` | AUTOINCREMENT + UNIQUE(game_id, summoner_name) | INSERT OR IGNORE | 每局10人完整数据（32列） |
| `summoner_profile` | puin | INSERT OR REPLACE | 召唤师当前快照（55列）：基本信息 + 赛季段位 + 近30天 + 生涯总计 |
| `champion_mastery` | (puin, champion_id) | INSERT OR REPLACE | 172英雄熟练度当前快照（12列）：场次/胜率/熟练度/常用分路/赛季数据 |
| `season_history` | (puin, sid) | INSERT OR REPLACE | 赛季段位历史（14列）：每赛季排位+组排的场次/段位/胜点 |
| `career_overview` | puin | INSERT OR REPLACE | 生涯全模式总览（19列）：匹配/大乱斗/单双排/组排/人机各模式场次 |

### WeGame 段位映射

```python
WEGAME_TIER_NAMES = {0: "未定级", 1: "钻石", 2: "翡翠", 3: "铂金",
                     4: "黄金", 5: "白银", 6: "超凡大师", 7: "傲世宗师", 8: "最强王者"}
```

注意：WeGame 编号方向与 Riot 不同——非大师段位数值越小段位越高（1=钻石，5=白银），大师+从 6 递增。

## 数据分析 (_analysis.py)

CLI: `python -m lolhistory --analyze [--db wegame_matches.db] [--output report.html]`

从 SQLite (`match_summary`) 读取全量对局 → 30+ 维度分析 → 输出单个静态交互式 HTML。

### 报告结构（6 大板块）

报告按以下顺序组织，每章双列网格中卡片数为偶数，无空位：

| 章节 | 导航 ID | 内容 |
|------|---------|------|
| 一、总览 | `#overview` | 17 hero 卡片：场次/胜率/KDA/场均经济/五杀/四杀/MVP/SVP/最长连胜/出勤率/英雄池/招牌英雄/最高&当前段位 |
| 二、胜率因子 | `#winrate` | 8 卡片：星期几 → 时段 → 红蓝方 → 位置 → 对局时长 → LP区间 → 胜率极差排名（全宽）→ 荣誉与胜率（全宽） |
| 三、游戏节奏 | `#game-rhythm` | 6 卡片全部双列：轮次规模分布 → 首局开始时间 → 末局结束时间 → 轮次内第N局胜率 → '再来一局'陷阱 → 输后与赢后胜率 |
| 四、游戏心理 | `#psychology` | 5 卡片：胜负连势 → 发挥稳定性 → 挂机影响 → 投降分析 + 过度自信与救赎效应（全宽） |
| 五、玩家水平 | `#player-level` | 6 卡片：英雄池分布 → 招牌英雄雷达（全宽）→ LP爬分效率 → 多杀含金量 → Carry依赖度画像（全宽）→ 经济效率分析 |
| 六、出勤日历 | `#attendance` | 7 卡片：关键日期（全宽）→ 出勤热力图（全宽）→ 10场滚动胜率 → 时段热力图（全宽）→ 对局数量热力图（全宽）→ 段位LP趋势（全宽）→ 每日LP变化 |

### 关键实现细节

- **雷达图归一化**: 逐维度比率归一化（全对局平均 = 50 分基准，2倍平均 = 100），避免跨维度量纲不同导致小值归零
- **GPM 计算**: 存储计算后的 GPM 值而非原始金币，防止索引错位 bug
- **经济效率排除**: <4 分钟（240s）的重开局不计入 GPM 统计
- **位置胜率极差**: 排除场次 <5 的位置，避免小样本虚高
- **Chart.js v4 CDN**: bootcdn → jsdelivr → unpkg 三级 fallback（国内友好）
- **所有标签中文化**: 仅保留 KDA/GPM/LP 等常用缩写
- **无新依赖**: 仅使用 stdlib（`sqlite3`, `json`, `datetime`, `collections`, `math`, `statistics`）

### HTML 生成函数映射

| 章节 | 函数 | 说明 |
|------|------|------|
| 总览 | `_build_hero(ov)` | 17 hero 卡片 + 综合评语 |
| 胜率因子 | `_build_section_winrate(r)` | 8 卡片，全宽：胜率极差排名 + 荣誉与胜率 |
| 游戏节奏 | `_build_section_game_rhythm(r)` | 6 卡片全部双列，包含 session 图表 + tilt |
| 游戏心理 | `_build_section_psychology(r)` | 5 卡片，全宽：过度自信与救赎效应 |
| 玩家水平 | `_build_section_player_level(r)` | 6 卡片，全宽：拿手英雄雷达 + Carry依赖度画像 |
| 出勤日历 | `_build_section_attendance(r)` | 7 卡片，全宽：关键日期/热力图/LP趋势 |

导航由 `_build_nav()` 生成，CSS 由 `_build_css()` 生成，所有图表 JS 由 `_build_all_charts(r)` 生成。
调整章节内容时修改对应 `_build_section_*` 函数，调整顺序修改 `_build_html()` 中的列表。

### 图表 JS 代码调试经验

**所有图表都不显示时，优先检查 JS 语法错误**——Chart.js 在遇到第一个语法错误时就停止执行，导致全部图表空白。

**常见根因：f-string 中 `{{}}` 嵌套对象括号计数错误**。例如：
```python
# ❌ 错误 — scales 被提前关闭，y 变成 options 的顶级属性
scales:{{x:{{...grid:{{color:'#2a3a4a'}}}}}},y:{{...}}}
#                                    ↑ 这里 }}}} 同时关闭 grid + x + scales
#                                    ↓ 正确：只关闭 grid + x，scales 保持打开
scales:{{x:{{...grid:{{color:'#2a3a4a'}}}},y:{{...}}}}
```

**排查流程：**
1. 用 `node -e "new Function(scriptBody)"` 检查 JS 语法，无需浏览器
2. 用 `grep -n "new Chart" report.html` 确认图表初始化数量与 canvas 数量一致
3. 检查双 Y 轴（`yAxisID: 'y1'`）的 chart 是否在 `scales` 中正确定义了 `y1`
4. 散点图数据格式：`{x: val, y: val}` 而非 `[x, y]`

**诀窍：** 复杂嵌套对象（如多轴 scales）优先用多行格式而非单行内联，减少括号计数失误。修改图表 JS 后，务必用 `node -e` 做语法验证。
