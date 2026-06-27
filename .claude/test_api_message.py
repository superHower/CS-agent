import json
import urllib.request

payload = {
    "platform": "抖音",
    "shop": "抖音艾睿斯旗舰店",
    "kefu": "清博照明运营",
    "buyer": "芬达",
    "product": "无",
    "chatList": [
        "6月14日16: 21\n用户超时未回复，系统关闭会话",
        "6月17日13: 10\n机器人接待中",
        "订单号6953495324704314513\n已完成\n客厅吸顶灯2026新款超薄LED现代简约大气房间卧室大厅灯中山灯具\n共1件，总价¥67.00\n代客发起售后\n发售后卡\n发物流卡\n邀评\n6月17日13: 10: 44",
        "发哪里去了\n6月17日13: 10: 50",
        "智能客服\n看到订单啦～您说『发哪里』是灯条没找到、安装材料没收到，还是刚才说按原地址寄出的主灯呀，帮您核对物流细节～\n6月17日13: 10: 57\n已读\n抖音电商智能客服发送",
        "灯条\n6月17日13: 11: 09",
        "转人工\n6月17日13: 11: 11"
    ],
    "detail": "无"
}

data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:8080/api/message",
    data=data,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=45) as resp:
        body = resp.read().decode("utf-8")
        print("STATUS:", resp.status)
        print("BODY:", body)
except urllib.error.HTTPError as e:
    print("STATUS:", e.code)
    print("BODY:", e.read().decode("utf-8"))
