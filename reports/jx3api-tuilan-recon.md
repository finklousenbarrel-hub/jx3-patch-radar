# 简报019 执行结果（公开版）：jx3api 名剑接口实测结论

日期：2026-10-19。接简报018，本次拿到真实推栏 ticket 并完成实测。逆向过程与细节见 `personal-report/`（不进 git）。

## 结论速览

- `/arena/awesome`、`/arena/schools`、`/arena/recent` 三接口均可正常调用（LV.1 token + 推栏 ticket）
- **`/arena/awesome` 的 limit 上限 = 100，服务端硬校验**：limit=101/1000 → `400 参数 [limit] 应该小于或等于 [100]`，不是截断。且无分页参数，榜单最多拿前 100 名
- 四个 AstrBot jx3 插件（qsc20001102、muqing-kg ×2、CrystalSight）**全部不直调推栏后端**，都走 jx3api.com 中转，ticket 仅作参数透传

## ticket 获取结论

ticket 是推栏 APP 的登录态标识，官方不提供申请渠道，获取方式 = **抓包推栏 APP 请求头中的 `token`**。本次实测用 MuMu 模拟器 + Reqable 成功（Android 14 需额外处理系统证书目录，属通用安卓抓包知识）。密码登录被极验滑块拦截、短信登录对该账号返回验证码错误，均不可自动化。

## 接口实测结构（2026-10-19，真实数据）

### /arena/awesome（名剑排行）

```
GET /arena/awesome?mode=33&limit=100&token=***&ticket=*** → 200，恰好 100 条
```

每条字段（**实测以此为准**，与 TS SDK 类型定义有出入）：

```json
{"roleName": "惜别·梦江南", "forceName": "五毒", "avatarUrl": "https://qdla.pvp.xoyo.com/...",
 "rankNum": "1", "upNum": 20, "winRate": 71, "matchScore": "3229"}
```

注意：`roleName` 带区服后缀（`名字·服务器`），拆名字要自己处理；分数字段名是 `matchScore`（不是 TS 类型里的 `score`）；无 `zoneName/serverName` 字段。

### /arena/schools（门派统计）

```
GET /arena/schools?mode=33&token=***&ticket=*** → 200，20 条（每门派一条）
```

字段：`{forceName, thisWeek, lastWeek}` —— 该模式本周/上周竞技场场次数。

### /arena/recent（名剑战绩）

以榜内玩家实测（server=幽月轮， name=乌洛波洛斯， mode=33）：

- 身份字段：zoneName/serverName/roleName/`roleId`/**`globalId`**（现网字段名确认是 `globalId`，旧文档的 `globalRoleId` 已过时）/forceName/bodyName/tongName/campName 等
- `performance.3v3`：mmr / grade / ranking / winCount / totalCount / mvpCount / winRate
- `history`：20 场逐局记录（avgGrade、totalMmr、mmr 变化、kungfu、won、mvp、起止时间戳）
- `trend`：指定 mode 时附加（matchDate/mmr/winRate 走势）；不传 mode 时 performance 返回 5v5/2v2/3v3 三个键
- **空数据要容忍**：榜首玩家各 mode 下 performance/history 均为空数组（数据按周重置或玩家隐藏）

### /card/preset（简报中 role-card-preset 的对应物）

`role-card-preset` 在公开渠道查无此标识符；对应 jx3api 的 `/card/preset`：`GET ?server=&name=&ticket=&token=`，需 **LV.2** token，取角色推栏名片预设图与获赞数。

## 依据

- 实测原始响应留存：`.tmp-recon/arena-live.json`、`recent-live.json`、`recent-live2.json`、`live-test-019.json`（均不进 git）
- 简报018 报告：`reports/jx3api-arena-recon.md`
