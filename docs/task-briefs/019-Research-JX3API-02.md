# 简报019 jx3api接口二次侦查

## 目标：
侦查网站：
    https://www.jx3api.com/
    https://github.com/JX3API/jx3api-py
回答以下问题：
    从下载的 JS chunk 里搜 role-card-preset 的调用代码，看它带什么参数
    翻二猫子机器人、astrbot jx3 插件的源码——它们都直调推栏后端，代码里就写着 m.pvp.xoyo.com 的接口路径和参数格式
        重点找：角色详情/配装/奇穴对应的接口路径
        纯读代码，不发请求，零风险
        需要登录推栏则直接请求我发给你推栏账号和密码
    awesome/schools 进行测试（在获取ticket之后）
        api_key见环境变量


## 限制
- 见AGENTS.md的铁律内容
- 见.cursor/rules中的内容
