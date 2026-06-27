"""管理后台单元测试：店铺 CRUD API + 仪表盘统计。

使用 httpx AsyncClient + FastAPI TestClient（内存 SQLite），不依赖真实 Redis。
"""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from admin.app import app
from admin.database import init_db, get_db
import aiosqlite


# ── 测试数据库 fixture ─────────────────────────────────────────────────────────

@pytest.fixture
async def test_db(tmp_path):
    """每个测试独立的临时 SQLite 数据库。"""
    db_file = tmp_path / "test_admin.db"

    async with aiosqlite.connect(db_file) as conn:
        conn.row_factory = aiosqlite.Row
        # 创建表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shops (
                shop_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                name TEXT NOT NULL,
                confidence_threshold INTEGER NOT NULL DEFAULT 85,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id TEXT NOT NULL,
                stat_date TEXT NOT NULL,
                total_sessions INTEGER NOT NULL DEFAULT 0,
                faq_hits INTEGER NOT NULL DEFAULT 0,
                llm_calls INTEGER NOT NULL DEFAULT 0,
                escalations INTEGER NOT NULL DEFAULT 0,
                UNIQUE(shop_id, stat_date)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                webhook_url TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                backend TEXT NOT NULL DEFAULT 'cloud',
                model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
                api_key TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
                max_tokens INTEGER NOT NULL DEFAULT 512,
                temperature REAL NOT NULL DEFAULT 0.3,
                timeout REAL NOT NULL DEFAULT 5.0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.commit()
        yield conn


@pytest.fixture
async def client(test_db):
    """使用临时数据库的 FastAPI 测试客户端。"""
    from admin.app import db_conn

    async def override_db():
        yield test_db

    app.dependency_overrides[db_conn] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

SHOP_PAYLOAD = {
    "shop_id": "tb_test_001",
    "platform": "taobao",
    "name": "测试灯具店",
    "api_key": "test_key",
    "api_secret": "test_secret",
    "confidence_threshold": 85,
    "enabled": True,
}


# ── CRUD 单元测试（直接测试 crud 模块）────────────────────────────────────────

class TestCrud:
    async def test_create_and_get_shop(self, test_db):
        from admin.crud import create_shop, get_shop
        from admin.schemas import ShopCreate
        data = ShopCreate(**SHOP_PAYLOAD)
        shop = await create_shop(test_db, data)
        assert shop.shop_id == "tb_test_001"
        assert shop.name == "测试灯具店"
        assert shop.enabled is True

        fetched = await get_shop(test_db, "tb_test_001")
        assert fetched is not None
        assert fetched.platform == "taobao"

    async def test_get_nonexistent_returns_none(self, test_db):
        from admin.crud import get_shop
        result = await get_shop(test_db, "nonexistent")
        assert result is None

    async def test_list_shops(self, test_db):
        from admin.crud import create_shop, list_shops
        from admin.schemas import ShopCreate
        for i in range(3):
            await create_shop(test_db, ShopCreate(
                shop_id=f"shop_{i:03d}",
                platform="taobao",
                name=f"店铺{i}",
            ))
        shops = await list_shops(test_db)
        assert len(shops) == 3

    async def test_update_shop(self, test_db):
        from admin.crud import create_shop, update_shop
        from admin.schemas import ShopCreate, ShopUpdate
        await create_shop(test_db, ShopCreate(**SHOP_PAYLOAD))
        updated = await update_shop(test_db, "tb_test_001", ShopUpdate(name="新店铺名"))
        assert updated.name == "新店铺名"
        assert updated.platform == "taobao"  # 未变

    async def test_update_nonexistent_returns_none(self, test_db):
        from admin.crud import update_shop
        from admin.schemas import ShopUpdate
        result = await update_shop(test_db, "nonexistent", ShopUpdate(name="x"))
        assert result is None

    async def test_delete_shop(self, test_db):
        from admin.crud import create_shop, delete_shop, get_shop
        from admin.schemas import ShopCreate
        await create_shop(test_db, ShopCreate(**SHOP_PAYLOAD))
        deleted = await delete_shop(test_db, "tb_test_001")
        assert deleted is True
        assert await get_shop(test_db, "tb_test_001") is None

    async def test_delete_nonexistent_returns_false(self, test_db):
        from admin.crud import delete_shop
        result = await delete_shop(test_db, "nonexistent")
        assert result is False

    async def test_update_empty_fields_unchanged(self, test_db):
        from admin.crud import create_shop, update_shop
        from admin.schemas import ShopCreate, ShopUpdate
        await create_shop(test_db, ShopCreate(**SHOP_PAYLOAD))
        # 空更新不应改变任何字段
        updated = await update_shop(test_db, "tb_test_001", ShopUpdate())
        assert updated.name == "测试灯具店"

    async def test_upsert_stat_creates_and_increments(self, test_db):
        from admin.crud import upsert_stat, get_dashboard_stats
        await upsert_stat(test_db, "shop_a", "2024-01-01", "faq_hits", 3)
        await upsert_stat(test_db, "shop_a", "2024-01-01", "faq_hits", 2)
        await upsert_stat(test_db, "shop_a", "2024-01-01", "total_sessions", 10)

        stats = await get_dashboard_stats(test_db, shop_id="shop_a", stat_date="2024-01-01")
        assert len(stats) == 1
        assert stats[0].faq_hits == 5
        assert stats[0].total_sessions == 10
        assert stats[0].faq_hit_rate == 0.5

    async def test_upsert_stat_invalid_field_raises(self, test_db):
        from admin.crud import upsert_stat
        with pytest.raises(ValueError, match="非法统计字段"):
            await upsert_stat(test_db, "shop_a", "2024-01-01", "invalid_field")

    async def test_dashboard_empty_returns_empty(self, test_db):
        from admin.crud import get_dashboard_stats
        stats = await get_dashboard_stats(test_db, stat_date="2099-01-01")
        assert stats == []


