# 简报 013——技能库快照抓取器

## 数据源侦察结论（已完成，无需重复侦察）

- 接口：GET https://jx3.unua.top/api/schools/data
- 返回：JSON，约 1.1MB，无鉴权、无 token、单次请求即全量
- 顶层结构：{"forces": [...22个门派], "source": {...}, "generatedAt": "ISO8601时间戳"}
  - generatedAt 每天凌晨 4:00（UTC）重建，可作为"数据是否更新"的判据
  - source 字段为上游出处（推栏官方 m.pvp.xoyo.com），落盘时必须保留
- 门派对象字段：name / forceId / qixueData（奇穴）/ skillData（技能）/ kungfuList（心法）
- 技能对象字段示例：skillName / weapon / distance / simpleDesc / desc / icon
- 验证锚点：门派数 = 22；技能"乱天狼"在全文出现 15 次（凌雪阁门派）
- 注意：该站为玩家自建，礼貌纪律——每天最多请求一次，本地缓存后一切查询只读本地文件
- 如接口实际返回与上述侦察结论不符，停止执行并报告差异，不得自行猜测适配

## 目标
- 每天拉取一次技能库的信息，以json格式存储至本地文件夹data/skill-info中
- 幂等：在已有的状态文件 data/state.json，记录已处理数据的唯一标识和首次处理时间
- 保留 generatedAt 和 source 两个字段，带 generatedAt 校验

## 环境
jx3-patch-radar 项目
- src存放代码文件 
- tests为函数测试用
- docs用来存放开发日志
- data用来存放技改信息抓取结果

## 限制
- 见AGENTS.md的铁律内容
- 见.cursor/rules中的内容

## 验收标准
- 门派数=22、乱天狼出现15次