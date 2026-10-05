# 简报 008：生成技改报告


## 目标：
- 新建 src/make_report.py，读 data/patches/*.json，生成 Markdown 简报到 reports/ 目录

## 结构：
- 标题头（标题/日期/三数统计）→ 改动变化榜（按条目数降序）→ 分门派展开（心法 + 条目；is_shared 的心法标注"（通用）"；notes 叙述文保留在门派开头）

## 限制：
- 只读 JSON 不碰网络；
- generate_report() 可 import；
- 简报是派生物，每次全量重新生成、直接覆盖


## 验收标准：
9/24 简报的变化榜条目数合计 = 352，和 JSON 三数一致
抽查"沁逸"条目出现在万花/花间游小节
连续生成两次，第二次 git status 无变化