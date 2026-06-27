import sqlite3

conn = sqlite3.connect('data/admin.db')
cur = conn.cursor()

# Check DB encoding
print('=== DB encoding ===')
cur.execute('PRAGMA encoding')
print(' ', cur.fetchone()[0])

# Check what bytes are actually stored
print()
print('=== escalation_keywords raw bytes ===')
cur.execute('SELECT id, shop_id, keyword, category_id FROM escalation_keywords ORDER BY id')
for r in cur.fetchall():
    kw = r[2]
    # kw is already a str (Python decoded it using the connection encoding)
    # Show actual UTF-8 bytes
    kw_bytes = kw.encode('utf-8')
    print('  id=%d  shop=%-15s  keyword=%-15r  utf8_hex=%s  category=%s' % (
        r[0], r[1], kw, kw_bytes.hex(), r[3]
    ))
    # Test: does the ACTUAL "转人工" contain this kw?
    if '转人工' in kw:
        print('    *** MATCH: "%s" is substring of "转人工" ***' % kw)
    elif kw in '转人工':
        print('    *** MATCH: "转人工" contains "%s" ***' % kw)

print()
print('=== alert_config ===')
cur.execute('SELECT id, webhook_url FROM alert_config')
for r in cur.fetchall():
    url = r[1] if r[1] else ''
    print('  id=%d  webhook_url=%s' % (r[0], url[:80] if url else '(empty)'))

print()
print('=== shops ===')
cur.execute('SELECT shop_id, name, platform, category_id FROM shops')
for r in cur.fetchall():
    print('  shop_id=%-15s  name=%-20s  platform=%-8s  category=%s' % (r[0], r[1], r[2], r[3]))

conn.close()

conn.close()
