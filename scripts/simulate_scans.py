import json, random, time, threading, requests

BASE = "http://127.0.0.1:5000"

TOKENS = [f"100{i}" for i in range(1,10)]
SCANNERS = ["S1","S2","S3"]

def worker_loop(token):
    for _ in range(3):
        r = requests.post(f"{BASE}/api/scan", json={"token_id": token, "scanner_id": random.choice(SCANNERS)})
        print(token, r.status_code, r.json())
        time.sleep(random.uniform(0.3, 1.2))

threads = [threading.Thread(target=worker_loop, args=(t,)) for t in TOKENS[:5]]
[t.start() for t in threads]
[t.join() for t in threads]
