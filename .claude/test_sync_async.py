import asyncio
import sys
sys.path.insert(0, r'd:\MyWork\project-agent\code\CS-agent')

async def test():
    from admin.database import get_db
    from admin.crud import load_escalation_keywords

    conn = await get_db()
    try:
        kw = await load_escalation_keywords(conn, 'lamp_store', '104b9a596a97')
        print('Keywords loaded:', kw)
    finally:
        await conn.close()

# Test: calling from within async context using asyncio.get_event_loop() pattern
async def main():
    print('Testing async load...')
    loop = asyncio.get_event_loop()
    conn = await get_db()
    try:
        kw = await load_escalation_keywords(conn, 'lamp_store', '104b9a596a97')
        print('Result:', kw)
    finally:
        await conn.close()

try:
    asyncio.run(main())
except Exception as e:
    print('Error:', e)
    import traceback; traceback.print_exc()
