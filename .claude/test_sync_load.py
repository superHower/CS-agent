import sys
sys.path.insert(0, r'd:\MyWork\project-agent\code\CS-agent')

# 模拟 dispatcher._load_keywords_from_db 内部逻辑
def load_keywords_sync(category_id, shop_id):
    """完全照抄 dispatcher.py:168-181"""
    try:
        import asyncio
        from admin.crud import load_escalation_keywords
        from admin.database import get_db
        loop = asyncio.get_event_loop()
        conn = loop.run_until_complete(get_db())
        try:
            return loop.run_until_complete(load_escalation_keywords(conn, category_id, shop_id))
        finally:
            loop.run_until_complete(conn.close())
    except Exception as exc:
        print('EXCEPTION caught in _load_keywords_from_db:')
        import traceback
        traceback.print_exc()
        return []

# 模拟在 FastAPI 异步上下文里调用（已经有了 event loop）
import asyncio

async def run_in_async_ctx():
    print('Inside async context, calling _load_keywords_from_db (sync)...')
    result = load_keywords_sync('lamp_store', '104b9a596a97')
    print('Result:', result)

# 注意：在已有 event loop 里运行 get_event_loop + run_until_complete 通常会失败
try:
    asyncio.run(run_in_async_ctx())
except Exception as e:
    print('Top-level exception:', e)
