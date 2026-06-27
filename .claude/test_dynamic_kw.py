import sqlite3

conn = sqlite3.connect('data/admin.db')
cur = conn.cursor()

print('=== 完整表数据 ===')
cur.execute('SELECT id, shop_id, keyword, category_id FROM escalation_keywords')
for r in cur.fetchall():
    print('  id=%-3d shop=%-15s kw=%-15r cat=%s' % r)

print()
print('=== dispatcher.load_dynamic_config 当前 SQL（过滤掉 global）===')
cur.execute(
    "SELECT category_id, shop_id, keyword FROM escalation_keywords "
    "WHERE category_id IS NOT NULL AND shop_id != 'global' ORDER BY category_id, shop_id"
)
rows = cur.fetchall()
print(f'命中 {len(rows)} 条:')
for r in rows:
    print('  cat=%s  shop=%s  kw=%s' % r)
print('>>> 转人工 / 人工 / 举报 全部被过滤掉了！')

print()
print('=== 修复后 SQL（保留 shop_id=global，作为分类共享）===')
cur.execute(
    "SELECT category_id, shop_id, keyword FROM escalation_keywords "
    "WHERE category_id IS NOT NULL ORDER BY category_id, shop_id"
)
rows = cur.fetchall()
print(f'命中 {len(rows)} 条:')
for r in rows:
    print('  cat=%s  shop=%s  kw=%s' % r)

print()
print('=== 模拟 dispatcher._get_escalation_keywords 解析 ===')
kw_cache = {}
for cat_id, shop_id, kw in rows:
    kw_cache.setdefault(cat_id, {}).setdefault(shop_id, []).append(kw)

shop_id = '104b9a596a97'
cat_id = 'lamp_store'
cat_map = kw_cache.get(cat_id, {})
print(f'  cat_map for {cat_id}:', cat_map)
if shop_id in cat_map:
    result = cat_map[shop_id]
elif 'global' in cat_map:
    result = cat_map['global']
else:
    result = []
print(f'  最终返回关键词: {result}')

print()
test_msg = '转人工\n6月17日13: 11: 11'
for kw in result:
    if kw in test_msg:
        print(f'  命中! kw={kw!r}')

conn.close()
