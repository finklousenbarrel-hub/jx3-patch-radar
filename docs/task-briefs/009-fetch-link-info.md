# 简报 009：技改信息进一步获取


## 目标：
- 新建 src/fecth_link_info.py，读取 data/patches/*.json中的notes里的所有网页链接，并抓取网页链接中的内容，以txt格式存储进data/extr_info文件夹中

## 环境
jx3-patch-radar 项目
- src存放代码文件 
  src/fetch_news.py用于抓取公告并储存为txt格式文件
  src/parse_patch.py用于将txt文件中的内容解析为json格式
- tests为函数测试用
- docs用来存放开发日志
- data用来存放技改信息抓取结果

## 限制：
- 参照.cursor/rules中的内容

## 验收标准：
- 成功获取所有21个门派的技改链接并存储至本地，标题为“9月8日“苍生铸世”资料片首轮武学调整-门派”，共计21个
