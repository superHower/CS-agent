"""配置加载与热更新单元测试。"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.config.settings import (
    Config,
    ShopConfig,
    _CONFIG_PATH,
    get_config,
    reload_config,
)
from src.contracts import Platform


# ── 辅助 fixture ──────────────────────────────────────────────────────────────

MINIMAL_YAML = {
    "redis": {"host": "127.0.0.1", "port": 6379},
    "shops": [
        {
            "shop_id": "tb_test_001",
            "platform": "taobao",
            "name": "测试店铺",
        }
    ],
}

TWO_SHOPS_YAML = {
    "shops": [
        {
            "shop_id": "tb_test_001",
            "platform": "taobao",
            "name": "淘宝测试",
            "enabled": True,
        },
        {
            "shop_id": "pdd_test_001",
            "platform": "pinduoduo",
            "name": "拼多多测试",
            "enabled": False,
        },
    ]
}


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """每个测试前重置配置单例，避免测试间相互污染。"""
    import src.config.settings as settings_module
    original = settings_module._config
    settings_module._config = None
    yield
    settings_module._config = original


@pytest.fixture
def tmp_yaml(tmp_path: Path):
    """创建临时 YAML 配置文件，返回写入函数和文件路径。"""
    yaml_file = tmp_path / "settings.yaml"

    def write(data: dict) -> Path:
        with open(yaml_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        return yaml_file

    return write


# ── ShopConfig 验证 ───────────────────────────────────────────────────────────

class TestShopConfig:
    def test_valid_shop(self):
        shop = ShopConfig(
            shop_id="tb_lamp_001",
            platform=Platform.TAOBAO,
            name="灯具店铺",
        )
        assert shop.shop_id == "tb_lamp_001"
        assert shop.enabled is True
        assert shop.confidence_threshold == 85

    def test_invalid_shop_id_no_underscore(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="shop_id 格式无效"):
            ShopConfig(
                shop_id="invalidid",
                platform=Platform.TAOBAO,
                name="test",
            )

    def test_invalid_shop_id_empty(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ShopConfig(
                shop_id="",
                platform=Platform.TAOBAO,
                name="test",
            )

    def test_confidence_threshold_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ShopConfig(
                shop_id="tb_x_001",
                platform=Platform.TAOBAO,
                name="test",
                confidence_threshold=150,
            )


# ── Config.from_yaml ──────────────────────────────────────────────────────────

class TestConfigFromYaml:
    def test_load_minimal_yaml(self, tmp_yaml):
        path = tmp_yaml(MINIMAL_YAML)
        config = Config.from_yaml(path)
        assert config.redis.host == "127.0.0.1"
        assert len(config.shops) == 1
        assert config.shops[0].shop_id == "tb_test_001"

    def test_load_two_shops(self, tmp_yaml):
        path = tmp_yaml(TWO_SHOPS_YAML)
        config = Config.from_yaml(path)
        assert len(config.shops) == 2

    def test_default_values_applied(self, tmp_yaml):
        path = tmp_yaml({"shops": []})
        config = Config.from_yaml(path)
        assert config.thresholds.default_confidence == 85
        assert config.llm.timeout == 5.0
        assert config.redis.port == 6379

    def test_escalation_keywords_default(self, tmp_yaml):
        path = tmp_yaml({})
        config = Config.from_yaml(path)
        assert "投诉" in config.escalation_keywords
        assert "12315" in config.escalation_keywords

    def test_env_var_substitution(self, tmp_yaml, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "secret_key_123")
        data = {
            "shops": [
                {
                    "shop_id": "tb_test_001",
                    "platform": "taobao",
                    "name": "测试",
                    "api_key": "${TEST_API_KEY}",
                }
            ]
        }
        path = tmp_yaml(data)
        config = Config.from_yaml(path)
        assert config.shops[0].api_key == "secret_key_123"

    def test_missing_env_var_becomes_empty_string(self, tmp_yaml):
        data = {
            "shops": [
                {
                    "shop_id": "tb_test_001",
                    "platform": "taobao",
                    "name": "测试",
                    "api_key": "${NONEXISTENT_VAR}",
                }
            ]
        }
        path = tmp_yaml(data)
        config = Config.from_yaml(path)
        assert config.shops[0].api_key == ""


# ── get_config 单例 ───────────────────────────────────────────────────────────

class TestGetConfig:
    def test_returns_singleton(self, tmp_yaml):
        path = tmp_yaml(MINIMAL_YAML)
        with patch("src.config.settings._CONFIG_PATH", path):
            c1 = get_config()
            c2 = get_config()
            assert c1 is c2

    def test_singleton_initialized_once(self, tmp_yaml):
        path = tmp_yaml(MINIMAL_YAML)
        call_count = 0
        original_from_yaml = Config.from_yaml

        def counting_from_yaml(p=path):
            nonlocal call_count
            call_count += 1
            return original_from_yaml(p)

        with patch.object(Config, "from_yaml", side_effect=counting_from_yaml):
            with patch("src.config.settings._CONFIG_PATH", path):
                get_config()
                get_config()
                get_config()
        assert call_count == 1


# ── get_shop / enabled_shops ──────────────────────────────────────────────────

class TestConfigHelpers:
    def test_get_shop_found(self, tmp_yaml):
        path = tmp_yaml(TWO_SHOPS_YAML)
        config = Config.from_yaml(path)
        shop = config.get_shop("tb_test_001")
        assert shop is not None
        assert shop.name == "淘宝测试"

    def test_get_shop_not_found(self, tmp_yaml):
        path = tmp_yaml(MINIMAL_YAML)
        config = Config.from_yaml(path)
        assert config.get_shop("nonexistent_shop") is None

    def test_enabled_shops_filters_disabled(self, tmp_yaml):
        path = tmp_yaml(TWO_SHOPS_YAML)
        config = Config.from_yaml(path)
        enabled = config.enabled_shops()
        assert len(enabled) == 1
        assert enabled[0].shop_id == "tb_test_001"


# ── reload_config 热更新 ──────────────────────────────────────────────────────

def _make_db_shops(shops_yaml: list[dict]):
    """从 YAML dict 列表构建 ShopConfig 列表（模拟 SQLite 返回）。"""
    return [ShopConfig(**s) for s in shops_yaml]


class TestReloadConfig:
    async def test_reload_updates_singleton(self, tmp_yaml):
        import src.config.settings as settings_module

        path = tmp_yaml(MINIMAL_YAML)
        settings_module._config = Config.from_yaml(path)
        assert len(settings_module._config.shops) == 1

        # 模拟 SQLite 返回两个店铺
        db_shops = _make_db_shops(TWO_SHOPS_YAML["shops"])
        with patch("src.config.settings._load_shops_from_db", AsyncMock(return_value=db_shops)):
            new_path = tmp_yaml(TWO_SHOPS_YAML)
            await reload_config(new_path)

        assert settings_module._config is not None
        assert len(settings_module._config.shops) == 2

    async def test_reload_is_atomic(self, tmp_yaml):
        """并发 reload 不会产生竞态，最终结果一致。"""
        import src.config.settings as settings_module

        path = tmp_yaml(MINIMAL_YAML)
        settings_module._config = Config.from_yaml(path)

        db_shops = _make_db_shops(TWO_SHOPS_YAML["shops"])
        new_path = tmp_yaml(TWO_SHOPS_YAML)

        # 并发执行多次 reload
        with patch("src.config.settings._load_shops_from_db", AsyncMock(return_value=db_shops)):
            await asyncio.gather(*[reload_config(new_path) for _ in range(5)])

        assert settings_module._config is not None
        assert len(settings_module._config.shops) == 2
