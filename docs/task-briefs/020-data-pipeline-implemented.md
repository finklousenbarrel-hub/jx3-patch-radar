# 任务简报20 数据管道落地

## 目标 
- 对awesome/top200 进行门派统计 输出各个门派前200的数量
- 幂等落盘（state.json 同款）
- 每日最多爬取一次
- ticket 从 .env 读（绝不进仓库）

## 数据源
- 推栏直调 /mine/arena/top200（前 200 排行）+ /mine/equip/get-role-equip（qiXueId 奇穴方案）
- 调用推栏所需要的ticket在环境变量 JX3_Ticket中

## 项目架构
- 见AGENTS.md的内容

## 限制
- 见AGENTS.md的铁律内容
- 见.cursor/rules中的内容

