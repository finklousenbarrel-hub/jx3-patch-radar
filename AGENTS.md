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
│   │                    #   也解析 extra-info/plus/*.md → 同目录 .json（含 qixue_table）
│   ├── make_report.py   # 简报：json → Markdown（标题头 → 改动变化榜 → 分门派详情）
│   │                    #   也读 plus/*.json → 首轮技改总览（跨门派改动奇穴排行榜，简报 012）
│   ├── fetch_link_info.py # 子文章：json notes 链接 → 官网 api.php → 全文 txt + plus Markdown
│   ├── fetch_skill_info.py # 技能库：unua.top 快照 → 校验（22 门派/乱天狼×15/generatedAt）
│   │                       #   → data/skill-info/*.json（幂等，共用 state.json）
│   ├── fetch_arena_rank.py # 名剑榜：推栏直调 top200（X-Sk 签名，ticket/密钥读 .env 不进仓库）
│   │                       #   → data/arena-rank/*.json（前 200 门派统计，每日最多一次）
│   ├── fetch_jjc_stats.py  # 名剑数据（简报 022/023）：推栏 /jjcrankstats 心法强度榜
│   │                       #   （复用 fetch_arena_rank 签名；aggregate-status=false 时短路）
│   │                       #   → data/jjc-stats/*.json（每日双快照：all + 2800-3100，
│   │                       #     uid=分段+日期互不顶替；样本不足的组合记 unavailable）
│   ├── retriever.py     # 检索（简报 014/015/016）：技能库+技改库压平成文档库
│   │                    #   字符级 2-gram TF-IDF + 余弦 top-3；名称完整互相包含 +0.5 加权（015）
│   │                    #   模糊档（016）：name 重叠率 ≥50% 按 0.5×重叠率 加分（阈值禁止下调）
│   ├── agent_tools.py   # 问答层工具（简报 023）：query_skill/query_patch（retriever
│   │                    #   按类型过滤封装）+ query_meta_rank（只读本地 jjc-stats /
│   │                    #   arena-rank 快照，绝不出网；样本不足自动回退并注明）
│   ├── agent.py         # 工具调用 Agent（简报 023，arch-agent-v1 方案A）：
│   │                    #   Kimi function calling 自主选工具，工具循环上限 3 轮防爆
│   ├── run_eval.py      # 评测跑批（简报 023）：agent-eval-v1 全 10 题 → Kimi 裁判
│   │                    #   逐题判定 → reports/agent-eval-v1-results.md（派生物）
│   └── ask.py           # 问答（简报 014，ask_demo 的升级）：任意问题 → 检索 top-3
│                        #   → 拼 prompt → Kimi 回答（带数据日期）
├── tests/               # pytest：12 个测试文件（共 157 项）
├── data/
│   ├── patches/         # *.txt（清洗后正文）+ *.json（结构化解析结果）
│   ├── skill-info/      # 技能库快照 *.json（文件名=generatedAt，保留 source 字段）
│   ├── arena-rank/      # 名剑榜快照 *.json（文件名=mode-日期，含 force_stats 与全量 rows）
│   ├── jjc-stats/       # 心法强度榜快照 *.json（文件名=jjc-分段-日期，rankings 键=dps|tps-时间维度）
│   ├── extra-info/      # 门派子文章全文 txt（文件名=文章标题）
│   │   └── plus/        # 子文章 Markdown（表格还原+标红加粗）+ 解析后的 .json（qixue_table）
│   └── state.json       # 增量状态：{公告url 或 generatedAt: {url, processed_at, ...}}
├── reports/             # 生成的 Markdown 简报（派生物）
├── docs/
│   ├── task-briefs/     # 任务简报 005~023（需求与验收标准）
│   ├── eval/            # Agent 评测集（agent-eval-v1.json：3 技能+3 技改+2 强度榜+1 复合+1 拒答）
│   ├── arch-agent-v1.md # Agent 架构设计（工具清单/方案A function calling/失败防御）
│   ├── experiments/     # 摸底脚本（001.py 等）
│   ├── assets/          # README 用的终端演示 SVG
│   └── tech-selection.md# 数据源选型记录
└── requirements.txt
```

关键可 import 接口：`fetch_records` / `load_state` / `save_state` / `filter_new_records` / `process_record`（fetch_news）；`parse_patch_text` / `parse_patch_file` / `save_patch_json`（parse_patch）；`generate_report` / `generate_report_file` / `generate_overview` / `generate_overview_file`（make_report）；`fetch_skill_data` / `validate_skill_data` / `snapshot_uid` / `save_snapshot` / `process_snapshot`（fetch_skill_info）；`load_credentials` / `xsk_sign` / `tuilan_post` / `fetch_top200` / `validate_top200` / `flatten_rows` / `force_statistics` / `build_payload`（fetch_arena_rank）；`fetch_aggregate_status` / `fetch_filter_options` / `fetch_kungfu_rank` / `enabled_periods` / `flatten_rank_rows` / `validate_rank_rows` / `resolve_score_range` / `pending_segments` / `snapshot_uid`（fetch_jjc_stats）；`ToolBox` / `TOOL_SCHEMAS` / `dispatch`（agent_tools）；`agent_answer` / `ask_agent` / `MAX_TOOL_ROUNDS`（agent）；`load_eval_set` / `parse_judge_output` / `judge_answer` / `render_report`（run_eval）；`skill_documents` / `patch_documents` / `build_documents` / `tokenize` / `TfidfIndex` / `search` / `NAME_MATCH_BOOST` / `FUZZY_OVERLAP_MIN`（retriever）；`build_prompt` / `answer` / `ask`（ask）。

## 怎么运行和验证

```bash
pip install -r requirements.txt
python src/fetch_news.py       # 增量抓取 + 解析；第二次运行应输出“本次新增 0 条”
python src/fetch_skill_info.py # 技能库快照（每天最多请求一次）；已处理应输出“本次新增 0 条”
python src/fetch_arena_rank.py # 名剑榜快照（每日最多一次，凭证在 .env）；已处理输出“本次新增 0 条”
python src/fetch_jjc_stats.py  # 强度榜双快照（all + 2800-3100，每日一次）；已处理输出“本次新增 0 条”
python src/make_report.py      # 全量重建 reports/*.md
python src/retriever.py "问题" # 检索文档库 top-3（技能 558 / 技改 1869）
python src/ask.py "问题"       # 检索 + Kimi 问答（需 .env 的 MOONSHOT_API_KEY；无参进交互模式）
python src/agent.py "问题"     # 工具调用 Agent（function calling，3 轮上限；无参进交互模式）
python src/run_eval.py         # 跑 agent-eval-v1 全 10 题 → reports/agent-eval-v1-results.md
python -m pytest tests/ -q     # 应 157 passed（各测试文件也可直接 python 运行）
```

验收基线（改动后必查）：

- 9/24 JSON：门派 21 / 心法 65 / 条目 352；「沁逸」条目同时含原效果与「调整为：」文本
- 9/8 JSON：文本字数 ≥ 原 txt 95%（防静默丢数据）；少林下「旗舰通用」is_shared = true
- 首轮总览（plus json → reports/*-总览.md）：门派 21 / 奇穴 1152 / 改动 346，排行榜改动数合计 = 346
- 名剑榜快照（data/arena-rank/3v3-*.json）：total = 1000、force_stats 合计 = 200；当日重复运行输出“本次新增 0 条”且文件与 state 逐字节不变
- 强度榜快照（data/jjc-stats/jjc-<分段>-<日期>.json）：每日双快照（all + 2800-3100），uid=分段+日期互不顶替；rankings 覆盖 dps/tps × 全部可用时间维度，样本不足的组合记 unavailable（官方「数据量过少」口径）；当日重复运行输出“本次新增 0 条”且不发请求
- Agent 评测（run_eval）：reports/agent-eval-v1-results.md 逐题判定；7 道非工具题不许回归，2 强度榜 + 1 复合必须答出，拒答题必须仍拒答
- 删 data/state.json 重跑能完整重建，且 txt/json 逐字节一致
- 简报连续生成两次，逐字节一致（输出不含时间戳）

## 铁律（不许碰）

- 通用铁律（假完成/越权写入防御）见 hello-engineering/docs/universal-rules.md，本项目铁律为其特化补充
- parse_patch 只读已清洗的 txt，**不碰 HTML**；make_report 只读 JSON，**不碰网络**
- 增量运行时（state.json 存在），已处理公告的 txt/json **不得改动或重写**，只处理新增条目
- 公告唯一标识一律用 **url**（缺失时回退标题并告警）
- JSON 一律 UTF-8、中文不转义（ensure_ascii=False）
- 简报是派生物：每次全量重新生成、直接覆盖，不要在 make_report 里加增量逻辑或时间戳
- 条目续段（「调整为：…」等不以 · 开头的行）必须并入上一条目，不得拆散或丢弃
- 模糊匹配重叠率阈值 `FUZZY_OVERLAP_MIN`（50%）**禁止下调**：低于 50% 会让「孤影化双」这类技能被「什么效果」等泛词误捞（retriever 模糊档，简报 016）
- jx3api 会拒绝 Python requests 的 TLS 握手：fetch_records 已内置 curl 回退通道，不要拆掉；subprocess 调 curl 必须用字节捕获（Windows GBK 会毁掉 UTF-8 输出）
- 问答层（agent_tools/agent/run_eval）**只读本地数据**（检索库与 data/ 快照），绝不实时调推栏/jx3api；每日一次的抓取纪律属于管道层，用户问多少问题都不该多打一次外部 API（简报 023）
- Agent 工具循环上限 `MAX_TOOL_ROUNDS = 3` **禁止上调**；回答必须逐条对应工具返回，资料里没有就明说不知道，禁止编造（arch-agent-v1 失败防御规范层）
