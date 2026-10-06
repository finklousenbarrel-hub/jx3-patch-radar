# 项目说明书

## 项目是什么

剑网3技改情报聚合器（jx3-patch-radar）：自动抓取剑网3官方技改公告，解析成结构化 JSON，再生成人类可读的 Markdown 简报。

- 数据源：https://www.jx3api.com/news/records （LV0 免 ticket，limit ≤ 50，历史窗口约一个月）
- 处理管道：抓取（fetch_news）→ 解析（parse_patch）→ 简报（make_report）
- 当前数据基线：9/24 第二轮公告 = 21 门派 / 65 心法 / 352 条目（核心验收锚点）；另有 9/8 首轮公告（预告体，内容为叙述段 + 3 条通用条目）

## 结构地图

```
jx3-patch-radar/
├── src/
│   ├── fetch_news.py    # 抓取：拉列表 → 比对 state → 只处理新增（存 txt + 解析 json）→ 更新 state
│   ├── parse_patch.py   # 解析：txt → 结构化 JSON（门派/心法/条目，含 notes、is_shared）
│   └── make_report.py   # 简报：json → Markdown（标题头 → 改动变化榜 → 分门派详情）
├── tests/               # pytest：test_fetch_news / test_parse_patch / test_make_report（共 30 项）
├── data/
│   ├── patches/         # *.txt（清洗后正文）+ *.json（结构化解析结果）
│   └── state.json       # 增量状态：{公告url: {url, processed_at}}
├── reports/             # 生成的 Markdown 简报（派生物）
├── docs/
│   ├── task-briefs/     # 任务简报 005~008（需求与验收标准）
│   ├── experiments/     # 摸底脚本（001.py 等）
│   ├── assets/          # README 用的终端演示 SVG
│   └── tech-selection.md# 数据源选型记录
└── requirements.txt
```

关键可 import 接口：`fetch_records` / `load_state` / `save_state` / `filter_new_records` / `process_record`（fetch_news）；`parse_patch_text` / `parse_patch_file` / `save_patch_json`（parse_patch）；`generate_report` / `generate_report_file`（make_report）。

## 怎么运行和验证

```bash
pip install -r requirements.txt
python src/fetch_news.py     # 增量抓取 + 解析；第二次运行应输出“本次新增 0 条”
python src/make_report.py    # 全量重建 reports/*.md
python -m pytest tests/ -q   # 应 30 passed（各测试文件也可直接 python 运行）
```

验收基线（改动后必查）：

- 9/24 JSON：门派 21 / 心法 65 / 条目 352；「沁逸」条目同时含原效果与「调整为：」文本
- 9/8 JSON：文本字数 ≥ 原 txt 95%（防静默丢数据）；少林下「旗舰通用」is_shared = true
- 删 data/state.json 重跑能完整重建，且 txt/json 逐字节一致
- 简报连续生成两次，逐字节一致（输出不含时间戳）

## 铁律（不许碰）

- parse_patch 只读已清洗的 txt，**不碰 HTML**；make_report 只读 JSON，**不碰网络**
- 增量运行时（state.json 存在），已处理公告的 txt/json **不得改动或重写**，只处理新增条目
- 公告唯一标识一律用 **url**（缺失时回退标题并告警）
- JSON 一律 UTF-8、中文不转义（ensure_ascii=False）
- 简报是派生物：每次全量重新生成、直接覆盖，不要在 make_report 里加增量逻辑或时间戳
- 条目续段（「调整为：…」等不以 · 开头的行）必须并入上一条目，不得拆散或丢弃
- jx3api 会拒绝 Python requests 的 TLS 握手：fetch_records 已内置 curl 回退通道，不要拆掉；subprocess 调 curl 必须用字节捕获（Windows GBK 会毁掉 UTF-8 输出）
