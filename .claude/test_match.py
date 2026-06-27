import asyncio
import sys
sys.path.insert(0, r'd:\MyWork\project-agent\code\CS-agent')

async def test():
    from admin.database import get_db
    from admin.crud import load_escalation_keywords
    from src.config.settings import get_config

    cfg = get_config()
    print('Config loaded:', type(cfg).__name__)
    print('Shops count:', len(cfg.shops))

    # 模拟 _get_escalation_keywords 的逻辑
    shop_id = '104b9a596a97'
    cat_id = 'lamp_store'

    # 模拟 dispatcher 的 _dynamic_keywords（实际为空，因为 load_dynamic_config 没被调用）
    dyn = {}
    if dyn:
        print('使用动态缓存')
    else:
        print('动态缓存为空，走 _load_keywords_from_db')

    conn = await get_db()
    try:
        keywords = await load_escalation_keywords(conn, cat_id, shop_id)
        print('Loaded %d keywords:' % len(keywords))
        for kw in keywords:
            print('  ', repr(kw))

        # 测试匹配
        msg = '转人工\n6月17日13: 11: 11'
        print()
        print('Buyer msg:', repr(msg))
        for kw in keywords:
            if kw in msg:
                print('  HARD_KEYWORD MATCH:', repr(kw))
    finally:
        await conn.close()

asyncio.run(test())
