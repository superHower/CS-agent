"""RPA 聊天记录解析器。

影刀 RPA 机器人抓取的聊天记录是字符串数组，每个元素是一个"气泡"，包含
发送者标记、时间戳、已读状态等杂项文本。本模块负责从中提取：
- 买家最新一条消息（待回复）
- 对话历史（供 LLM 上下文）

各平台气泡格式不同，通过平台特定规则识别发送者角色。
"""

import re
from dataclasses import dataclass, field

# ── 抖音系统消息过滤 ───────────────────────────────────────────────────────────

_DOUYIN_SYSTEM_KEYWORDS = {
    "系统消息", "系统自动发送", "机器人发送", "机器人接待中",
    "用户超时未回复，系统关闭会话", "平台已自动同意", "售后小助手",
    "系统自动同意", "消费者正在查看订单", "平台主动处理",
    "邀请下单", "商家配置发送", "系统关闭会话",
    "当前会话已长时间未回复", "退款成功", "同意退款",
    "支付提醒", "订单已关闭", "消费者催发货",
    "从历史会话发起会话", "平台已自动同意补寄",
    "用户仍在等待您的处理结果",
}


def is_system_message(message: str, kefu: str) -> bool:
    """判断气泡是否为系统消息（抖音平台专用）。

    判断规则：
    1. 空/非字符串 → system
    2. 包含 "智能客服\\n" → system
    3. 含 kefu：开头 "客服{kefu}接入" 或后面跟"撤回" → system
    4. 单行系统关键词 → system
    5. 首行或全文含系统关键词 → system
    """
    if not isinstance(message, str) or not message.strip():
        return True

    if "智能客服\n" in message or "\n智能客服\n" in message:
        return True

    if kefu and kefu in message:
        idx = message.index(kefu)
        after = message[idx + len(kefu):].strip()

        if message.startswith("客服" + kefu + "接入"):
            return True
        if after in ("撤回了一条消息", "撤回了一条消息，已被编辑"):
            return True

    if "\n" not in message:
        single_keywords = {
            "从历史会话发起会话", "消费者催发货", "平台已自动同意补寄",
            "机器人接待中",
        }
        if any(message.startswith(kw) for kw in single_keywords):
            return True

    first_line = message.split("\n")[0]
    if first_line in _DOUYIN_SYSTEM_KEYWORDS or any(kw in message for kw in _DOUYIN_SYSTEM_KEYWORDS):
        return True

    return False


def filter_douyin_bubbles(raw_list: list[str], kefu: str) -> list[str]:
    """过滤抖音气泡数组，去除系统消息气泡。

    返回过滤后的字符串数组（原始文本，不做角色分类）。
    """
    return [item for item in raw_list if not is_system_message(item, kefu)]


# ── 角色识别正则 ──────────────────────────────────────────────────────────────

# 客服气泡特征（不区分大小写）
_AGENT_PATTERNS = [
    re.compile(r"智能客服"),
    re.compile(r"客服\S*发送"),
    re.compile(r"抖音电商智能客服发送"),
    re.compile(r"已读\s*$"),  # 以"已读"结尾通常是客服发出的气泡
    re.compile(r"客服\S*接入"),  # "客服清博照明运营接入"
    re.compile(r"运营接入"),
    re.compile(r"清博照明运营"),
]

# 系统通知气泡特征（不参与对话）
_SYSTEM_PATTERNS = [
    re.compile(r"当前会话已长时间未回复"),
    re.compile(r"用户超时未回复"),
    re.compile(r"系统关闭会话"),
    re.compile(r"平台可能主动介入"),
]

# 时间戳行（独立行形如 "昨天 12:29" 或 "今天 09:00"）
_TIMESTAMP_LINE_RE = re.compile(r"^(昨天|今天|前天|\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2})")

# 气泡内行级时间戳（如 "昨天 12:29:05" 在消息文本中）
_INLINE_TIMESTAMP_RE = re.compile(r"(昨天|今天|前天)\s*\d{1,2}:\d{2}(:\d{2})?")

# 商品卡片特征（不是买家消息）
_PRODUCT_CARD_PATTERNS = [
    re.compile(r"^¥\s*\d"),
    re.compile(r"节能环保"),
    re.compile(r"柔光护眼"),
    re.compile(r"无极调光"),
]


@dataclass
class ParsedTurn:
    """解析出的单条对话轮次。"""

    role: str  # "user" | "assistant" | "system"
    content: str  # 清洗后的文本内容


