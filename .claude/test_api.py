import urllib.request
import json
import sys

with open(r'd:\MyWork\project-agent\code\CS-agent\.claude\test-msg2.json', 'r', encoding='utf-8') as f:
    body = f.read().encode('utf-8')

req = urllib.request.Request(
    'http://127.0.0.1:8080/api/message',
    data=body,
    headers={'Content-Type': 'application/json; charset=utf-8'},
    method='POST',
)

try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode('utf-8')
        print('STATUS:', resp.status)
        data = json.loads(raw)
        print('REPLY:', data.get('reply'))
        print('ESCALATED:', data.get('escalated'))
except urllib.error.HTTPError as e:
    print('ERROR STATUS:', e.code)
    print('ERROR BODY:', e.read().decode('utf-8', errors='replace'))
except Exception as e:
    print('EXC:', e)
