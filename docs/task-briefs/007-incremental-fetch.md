# 简报 007：爬取管道去重

## 目标
- 修改src/fetch_news.py
- 创立状态文件 data/state.json，记录已处理公告的唯一标识和首次处理时间
- 设定唯一标识为公告的url
- 新的爬取信息流程为：拉列表 → 逐条比对 state → 只处理新的（存 txt + 解析存 json）→ 更新 state → 打印本次新增 N 条

## 环境
jx3-patch-radar 项目
- src存放代码文件 
  src/fetch_news.py用于抓取公告并储存为txt格式文件
  src/parse_patch.py用于将txt文件中的内容解析为json格式
- tests为函数测试用
- docs用来存放开发日志
- data用来存放技改信息抓取结果

数据源 https://www.jx3api.com/news/records 

## 限制
- 增量运行时（state.json 存在时），已处理公告的 txt/json 不得被改动或重写；仅处理新增条目。

## 验收标准
- 连续运行两次：第二次输出"新增 0 条"，且 git status 无文件变化
- 删掉 state.json 重跑：能完整重建，且 txt/json 内容与之前一致
- state.json 里每条记录含 url + 处理日期
- tests/ 补 state 存取和"已处理则跳过"的用例，pytest 全绿