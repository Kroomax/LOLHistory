<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/Server-CN%20%2F%20Global-red?style=for-the-badge" alt="Server">
</p>

<br>

<h1 align="center">⚔️ lolhistory</h1>

<p align="center">
  <strong>你的每一场召唤师峡谷之战，都值得被记住。</strong>
</p>

<p align="center">
  从 WeGame 一键导出完整的英雄联盟对局历史——<br>
  段位变迁、KDA 走势、装备符文、10 人全量数据，全部落到你本地。
</p>

<br>

---

## 🤔 为什么需要这个？

League 客户端只展示最近 20 场。WeGame 助手虽然能看到更多，但数据锁在网页里——既不能导出，也没法分析。

**lolhistory** 把你散落在腾讯服务器上的对局数据全部取回来：最多 **500 场**完整对局，含段位历史、装备符文、10 人详情。CSV 拖进 Excel 就能做胜率趋势图，SQLite 可以跑 SQL 分析，JSON 可以喂给自己的脚本。

> 客户端都不用开。只要有 Cookie，随时拉数据。

---

## ✨ 核心亮点

| | |
|---|---|
| 🔌 **WeGame API** | 无需客户端，最大 500 场 + 段位历史 + 装备符文 + 10 人详情 |
| 🍪 **一键抓包** | `--capture-cookies` 自动启动代理，登录 WeGame 即获取 Cookie——告别 Fiddler/Charles 手动操作 |
| 📁 **智能 Cookie 提取** | 也支持从 Fiddler/Charles/浏览器 抓包文件中自动提取，兼容 HAR、Raw、cURL、Charles 四种格式 |
| 📊 **三种导出格式** | CSV（UTF-8 BOM，Excel 即开）+ SQLite（35 列 summary + 31 列 detail）+ JSON（完整原始数据） |
| 🔄 **增量合并** | 重复运行自动去重追加——只拉新对局，不覆盖旧数据 |
| 💾 **断点续传** | 拉 500 场详情要几分钟，中断后从断点恢复，不用重来 |
| 🏆 **段位历史** | 每局 tier / league_points / rank 全记录（WeGame） |
| 🧩 **10 人完整详情** | 7 件装备、6 枚符文、召唤师技能、伤害/承伤/视野——敌我双方全量 |
| 🚫 **智能过滤** | 默认跳过 8 种云顶之弈队列，只保留召唤师峡谷 |
| 🗺️ **完整识别** | 96 种游戏队列 × 17 张地图，从排位到极限闪击全覆盖 |
| 📊 **交互式分析报告** | 30+ 维度数据分析，一键生成静态 HTML——胜率因子、英雄雷达、段位趋势、出勤热力图… |
| 🔐 **纯本地运行** | 数据直达你的硬盘，不经过任何第三方 |

---

## 📦 快速开始

### 前置条件

- **Python 3.10+**
- WeGame Cookie（获取方式见下，一分钟搞定）

### 1. 安装

```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt   # 唯一依赖：requests
```

### 2. 获取 Cookie

**🆕 一键抓包（推荐，无需任何手动操作）**

```bash
# 首次使用：安装 mitmproxy 根证书（仅需一次，无需管理员）
python -m lolhistory --install-cert

# 一键抓包：代理自动启动 → 登录 WeGame → Cookie 自动保存
python -m lolhistory --capture-cookies
```

登录 WeGame 即自动完成！Cookie 保存为 `cookies.json`，随后直接使用。

> **原理**：内嵌 mitmproxy HTTP 代理 + Windows 系统代理，自动拦截 WeGame 登录时的认证请求。无需打开助手页/对局记录页，无需任何抓包工具。

<details>
<summary><strong>备选方案：从抓包文件提取（点此展开）</strong></summary>

打开 WeGame → 点击「WeGame 助手」→ 对局记录页面。用抓包工具导出 **任意一个** `www.wegame.com.cn` 的 HTTPS 请求：