# ── API 端点测试 ───────────────────────────────────────────────────────────────

class TestShopAPI:
    async def test_create_shop_201(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            resp = await client.post("/shops", json=SHOP_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["shop_id"] == "tb_test_001"
        assert data["enabled"] is True

    async def test_create_duplicate_409(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)
            resp = await client.post("/shops", json=SHOP_PAYLOAD)
        assert resp.status_code == 409

    async def test_list_shops_empty(self, client):
        resp = await client.get("/shops")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_shops_after_create(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)
        resp = await client.get("/shops")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_shop_200(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)
        resp = await client.get("/shops/tb_test_001")
        assert resp.status_code == 200
        assert resp.json()["name"] == "测试灯具店"

    async def test_get_nonexistent_shop_404(self, client):
        resp = await client.get("/shops/nonexistent")
        assert resp.status_code == 404

    async def test_update_shop_200(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)
            resp = await client.put("/shops/tb_test_001", json={"name": "新名称", "confidence_threshold": 90})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "新名称"
        assert data["confidence_threshold"] == 90

    async def test_update_nonexistent_shop_404(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            resp = await client.put("/shops/nonexistent", json={"name": "x"})
        assert resp.status_code == 404

    async def test_delete_shop_204(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)
            resp = await client.delete("/shops/tb_test_001")
        assert resp.status_code == 204

    async def test_delete_nonexistent_shop_404(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            resp = await client.delete("/shops/nonexistent")
        assert resp.status_code == 404

    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestDashboardAPI:
    async def test_dashboard_empty(self, client):
        resp = await client.get("/dashboard", params={"date": "2099-01-01"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_dashboard_with_stats(self, test_db, client):
        from admin.crud import upsert_stat
        await upsert_stat(test_db, "shop_a", "2024-06-01", "total_sessions", 100)
        await upsert_stat(test_db, "shop_a", "2024-06-01", "faq_hits", 60)
        await upsert_stat(test_db, "shop_a", "2024-06-01", "llm_calls", 40)
        await upsert_stat(test_db, "shop_a", "2024-06-01", "escalations", 5)

        resp = await client.get("/dashboard", params={"date": "2024-06-01", "shop_id": "shop_a"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["faq_hits"] == 60
        assert data[0]["faq_hit_rate"] == 0.6

    async def test_notify_redis_called_on_create(self, client):
        notify_mock = AsyncMock()
        with patch("admin.app._notify_config_updated", notify_mock):
            await client.post("/shops", json=SHOP_PAYLOAD)
        notify_mock.assert_called_once_with("tb_test_001")

    async def test_notify_redis_called_on_update(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)

        notify_mock = AsyncMock()
        with patch("admin.app._notify_config_updated", notify_mock):
            await client.put("/shops/tb_test_001", json={"name": "new"})
        notify_mock.assert_called_once_with("tb_test_001")

    async def test_notify_redis_called_on_delete(self, client):
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.post("/shops", json=SHOP_PAYLOAD)

        notify_mock = AsyncMock()
        with patch("admin.app._notify_config_updated", notify_mock):
            await client.delete("/shops/tb_test_001")
        notify_mock.assert_called_once_with("tb_test_001")


class TestLLMConfigAPI:
    async def test_get_llm_config_defaults(self, client):
        """未配置时返回默认值。"""
        resp = await client.get("/llm-config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "gpt-4o-mini"
        assert data["api_key"] == ""
        assert data["base_url"] == "https://api.openai.com/v1"
        assert data["max_tokens"] == 512
        assert data["temperature"] == 0.3
        assert data["timeout"] == 5.0

    async def test_update_llm_config_model_and_key(self, client):
        """更新模型名和 API Key。"""
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            resp = await client.put(
                "/llm-config",
                json={"model": "qwen-turbo", "api_key": "sk-test-123"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "qwen-turbo"
        assert data["api_key"] == "sk-test-123"

    async def test_update_llm_config_partial(self, client):
        """部分更新只改指定字段，其余保持默认。"""
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.put("/llm-config", json={"temperature": 0.7})
        resp = await client.get("/llm-config")
        data = resp.json()
        assert data["temperature"] == 0.7
        assert data["model"] == "gpt-4o-mini"  # 未改变

    async def test_update_llm_config_base_url(self, client):
        """更新 base_url（用于通义千问、豆包等兼容接口）。"""
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            resp = await client.put(
                "/llm-config",
                json={"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
            )
        assert resp.status_code == 200
        assert resp.json()["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    async def test_update_llm_config_notifies_redis(self, client):
        """更新 LLM 配置后推送 config_updated。"""
        notify_mock = AsyncMock()
        with patch("admin.app._notify_config_updated", notify_mock):
            await client.put("/llm-config", json={"model": "gpt-4o"})
        notify_mock.assert_called_once_with("__llm_config__")

    async def test_update_llm_config_invalid_temperature(self, client):
        """temperature 超出范围返回 422。"""
        resp = await client.put("/llm-config", json={"temperature": 5.0})
        assert resp.status_code == 422


class TestAlertConfigAPI:
    async def test_get_alert_config_defaults(self, client):
        """未配置时返回空 webhook_url。"""
        resp = await client.get("/alert-config")
        assert resp.status_code == 200
        assert resp.json()["webhook_url"] == ""

    async def test_update_alert_config_webhook(self, client):
        """设置企业微信 Webhook 地址。"""
        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key"
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            resp = await client.put("/alert-config", json={"webhook_url": url})
        assert resp.status_code == 200
        assert resp.json()["webhook_url"] == url

    async def test_get_after_update_reflects_change(self, client):
        """更新后 GET 返回新值。"""
        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
        with patch("admin.app._notify_config_updated", new_callable=AsyncMock):
            await client.put("/alert-config", json={"webhook_url": url})
        resp = await client.get("/alert-config")
        assert resp.json()["webhook_url"] == url

    async def test_update_alert_config_notifies_redis(self, client):
        """更新告警配置后推送 config_updated。"""
        notify_mock = AsyncMock()
        with patch("admin.app._notify_config_updated", notify_mock):
            await client.put("/alert-config", json={"webhook_url": "https://example.com"})
        notify_mock.assert_called_once_with("__alert_config__")
