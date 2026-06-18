"""日志与工具模块单元测试。"""

import asyncio
import logging
from pathlib import Path

import pytest

from src.utils.sensitive import (
    mask_address,
    mask_bank_card,
    mask_id_card,
    mask_phone,
    mask_sensitive,
)
from src.utils.trace import (
    clear_trace_id,
    get_trace_id,
    new_trace_id,
    set_trace_id,
)


# ── trace_id ──────────────────────────────────────────────────────────────────

class TestTraceId:
    def setup_method(self):
        clear_trace_id()

    def test_default_empty(self):
        assert get_trace_id() == ""

    def test_set_and_get(self):
        set_trace_id("abc123")
        assert get_trace_id() == "abc123"

    def test_new_trace_id_returns_hex(self):
        tid = new_trace_id()
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)

    def test_new_trace_id_updates_context(self):
        tid = new_trace_id()
        assert get_trace_id() == tid

    def test_clear_resets_to_empty(self):
        set_trace_id("some_id")
        clear_trace_id()
        assert get_trace_id() == ""

    def test_unique_trace_ids(self):
        tid1 = new_trace_id()
        tid2 = new_trace_id()
        assert tid1 != tid2

    async def test_async_context_isolation(self):
        """不同协程拥有独立的 trace_id 上下文。"""
        results = {}

        async def task_a():
            set_trace_id("task_a_id")
            await asyncio.sleep(0)
            results["a"] = get_trace_id()

        async def task_b():
            set_trace_id("task_b_id")
            await asyncio.sleep(0)
            results["b"] = get_trace_id()

        await asyncio.gather(task_a(), task_b())
        # 每个任务在自己的协程上下文中，互不干扰
        assert results["a"] == "task_a_id"
        assert results["b"] == "task_b_id"


# ── mask_phone ────────────────────────────────────────────────────────────────

class TestMaskPhone:
    def test_basic_phone(self):
        assert mask_phone("13812345678") == "138****5678"

    def test_phone_in_sentence(self):
        result = mask_phone("请联系 13812345678 咨询")
        assert "138****5678" in result
        assert "1234" not in result

    def test_multiple_phones(self):
        text = "电话1：13812345678，电话2：15987654321"
        result = mask_phone(text)
        assert "138****5678" in result
        assert "159****4321" in result

    def test_no_phone_unchanged(self):
        text = "没有手机号的文本"
        assert mask_phone(text) == text

    def test_all_phone_prefixes(self):
        phones = ["13312345678", "14512345678", "15012345678",
                  "16612345678", "17712345678", "18812345678", "19912345678"]
        for phone in phones:
            result = mask_phone(phone)
            assert "****" in result
            assert phone not in result


# ── mask_address ──────────────────────────────────────────────────────────────

class TestMaskAddress:
    def test_long_address(self):
        addr = "广东省深圳市南山区科技园路1号A栋201"
        result = mask_address(addr)
        assert result.endswith("***")
        assert len(result) < len(addr)

    def test_short_address(self):
        result = mask_address("北京市")
        assert "***" in result

    def test_very_short_address(self):
        result = mask_address("京")
        assert "***" in result

    def test_exactly_6_chars(self):
        addr = "广东省深圳市"
        result = mask_address(addr)
        # 恰好6字符，走短地址分支，保留前3字符+***
        assert result == "广东省***"


# ── mask_id_card ──────────────────────────────────────────────────────────────

class TestMaskIdCard:
    def test_basic_id_card(self):
        result = mask_id_card("身份证：440301199001011234")
        assert "19900101" not in result
        assert "440301" in result
        assert "1234" in result

    def test_no_id_card_unchanged(self):
        text = "没有身份证的文本"
        assert mask_id_card(text) == text


# ── mask_bank_card ────────────────────────────────────────────────────────────

class TestMaskBankCard:
    def test_16_digit_card(self):
        result = mask_bank_card("卡号：6222021234567890")
        assert "****" in result
        assert "6222" in result
        assert "7890" in result

    def test_no_bank_card_unchanged(self):
        text = "没有银行卡号"
        assert mask_bank_card(text) == text


# ── mask_sensitive 组合 ───────────────────────────────────────────────────────

class TestMaskSensitive:
    def test_combined_sensitive_info(self):
        text = "手机：13812345678，身份证：440301199001011234"
        result = mask_sensitive(text)
        assert "13812345678" not in result
        assert "199001" not in result
        assert "138****5678" in result

    def test_empty_string(self):
        assert mask_sensitive("") == ""

    def test_no_sensitive_info(self):
        text = "这是普通文本，没有敏感信息。"
        assert mask_sensitive(text) == text


# ── logger ────────────────────────────────────────────────────────────────────

class TestLogger:
    def test_get_logger_returns_adapter(self):
        from src.utils.logger import get_logger
        logger = get_logger(__name__, shop_id="tb_test_001")
        assert isinstance(logger, logging.LoggerAdapter)

    def test_setup_logging_idempotent(self, tmp_path):
        import src.utils.logger as logger_module
        logger_module._setup_done = False  # 重置

        from src.utils.logger import setup_logging

        root = logging.getLogger()
        before_count = len(root.handlers)

        setup_logging(log_dir=tmp_path)
        after_first = len(root.handlers)

        setup_logging(log_dir=tmp_path)  # 第二次调用不应再添加 handler
        after_second = len(root.handlers)

        # 第一次调用增加了 handler，第二次调用因幂等保护不再增加
        assert after_second == after_first

        logger_module._setup_done = False  # 清理
        # 移除本次测试添加的 handler，恢复到 before_count
        root.handlers = root.handlers[:before_count]

    def test_log_emits_message(self, tmp_path, caplog):
        import src.utils.logger as logger_module
        logger_module._setup_done = False

        from src.utils.logger import get_logger, setup_logging
        setup_logging(level="DEBUG", log_dir=tmp_path)

        logger = get_logger("test.module", shop_id="tb_test_001")
        with caplog.at_level(logging.INFO):
            logger.info("测试日志消息")

        assert any("测试日志消息" in r.message for r in caplog.records)

        logger_module._setup_done = False
        logging.getLogger().handlers.clear()