| 工具 | 操作 |
|---|---|
| **Fiddler** | 右键请求 → Save → Request → Raw，放入 `wegame-api-export/` |
| **Charles** | 右键请求 → Export → HAR，放入 `wegame-api-export/` |
| **浏览器 DevTools** | Network → 右键请求 → Copy as cURL → 粘贴到 `.txt` 文件 |

然后提取：

```bash
python -m lolhistory --extract-cookies
```

</details>

输出示例：

```json
{
  "puin": "xxxxxxxxxx",
  "pkey": "0003...",
  "tgp_biz_ticket": "0100...",
  "tgp_id": "xxxxxxxx"
}
```

> 💡 **Cookie 有效期**：与 WeGame 助手页共享 session，通常管几小时到一天。过期后重新运行 `--capture-cookies` 即可。

### 3. 拉数据！

```bash
# 基础用法——拉取对局列表（含段位数据）
python -m lolhistory --cookies cookies.json

# 全部拉满——500 场 + 每场 10 人完整装备符文详情
python -m lolhistory --cookies cookies.json -n 500 --detailed

# 只看某一场的完整数据
python -m lolhistory --cookies cookies.json --detail-game GAME_ID

# 指定大区（默认艾欧尼亚=1）
python -m lolhistory --cookies cookies.json --area 1
```

跑完在当前目录生成两个文件：

```
wegame_matches.csv    ← Excel 拖进去就能看，35 列中文表头
wegame_matches.db     ← SQLite，6 张表（对局摘要 + 10 人详情 + 召唤师资料 + 英雄熟练度 + 赛季历史 + 生涯总览）
```

---

## 🧭 使用指南

### WeGame API（推荐，无需客户端）

| 参数 | 说明 |
|---|---|
| `--cookies cookies.json` | Cookie 文件路径 |
| `-n N` | 最大对局数（默认不限，上限 ~500） |
| `--detailed` | 逐场拉取 10 人完整详情（装备/符文/ban） |
| `--detail-game ID` | 查单场详情并在终端打印 |
| `--area N` | 大区 ID（1=艾欧尼亚，2=比尔吉沃特…） |
| `-o ./output` | 输出目录 |
| `--output-prefix NAME` | 自定义文件名前缀 |
| `--checkpoint` | 启用断点续传 |
| `--no-csv` | 跳过 CSV 导出（仅导出 SQLite） |
| `--no-sqlite` | 跳过 SQLite 导出（仅导出 CSV） |
| `--include-tft` | 包含云顶之弈对局 |

Cookie 还可以直接从命令行传入（无需文件）：

```bash
python -m lolhistory --puin <puin> --pkey "<pkey>" --tgp-biz-ticket "<ticket>" --tgp-id <id>
```

---

## 📋 导出数据说明

### match_summary（每场对局一行，35 列）

```
对局ID    日期      时间      游戏时长    队列类型    地图    英雄ID    位置
击杀      死亡      助攻      KDA        评分       金币    双杀~五杀
MVP / SVP / 投降 / 挂机   击杀最多 / 助攻最多 / 金币最多 / 伤害最高 / 承伤最高 / 推塔最多
段位      胜点      段位等级    游戏版本
```

### match_detail（每局每位玩家一行，31 列）

```
对局ID    召唤师名称    英雄ID    阵营    胜负    KDA
装备×7    召唤师技能×2    符文×6
伤害      承伤      金币    补刀    视野分    控制分    is_self（标记哪行是你）
```

---

## 📊 数据分析报告

导出数据后，一行命令生成交互式 HTML 分析报告：

```bash
python -m lolhistory --analyze
```

浏览器打开 `lol_analysis_report.html`，你会看到：

### 7 大分析板块，30+ 图表

