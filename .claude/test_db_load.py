import asyncio
import sys
sys.path.insert(0, r'd:\MyWork\project-agent\code\CS-agent')

async def test():
    from admin.database import get_db
    from admin.crud import load_escalation_keywords

    conn = await get_db()
    try:
        keywords = await load_escalation_keywords(conn, 'lamp_store', '104b9a596a97')
        print('=== load_escalation_keywords(lamp_store, 104b9a596a97) ===')
        for kw in keywords:
            print(' ', repr(kw))
        print('共 %d 条' % len(keywords))
    finally:
        await conn.close()

asyncio.run(test())