def _clean_bubble(text: str) -> str:
    """清洗气泡文本，去除时间戳行、已读状态等杂项。"""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 去掉纯时间戳行
        if _TIMESTAMP_LINE_RE.match(line):
            continue
        # 去掉 "已读" / "未读" 独立行
        if line in ("已读", "未读"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _classify_bubble(text: str) -> str:
    """判断气泡属于哪个角色。

    Returns:
        "user" | "assistant" | "system"
    """
    for pat in _SYSTEM_PATTERNS:
        if pat.search(text):
            return "system"
    for pat in _AGENT_PATTERNS:
        if pat.search(text):
            return "assistant"
    # 商品卡片归为 assistant（客服推送的商品）
    for pat in _PRODUCT_CARD_PATTERNS:
        if pat.search(text):
            return "assistant"
    return "user"


def parse_chat_bubbles(bubbles: list[str]) -> list[ParsedTurn]:
    """将聊天记录气泡数组解析为结构化对话轮次列表。

    Args:
        bubbles: RPA 抓取的字符串数组，每个元素是一个聊天气泡。

    Returns:
        ParsedTurn 列表，system 气泡已过滤，role 为 "user" 或 "assistant"。
    """
    turns: list[ParsedTurn] = []
    for bubble in bubbles:
        role = _classify_bubble(bubble)
        if role == "system":
            continue
        content = _clean_bubble(bubble)
        # 清洗后移除客服身份标记行（如 "智能客服"、"清博照明运营"）
        if role == "assistant":
            content = _remove_agent_header(content)
        if not content:
            continue
        turns.append(ParsedTurn(role=role, content=content))
    return turns


def _remove_agent_header(text: str) -> str:
    """移除客服气泡开头的角色标记行（如 "智能客服" 单独一行）。"""
    lines = text.splitlines()
    if lines and re.fullmatch(r"智能客服|清博照明运营|\S*客服\S*", lines[0].strip()):
        lines = lines[1:]
    return "\n".join(lines).strip()


def extract_latest_buyer_message(bubbles: list[str]) -> str | None:
    """从气泡数组中提取买家最新一条消息。

    RPA 触发时机是买家刚发了新消息，因此最后一条 user 气泡即为待回复消息。

    Args:
        bubbles: RPA 抓取的字符串数组。

    Returns:
        买家最新消息文本，若无法提取则返回 None。
    """
    turns = parse_chat_bubbles(bubbles)
    for turn in reversed(turns):
        if turn.role == "user":
            return turn.content
    return None


@dataclass
class RpaSessionData:
    """从 RPA JSON payload 解析出的会话数据。"""

    platform: str  # 平台名称（中文，如"淘宝"）
    shop: str  # 店铺名称
    buyer: str  # 买家昵称
    product: str  # 商品名（"无"时为空字符串）
    bubbles: list[str]  # 原始 chatList 气泡数组
    detail: str  # 订单详情（"无"时为空字符串）
    kefu: str  # 客服名字
    latest_buyer_message: str | None  # 解析出的买家最新消息
    history_turns: list[ParsedTurn]  # 对话历史（不含最新消息）
    # ── 过滤后气泡（系统消息已移除，供 MatchEngine 直接使用）───────────────────
    filtered_bubbles: list[str] = field(default_factory=list)
    # ── 分类标签（从 RPA JSON 的 category 字段读取，没有则由 infer_category 推断）───
    category: str = ""


# ── 店铺分类关键词推断 ─────────────────────────────────────────────────────────

# 关键词到分类标签的映射（优先精确匹配商品名词）
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "灯具": ["灯", "灯泡", "灯具", "吸顶灯", "吊灯", "台灯", "壁灯", "灯带", "射灯", "筒灯", "落地灯", "led灯", "灯饰", "光源", "灯管"],
    "内衣": ["内衣", "文胸", "胸罩", "内裤", "背心", "吊带", "塑身", "保暖内衣", "无钢圈", "聚拢", "文胸", "内衣套装"],
    "数码": ["手机", "电脑", "平板", "笔记本", "相机", "耳机", "音箱", "键盘", "鼠标", "充电器", "数据线", "移动电源", "存储卡", "智能手环", "智能手表", "无人机", "游戏机"],
    "服装": ["衣服", "T恤", "衬衫", "裤子", "裙子", "外套", "羽绒服", "大衣", "卫衣", "毛衣", "牛仔裤", "休闲裤", "西装", "运动服", "连衣裙"],
    "美妆": ["口红", "眼影", "粉底", "护肤", "面膜", "洗面奶", "水乳", "精华", "防晒", "眉笔", "睫毛膏", "香水", "卸妆", "妆前乳", "遮瑕"],
    "食品": ["零食", "坚果", "饼干", "糖果", "巧克力", "薯片", "肉脯", "蜜饯", "咖啡", "茶叶", "饮料", "牛奶", "酸奶", "水果", "罐头"],
    "家居": ["家具", "沙发", "床", "衣柜", "桌椅", "床垫", "窗帘", "地毯", "抱枕", "收纳", "置物架", "鞋柜", "电视柜", "书柜"],
    "母婴": ["奶粉", "纸尿裤", "婴儿车", "奶瓶", "童装", "玩具", "婴儿床", "妈咪包", "吸奶器", "儿童座椅", "爬行垫"],
    "家电": ["空调", "冰箱", "洗衣机", "电视", "微波炉", "电饭煲", "电磁炉", "吹风机", "吸尘器", "电风扇", "加湿器", "空气净化器", "饮水机", "榨汁机"],
}