| 板块 | 分析内容 |
|---|---|
| 🏠 **总览** | 17 张统计卡片：胜率、KDA、场均经济、MVP/SVP 率、五杀/四杀、常用英雄数… |
| 🔮 **胜率分析** | 星期几胜率最高？哪个时段最强？红蓝方差距？打什么位置最稳？什么 KDA 区间胜率最高？游戏时长对胜率的影响？——所有维度的胜率方差排名，找出你的"神秘因子" |
| 🏆 **英雄分析** | Top 5 拿手英雄多维雷达图（KDA/击杀/助攻/生存率/经济效率）+ 英雄池深度与位置灵活性 |
| 📈 **段位分析** | LP 累计趋势曲线 + 10 场滚动胜率 + 段位分布 + 不同段位的 KDA 变化 |
| 📅 **出勤分析** | GitHub 风格日历热力图 + 每日胜率 + 每日 LP 变化 |
| 🎮 **Session 分析** | 连续游戏 Session 的规模分布、最后一局结束时间、首局 vs 末局胜率对比 |
| 🧠 **心理与风格** | 连败后反弹能力、连胜/连败分布、抗压局胜率、carry 局胜率、前期 vs 后期能力、发挥稳定性、投降率、经济效率（GPM） |

### 图表特点

- **暗色 League 主题**：Shadow Isles 风格，金色/蓝色点缀
- **纯静态 HTML**：无需服务器，浏览器打开即用
- **每张图表配有中文概要**：金色斜体一句话总结，直击要点
- **响应式布局**：手机/平板/桌面全适配

### 自定义参数

```bash
python -m lolhistory --analyze --db my_matches.db          # 指定数据库
python -m lolhistory --analyze --output my_report.html      # 指定输出路径
python -m lolhistory --analyze --session-gap 2.0            # 调整 Session 间隔阈值
```

> 💡 **数据要求**：需要有 `--detailed` 导出的 SQLite（含 `match_detail` 表）才能获取装备/符文等详情维度的完整分析。基础分析只需 `match_summary` 表。

---

## 🔧 常见问题

<details>
<summary><strong>Cookie 过期了（错误码 8025009）怎么办？</strong></summary>
重新抓一次 WeGame 助手页的请求，覆盖 <code>cookies.json</code>，再次运行即可。已经导出的数据不会丢失——增量机制会自动跳过已有对局。
</details>

<details>
<summary><strong>为什么只能拉到 ~500 场？</strong></summary>
WeGame API 服务端限制，<code>offset ≥ 500</code> 直接返回空。这是腾讯后端的数据保留策略，国服目前没有已知方式突破。
</details>

<details>
<summary><strong>重复运行会覆盖数据吗？</strong></summary>
不会。CSV 和 SQLite 均按 <code>对局ID</code> 去重，重复运行只追加新对局，不覆盖旧数据。
</details>

<details>
<summary><strong>分析报告能分析哪些数据？</strong></summary>
分析报告从 SQLite 读取数据，涵盖 <strong>7 大板块 30+ 维度</strong>：胜率因子（星期/时段/位置/红蓝方/KDA/时长）、英雄雷达图、段位趋势、出勤日历、Session 模式、心理风格（连胜/连败/抗压/carry/稳定性）、经济效率等。报告为纯静态 HTML，浏览器打开即用，无需服务器。
</details>

</details>

---

## 🗺️ 项目结构

```
lolhistory/
├── __main__.py             # CLI 入口 + 参数解析 + WeGame 流程编排
├── _wegame.py              # WeGame API：Cookie 认证 · 分页 · 详情 · 解析
├── _capture_cookies.py     # Cookie 一键抓包：mitmproxy 内嵌 · 系统代理 · 自动捕获
├── _cookie_extract.py      # Cookie 文件提取：HAR / Raw / cURL / Charles 四种格式
├── _export.py              # 导出引擎：CSV (UTF-8 BOM) + SQLite (六表) + 增量去重
├── _data.py                # 共享常量：96 队列 + 17 地图名称映射 + TFT 过滤列表
├── _analysis.py            # 数据分析：30+ 维度 → 交互式 HTML 报告
└── requirements.txt        # 依赖：requests + mitmproxy
archive/
└── _lcu.py                 # [已弃用] LCU API 实现，保留作为技术参考
```

---

## 📜 License

MIT © 2026

---

<p align="center">
  <sub>Made with ❤️ for the Summoner's Rift community. GGWP!</sub>
</p>
