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
  从 WeGame 或客户端直连，一键导出完整的英雄联盟对局历史——<br>
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
| 🔌 **双数据源** | WeGame API（500 场 + 段位 + 装备符文）/ LCU API（客户端直连） |
| 🍪 **智能 Cookie 提取** | 丢一个 Fiddler/Charles/浏览器 抓包文件进去，自动识别 HAR、Raw、cURL、Charles 四种格式 |
| 📊 **三种导出格式** | CSV（UTF-8 BOM，Excel 即开）+ SQLite（35 列 summary + 31 列 detail）+ JSON（完整原始数据） |
| 🔄 **增量合并** | 重复运行自动去重追加——只拉新对局，不覆盖旧数据 |
| 💾 **断点续传** | 拉 500 场详情要几分钟，中断后从断点恢复，不用重来 |
| 🏆 **段位历史** | 每局 tier / league_points / rank 全记录（WeGame） |
| 🧩 **10 人完整详情** | 7 件装备、6 枚符文、召唤师技能、伤害/承伤/视野——敌我双方全量 |
| 🚫 **智能过滤** | 默认跳过 8 种云顶之弈队列，只保留召唤师峡谷 |
| 🗺️ **完整识别** | 96 种游戏队列 × 17 张地图，从排位到极限闪击全覆盖 |
| 🔐 **纯本地运行** | 数据直达你的硬盘，不经过任何第三方 |

---

## 📦 快速开始

### 前置条件

- **Python 3.10+**
- Windows（LCU API 需要 Windows；WeGame API 理论跨平台）
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

打开 WeGame → 启动英雄联盟 → 点击「WeGame 助手」→ 对局记录页面。此时用抓包工具导出 **任意一个** `www.wegame.com.cn` 的 HTTPS 请求：

| 工具 | 操作 |
|---|---|
| **Fiddler** | 右键请求 → Save → Request → Raw，放入 `wegame-api-export/` |
| **Charles** | 右键请求 → Export → HAR，放入 `wegame-api-export/` |
| **浏览器 DevTools** | Network → 右键请求 → Copy as cURL → 粘贴到 `.txt` 文件 |

然后一行命令提取：

```bash
python -m lolhistory --extract-cookies
```

自动扫描目录、识别格式、提取并保存 `cookies.json`。输出示例：

```json
{
  "puin": "xxxxxxxxxx",
  "pkey": "0003...",
  "tgp_biz_ticket": "0100...",
  "tgp_id": "xxxxxxxx"
}
```

> 💡 **Cookie 有效期**：与 WeGame 助手页共享 session，通常管几小时到一天。过期后重新抓一次即可。

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

跑完在当前目录生成三个文件：

```
wegame_matches.csv    ← Excel 拖进去就能看，35 列中文表头
wegame_matches.db     ← SQLite，match_summary + match_detail 两张表
wegame_matches.json   ← 完整原始数据（含 10 人详情）
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
| `-f json/csv/both` | 导出格式（默认 both） |
| `-o ./output` | 输出目录 |
| `--output-prefix NAME` | 自定义文件名前缀 |
| `--checkpoint` | 启用断点续传 |
| `--no-sqlite` | 只导出 CSV |
| `--include-tft` | 包含云顶之弈对局 |

Cookie 还可以直接从命令行传入（无需文件）：

```bash
python -m lolhistory --puin <puin> --pkey "<pkey>" --tgp-biz-ticket "<ticket>" --tgp-id <id>
```

### LCU API（客户端需要开着）

```bash
python -m lolhistory --method lcu
python -m lolhistory --method lcu -n 200 -f csv
python -m lolhistory --method lcu --game-dir "D:\Software\Wegame\英雄联盟"
```

LCU 模式有 **4 种 lockfile 自动发现策略**：显式路径 → 游戏目录 → 已知路径扫描 → 进程命令行提取。绝大多数情况无需手动指定。

> ⚠️ **国服 403 反作弊拦截？**  
> 将 `python.exe` 重命名为 `RiotGamesApi.exe` 即可绕过：  
> `copy .venv\Scripts\python.exe .venv\Scripts\RiotGamesApi.exe`  
> `.venv\Scripts\RiotGamesApi.exe -m lolhistory --method lcu`

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

## 🔧 常见问题

<details>
<summary><strong>Cookie 过期了（错误码 8025009）怎么办？</strong></summary>
重新抓一次 WeGame 助手页的请求，覆盖 <code>cookies.json</code>，再次运行即可。已经导出的数据不会丢失——增量机制会自动跳过已有对局。
</details>

<details>
<summary><strong>为什么只能拉到 ~500 场？</strong></summary>
WeGame API 服务端限制，<code>offset ≥ 500</code> 直接返回空。LCU API 更少（~200 场）。这是腾讯后端的数据保留策略，国服目前没有已知方式突破。
</details>

<details>
<summary><strong>LCU API 和 WeGame API 数据有什么区别？</strong></summary>
WeGame 场次更多（500 vs 200），且包含段位历史、MVP/SVP 等荣誉标记。LCU 优势是不需要抓 Cookie，客户端开着就能用。推荐优先使用 WeGame。
</details>

<details>
<summary><strong>重复运行会覆盖数据吗？</strong></summary>
不会。CSV 和 SQLite 均按 <code>对局ID</code> 去重，重复运行只追加新对局，不覆盖旧数据。
</details>

</details>

---

## 🗺️ 项目结构

```
lolhistory/
├── __main__.py             # CLI 入口 + 参数解析 + 路由到 WeGame / LCU / Cookie 提取
├── _wegame.py              # WeGame API：Cookie 认证 · 分页 · 详情 · 解析
├── _lcu.py                 # LCU API：4 策略 lockfile 发现 · 对局拉取 · 解析
├── _cookie_extract.py      # Cookie 自动提取：HAR / Raw / cURL / Charles 四种格式
├── _export.py              # 导出引擎：CSV (UTF-8 BOM) + SQLite (两表) + 增量去重
├── _data.py                # 共享常量：96 队列 + 17 地图名称映射 + TFT 过滤列表
└── requirements.txt        # 单一依赖：requests
```

---

## 📜 License

MIT © 2026

---

<p align="center">
  <sub>Made with ❤️ for the Summoner's Rift community. GGWP!</sub>
</p>