def _infer_category(shop_name: str, product_name: str) -> str:
    """从店铺名或商品名中推断分类标签。

    优先匹配商品名词（更精确），其次匹配店铺名。
    返回最匹配的分类名，无匹配时返回空字符串。
    """
    # 拼接搜索文本，店铺名+商品名
    text = f"{shop_name} {product_name}".lower()

    best_match = ""
    best_count = 0
    for category, keywords in _CATEGORY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text)
        if count > best_count:
            best_count = count
            best_match = category

    return best_match


def parse_rpa_json(payload: dict, max_history: int = 6) -> RpaSessionData | None:
    """解析 RPA 推入的 JSON payload，提取最新会话数据。

    RPA payload 格式：
    {
        "history": [
            {
                "platform": "淘宝",
                "shop": "艾睿斯旗舰店",
                "buyer": "买家昵称",
                "product": "商品名或无",
                "chatList": ["气泡1", "气泡2", ...],
                "detail": "订单详情文本或无"
            },
            ...  # RPA 每次推一个会话项目，取 history[-1]
        ]
    }

    Args:
        payload: RPA 推入的完整 JSON 对象。
        max_history: 最多保留的历史轮数。

    Returns:
        RpaSessionData，或 None（payload 格式非法时）。
    """
    history = payload.get("history")
    if not history or not isinstance(history, list):
        return None

    session = history[-1]
    if not isinstance(session, dict):
        return None

    platform = str(session.get("platform", "")).strip()
    shop = str(session.get("shop", "")).strip()
    buyer = str(session.get("buyer", "")).strip()

    # product/detail 字段为"无"时归一化为空字符串
    product_raw = str(session.get("product", "")).strip()
    product = "" if product_raw in ("无", "none", "") else product_raw

    detail_raw = str(session.get("detail", "")).strip()
    detail = "" if detail_raw in ("无", "none", "") else detail_raw

    chat_list = session.get("chatList", [])
    if not isinstance(chat_list, list):
        chat_list = []
    bubbles = [str(b) for b in chat_list]

    # kefu 直接从 RPA JSON 读取
    kefu = str(session.get("kefu", "")).strip()

    # category 优先从 RPA JSON 读取，未提供则由商品/店铺名推断
    category_raw = str(session.get("category", "")).strip()
    inferred_category = _infer_category(shop, product) if not category_raw else ""
    final_category = category_raw if category_raw else inferred_category

    # 抖音平台：过滤系统消息气泡
    is_douyin = platform == "抖音"
    filtered_bubbles = filter_douyin_bubbles(bubbles, kefu) if is_douyin else bubbles

    latest_msg = extract_latest_buyer_message(filtered_bubbles)
    history_turns = extract_history_turns(filtered_bubbles, max_turns=max_history)

    return RpaSessionData(
        platform=platform,
        shop=shop,
        buyer=buyer,
        product=product,
        bubbles=bubbles,
        detail=detail,
        kefu=kefu,
        latest_buyer_message=latest_msg,
        history_turns=history_turns,
        filtered_bubbles=filtered_bubbles,
        category=final_category,
    )


def extract_history_turns(bubbles: list[str], max_turns: int = 6) -> list[ParsedTurn]:
    """提取对话历史（不含最后一条买家消息，因为那条是当前待回复的消息）。

    Args:
        bubbles: RPA 抓取的字符串数组。
        max_turns: 最多保留多少轮历史（从最新往前算）。

    Returns:
        ParsedTurn 列表，最多 max_turns 条，按时间正序排列。
    """
    turns = parse_chat_bubbles(bubbles)
    # 找到最后一条 user 消息的索引，历史是它之前的内容
    last_user_idx = -1
    for i in range(len(turns) - 1, -1, -1):
        if turns[i].role == "user":
            last_user_idx = i
            break
    if last_user_idx <= 0:
        return []
    history = turns[:last_user_idx]
    # 取最近 max_turns 条
    return history[-max_turns:]
