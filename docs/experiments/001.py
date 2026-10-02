import requests

resp = requests.get("https://www.jx3api.com/news/records?limit=50")
data = resp.json()

# 第一步：先摸清结构——看看返回的字典有哪些 key
print(data.keys())

records = data["data"]
print(records[0].keys())

for r in records:
    print(r.get("date"), "|", r.get("title"))