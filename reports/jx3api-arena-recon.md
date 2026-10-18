# 简报018 执行结果：jx3api 名剑接口侦查

侦查日期：2026-10-18（以当前站点 https://www.jx3api.com 的在线 OpenAPI 文档为准）

## 改动边界与实际改动

- 计划改动：仅新建本报告 `reports/jx3api-arena-recon.md`
- 实际改动：同上；侦查过程的临时抓取文件放在既有草稿目录 `.tmp-recon/`（openapi.json、old-docs.md 等），未触碰 `src/`、`data/`、`tests/`
- 未改 `src/`，无需跑 pytest

## 问题一：`/arena/recent` 的 ticket 怎么获得？返回结构是什么？

### ticket 获取

官方文档对 ticket 的定义只有一句「推栏标识鉴权」（OpenAPI 参数描述），**官方不提供 ticket 的申请/发放渠道**——它不是 jx3api 站点的凭证，而是**剑网3官方助手「推栏」APP 的登录态标识**。社区通行的获取方式是抓包推栏 APP：

- 安卓模拟器装推栏 APP + 抓包工具，抓取 APP 请求中携带的 `ticket` 参数（推栏后端为 `m.pvp.xoyo.com` 系列接口），登录哪个游戏账号，ticket 就代表哪个身份（[二猫子机器人部署文档](https://doc.ermaozi.cn/doc/deploy/)：「通过抓包工具获取 ticket，安卓模拟器推栏token抓包」）。
- SDK 侧只是透传：`JX3API(token=..., ticket=...)` 或环境变量 `JX3API_TOKEN` / `JX3API_TICKET`（[jx3api-py](https://github.com/JX3API/jx3api-py) 源码 `jx3api.py:184-194`，`arena_recent` 同时有 `@require_token` 和 `@require_ticket` 装饰器）。

注意区分两个凭证，缺一不可：

| 凭证 | 含义 | 获取 |
|---|---|---|
| `token` | jx3api 站点访问令牌 | 站点首页「令牌」管理，LV.1 起；现为**付费次数包**（1000 次=10 元起，另有 5000 次/50 元、10000 次/100 元、30000 次/300 元档位） |
| `ticket` | 推栏 APP 登录态标识 | 抓包推栏 APP 获得 |

实测（2026-10-18，匿名）：

- `GET /arena/recent?server=梦江南&name=测试`（无 token）→ `{"code":401,"msg":"禁止访问，请提供 token"}`
- `GET /arena/awesome?...&token=fake&ticket=fake` → `{"code":401,"msg":"token 无效"}`

即鉴权顺序是先 token 后 ticket，无有效 LV.1 token 时连参数校验都走不到。

### 返回结构

现行 OpenAPI 只写了 `200 成功`，无响应 schema。结构以官方 TypeScript SDK 的类型定义（[JX3API-TS types.ts](https://github.com/JX3API/JX3API-TS/blob/main/src/types.ts) `ArenaRecentData`）与旧版文档（[2024 快照](https://web.archive.org/web/20240724072722/https://www.jx3api.com/static/docs/README.md) 名剑战绩一节）交叉确认：

```
data: {
  zoneName, serverName, roleName, roleId, globalRoleId,
  forceName, forceId, bodyName, bodyId,        # 门派/体型
  tongName, tongId, campName, campId,          # 帮会/阵营
  personName, personId, personAvatar,          # 推栏号主信息（旧文档样例有，TS 类型未列）
  performance: { "2v2": {...}, "3v3": {...}, "5v5": [...] },
    # 每个模式: { mmr, grade, ranking, winCount, totalCount, mvpCount, pvpType, winRate }
  history: [ { zone, server, avgGrade, totalMmr, mmr, kungfu,
               pvpType, won, mvp, startTime, endTime } ],   # 逐场对战记录
  trend: [ { matchDate, mmr, winRate } ]       # 指定 mode 时附加趋势（文档原文：指定模式时附趋势）
}
```

两处细节：TS 类型里全局 ID 字段叫 `globalId`，旧文档样例叫 `globalRoleId`，**以实际返回为准**（旧文档自己也有这句免责）；旧文档还警告：不传 `mode` 时返回的是推栏个人页全部角色战绩，可能出现非指定角色的数据。

## 问题二：`/arena/awesome` 的 limit 最大多少？能填 1000 吗？

**不能。当前官方 OpenAPI 文档写明 `limit` 上限是 100**（`minimum: 1, maximum: 100, default: 20`），且该接口**没有 offset/page 分页参数**——意味着一次最多拿榜单前 100 名，「前 200」用现行接口拿不到。

简报「已知信息」里「前 200 就是 limit=200」的说法来自 jx3api-py 的函数签名（`limit` 无上限声明、SDK 不做本地校验），与现行服务端文档冲突。由于无有效 token + ticket，无法实测服务端是硬拒还是静默截断到 100；以官方文档的 `maximum: 100` 为准。若确实需要前 200，需要另找数据源或向站主确认。

返回结构（`ArenaAwesomeItem[]`）：每条含 `zoneName / serverName / roleName / forceName / avatarUrl / rankNum / score / upNum / winRate`。

## 问题三：200+ 次连续调用会触发限流吗？

**官方文档（新旧两版）均未声明任何 QPS/频率限制，响应头里也没有 `X-RateLimit-*` 字段。**实测（2026-10-18，匿名打 LV0 免费接口 `/server/status/check`）：

- 60 并发突发（≈17 次/秒，3.5 秒打完）：60/60 全部 `code:200`
- 120 并发突发：120/120 全部 `code:200`，无一次 429；但总耗时 2 分 21 秒，响应被服务端明显排队拉长——即超载时服务端倾向「慢」而不是「拒」

结论与建议：

1. 「拉排行 + 逐人查战绩」200+ 次调用**不会触发硬性限流**，但没有任何官方承诺，建议自觉节流在 2~5 次/秒，并处理偶发慢响应。
2. 真正要算的不是限流而是**成本**：arena 系列接口需 LV.1 token，现行计费是按次的次数包（最低 10 元/1000 次，约 0.01 元/次）。200 次 ≈ 2 元，「拉一次全服排行再逐人刷战绩」的玩法如果做成日常任务，次数消耗 = 1 + 逐人查询数，按天累计。
3. 每角色战绩查询必须带 `server` + `name` 两个参数（`arena_recent(server, name, mode=0)`），没有按 roleId 直查的入口。

## 本次侦查依据清单

- 现行官方 OpenAPI 文档：`https://www.jx3api.com/openapi`（本地留存 `.tmp-recon/openapi.json`）
- 官方 SDK：[jx3api-py](https://github.com/JX3API/jx3api-py)、[JX3API-TS](https://github.com/JX3API/JX3API-TS)（types.ts 响应类型定义）
- 旧版文档快照（含 `/arena/recent` 完整返回样例）：[Wayback 2024-07-24](https://web.archive.org/web/20240724072722/https://www.jx3api.com/static/docs/README.md)（本地留存 `.tmp-recon/old-docs.md`）
- ticket 抓包获取法：[二猫子机器人部署文档](https://doc.ermaozi.cn/doc/deploy/)
- 站点实测记录：401 鉴权报错、60/120 并发无 429、无限速响应头（命令与输出见上文会话）
