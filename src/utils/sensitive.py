"""数据脱敏工具函数。

对买家手机号、详细地址等敏感信息进行掩码处理，防止隐私数据出现在日志中。
"""

import re

# 手机号：11位数字，以1开头
_PHONE_RE = re.compile(r"(1[3-9]\d)\d{4}(\d{4})")

# 座机号：区号(3-4位)+号码(7-8位)，可含连字符
_LANDLINE_RE = re.compile(r"(\d{3,4}[-\s]?)\d{4,6}(\d{2,4})")

# 身份证：18位（最后一位可为X）
_ID_CARD_RE = re.compile(r"(\d{6})\d{8}(\d{3}[\dXx])")

# 银行卡：16-19位连续数字
_BANK_CARD_RE = re.compile(r"(\d{4})\d{8,11}(\d{4})")


def mask_phone(text: str) -> str:
    """将文本中的手机号中间4位替换为 ****。

    Args:
        text: 待脱敏的文本。

    Returns:
        脱敏后的文本。

    Examples:
        >>> mask_phone("联系我：13812345678")
        '联系我：138****5678'
    """
    return _PHONE_RE.sub(r"\1****\2", text)


def mask_address(address: str) -> str:
    """对详细地址进行部分遮掩，保留省市区，隐藏街道门牌号。

    策略：保留前8个字符（通常覆盖到区县级），其余替换为 ***。

    Args:
        address: 完整地址字符串。

    Returns:
        脱敏后的地址字符串。

    Examples:
        >>> mask_address("广东省深圳市南山区科技园路1号A栋201")
        '广东省深圳市南***'
    """
    if len(address) <= 6:
        return address[:3] + "***" if len(address) > 3 else "***"
    return address[:6] + "***"


def mask_id_card(text: str) -> str:
    """将文本中的身份证号中间8位替换为 ********。

    Args:
        text: 待脱敏的文本。

    Returns:
        脱敏后的文本。
    """
    return _ID_CARD_RE.sub(r"\1********\2", text)


def mask_bank_card(text: str) -> str:
    """将文本中的银行卡号中间位替换为 ****。

    Args:
        text: 待脱敏的文本。

    Returns:
        脱敏后的文本。
    """
    return _BANK_CARD_RE.sub(r"\1****\2", text)


def mask_sensitive(text: str) -> str:
    """对文本进行全量脱敏处理（手机号 + 身份证 + 银行卡）。

    适用于写入日志等场景的统一脱敏入口。

    Args:
        text: 待脱敏的文本。

    Returns:
        脱敏后的文本。
    """
    text = mask_phone(text)
    text = mask_id_card(text)
    text = mask_bank_card(text)
    return text
