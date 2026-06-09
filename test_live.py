"""End-to-end test against live TrustGuard on Railway."""
import json, urllib.request, urllib.error

BASE = "https://trustguard-production.up.railway.app"

def req(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    if body:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}

print("1. Root:", req("GET", "/"))
print("2. Register A:", req("POST", "/agents/register", {"agent_id": "live-a", "name": "Alice"}))
print("3. Register B:", req("POST", "/agents/register", {"agent_id": "live-b", "name": "Bob"}))
print("4. Rep A:", req("GET", "/reputation/live-a"))
print("5. Open:", req("POST", "/stream/open", {"payer_id": "live-b", "payee_id": "live-a", "rate_per_tick": 5, "max_total": 50, "ref": "live-test"}))
for i in range(3):
    s = req("POST", "/stream/drain?ref=live-test")
    print(f"6.{i+1} Drain: billed={s['total_billed']}, blocked={s['security_blocks']}")
print("7. Close:", req("POST", "/stream/close", {"ref": "live-test", "rater_id": "live-b", "rating": 5}))
print("8. Audit:", req("GET", "/audit/live-test"))
print("9. Final Rep:", req("GET", "/reputation/live-a"))
print("\nTRUSTGUARD LIVE ON RAILWAY!")
