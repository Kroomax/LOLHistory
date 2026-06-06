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

# 数据分析 — 从 SQLite 生成交互式 HTML 报告
.venv/Scripts/python -m lolhistory --analyze
.venv/Scripts/python -m lolhistory --analyze --db my_matches.db --output my_report.html
.venv/Scripts/python -m lolhistory --analyze --session-gap 2.0
```

无测试、lint 或构建步骤。

## 架构

MVP 结构，7 个模块各司其职，方法之间互不引用：

| 文件 | 用途 |
|------|------|
| `__main__.py` | CLI（argparse）+ 方法路由 |
| `_data.py` | 共享常量：`QUEUE_NAMES`(96)、`MAP_NAMES`(17)、`TFT_QUEUE_IDS`、工具函数 |
| `_lcu.py` | 方法1+2：lockfile 4策略发现 → LCU ApiClient → 分页获取 → 解析 |
| `_wegame.py` | 方法3：Cookie 认证 → WegameApiClient → `GetBattleList`(分页) + `GetBattleDetail`(详情) |
| `_cookie_extract.py` | 方法3 Cookie获取：从 Fiddler/Charles 导出的 HAR/raw/curl 文件中提取 cookie |
| `_export.py` | 导出：CSV（UTF-8 BOM）+ SQLite（`match_summary` 35列 + `match_detail` 32列） |
| `_analysis.py` | 数据分析：从 SQLite 读取 → 30+ 维度分析 → 生成单个交互式 HTML 报告 |

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

## 数据分析 (_analysis.py)

CLI: `python -m lolhistory --analyze [--db wegame_matches.db] [--output report.html] [--session-gap 2.0]`

从 SQLite (`match_summary`) 读取全量对局 → 30+ 维度分析 → 输出单个静态交互式 HTML。

### 分析维度（7 大板块）

| 板块 | 内容 |
|------|------|
| 总览 | 场次/胜率/KDA/场均经济/五杀/四杀/MVP/SVP/场均评分/英雄数（17 卡片） |
| 胜率分析 | 星期/小时/红蓝方/位置/KDA分桶/时长四分位/神秘因子方差排名/荣誉影响 |
| 英雄分析 | Top 5 拿手英雄多维雷达图（逐维度比率归一化）+ 英雄池堆叠图 |
| 段位分析 | LP 累计趋势 + 10 场滚动胜率 + 段位分布 + KDA 随段位变化 |
| 出勤分析 | 日历热力图（GitHub 风格）+ 每日胜率 + 每日 LP 变化 |
| Session 分析 | 连续游戏规模分布 + 最后一局结束时间分布 + 首局 vs 末局胜率 |
| 心理与风格 | 情绪韧性（连败后反弹）/ 连胜连败 / 抗压局 / carry 局 / 前期后期能力 / 发挥稳定性 / 位置灵活性 / 投降率 / AFK 影响 / 经济效率 |

### 关键实现细节

- **雷达图归一化**: 逐维度比率归一化（全对局平均 = 50 分基准，2倍平均 = 100），避免跨维度量纲不同导致小值归零
- **GPM 计算**: 存储计算后的 GPM 值而非原始金币，防止索引错位 bug
- **经济效率排除**: <4 分钟（240s）的重开局不计入 GPM 统计
- **位置胜率极差**: 排除场次 <5 的位置，避免小样本虚高
- **Chart.js v4 CDN**: bootcdn → jsdelivr → unpkg 三级 fallback（国内友好）
- **所有标签中文化**: 仅保留 KDA/GPM/LP 等常用缩写
- **无新依赖**: 仅使用 stdlib（`sqlite3`, `json`, `datetime`, `collections`, `math`, `statistics`）

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
