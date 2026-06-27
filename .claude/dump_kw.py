import sqlite3
conn = sqlite3.connect(r"data\admin.db")
cur = conn.cursor()

print("=== 所有表 ===")
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(row)

print("\n=== escalation_keywords 全表 ===")
try:
    for row in cur.execute("SELECT id, category_id, shop_id, keyword FROM escalation_keywords ORDER BY id"):
        print(row)
except Exception as e:
    print("Error:", e)

print("\n=== 模拟 load_escalation_keywords(cat='lamp_store', shop='104b9a596a97') ===")
sql = "SELECT DISTINCT keyword FROM escalation_keywords WHERE (category_id = ? OR category_id IS NULL) AND (shop_id = ? OR shop_id = 'global')"
for row in cur.execute(sql, ("lamp_store", "104b9a596a97")):
    print(row)

print("\n=== 模拟 load_dynamic_config SQL ===")
sql2 = "SELECT category_id, shop_id, keyword FROM escalation_keywords WHERE category_id IS NOT NULL ORDER BY category_id, shop_id"
for row in cur.execute(sql2):
    print(row)

print("\n=== shops 表 ===")
try:
    for row in cur.execute("SELECT shop_id, name, category_id FROM shops"):
        print(row)
except Exception as e:
    print("Error:", e)

conn.close()