# 简报018 jx3api接口侦查

## 目标：
侦查网站：
    https://github.com/JX3API/jx3api-py
    https://github.com/JX3API/jx3api-py
回答以下问题：
    https://www.jx3api.com/arena/recent 该接口下所需的ticket字段该如何获得 返回的数据结构是什么
    https://www.jx3api.com/arena/awesome 该接口的limit参数最大为多少 可以填1000吗
    频率限制："拉排行 + 逐人查战绩"一次要 200+ 次调用，会不会触发限流？限速多少？

## 已知信息
- jx3api-py 侦察结果
    基本信息：官方账号发的（JX3API 组织），6 stars，最近更新 2026-07，单文件 947 行，依赖只有 httpx。
    鉴权：JX3API(token=..., ticket=...)，还会自动读环境变量 JX3API_TOKEN / JX3API_TICKET
    名剑三接口签名全确认：
        arena_awesome(mode=33, limit=20) ← limit 参数存在，前 200 就是 limit=200
        arena_recent(server, name, mode=0) ← 必须带区服+角色名
        arena_schools(mode=33) ← 门派统计
    错误处理：自带 APIError(code, msg) 异常，权限不够会直接抛带错误码的异常

## 限制
- 见AGENTS.md的铁律内容
- 见.cursor/rules中的内容
