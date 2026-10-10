# 简报 0010：子文章技改内容提取为json格式

## 目标
- 解析 data/extra-info/plus/*.md 为 JSON，落盘同目录

## 输出结构：
- 沿用主公告的 sects/xinfas/entries/notes（保真原则不变），每个 xinfa 增加 qixue_table 字段——奇穴表格的结构化数组，每行含 重数/类型/名称/效果/is_changed

## 限制
- 表格行以 | 开头识别；** 只用于判断 is_changed，存入"效果"字段时剥掉符号；md 文件里 ◎ 万花 带空格，解析器要兼容

## 验收标准
- 21 个 JSON 全生成
- 万花篇：花间游的 qixue_table 行数 = 表格实际行数（数一下原文，让数字对得上）
- 抽查沁逸行：is_changed = true；抽查一个未改动奇穴（比如"南风吐月"）：is_changed = false
- 反向条款：两篇抽查文件保留率 ≥ 95%
- pytest 全绿