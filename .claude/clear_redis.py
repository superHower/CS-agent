import redis
r = redis.Redis(host='127.0.0.1', port=6379, db=0, decode_responses=True)
key = 'session:104b9a596a97:芬达'
val = r.get(key)
print('Before delete:', repr(val)[:300] if val else 'None')
r.delete(key)
print('Deleted:', key)
val2 = r.get(key)
print('After delete:', repr(val2)[:200] if val2 else 'None')

# Also check all session keys for 芬达
keys = r.keys('session:*芬达*')
print('All 芬达 session keys:', keys)
for k in keys:
    r.delete(k)
    print('Deleted:', k)
