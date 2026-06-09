# TrustGuard

**Reputation-backed secure payment streaming for AI agents.**

Agents hire agents. TrustGuard makes sure they don't get rugged.

---

## What it does

AI agents open payment streams to each other. Every tick, a security check runs BEFORE funds move — denylist scan, rate anomaly detection, risk threshold. Bad agents get blocked. Good agents build reputation. Higher rep = lower rates.

```
Agent A checks B's reputation → 92/100 ✅
A opens a stream to B at 15% discount (high rep)
Every tick: security check → pass → funds flow
A closes stream → rates B 5★ → B's rep goes up
```

---

## API (5 endpoints)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/reputation/{agent_id}` | Check trust score + risk level |
| `POST` | `/agents/register` | Register before transacting |
| `POST` | `/stream/open` | Open stream at rep-adjusted rate |
| `POST` | `/stream/drain?ref={ref}` | Security check → debit one tick |
| `POST` | `/stream/close` | Close + rate counterparty |
| `GET` | `/audit/{ref}` | Full security audit trail |

**Live:** `https://trustguard-production.up.railway.app`

---

## Quick test

```bash
# Register two agents
curl -X POST https://trustguard-production.up.railway.app/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"alice","name":"Alice"}'

curl -X POST https://trustguard-production.up.railway.app/agents/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"bob","name":"Bob"}'

# Check reputation
curl https://trustguard-production.up.railway.app/reputation/alice

# Open a stream
curl -X POST https://trustguard-production.up.railway.app/stream/open \
  -H "Content-Type: application/json" \
  -d '{"payer_id":"bob","payee_id":"alice","rate_per_tick":5,"max_total":100,"ref":"s1"}'

# Drain 3 ticks (security check on each)
curl -X POST https://trustguard-production.up.railway.app/stream/drain?ref=s1
curl -X POST https://trustguard-production.up.railway.app/stream/drain?ref=s1
curl -X POST https://trustguard-production.up.railway.app/stream/drain?ref=s1

# Close and rate
curl -X POST https://trustguard-production.up.railway.app/stream/close \
  -H "Content-Type: application/json" \
  -d '{"ref":"s1","rater_id":"bob","rating":5}'

# Full audit trail
curl https://trustguard-production.up.railway.app/audit/s1
```

---

## Architecture

```
┌──────────────────────────────────────────────┐
│                  TrustGuard                   │
│                                              │
│  POST /agents/register  ──► Agent Registry   │
│  GET  /reputation/{id}  ──► ELO + Risk Score │
│  POST /stream/open      ──► Stream State     │
│  POST /stream/drain     ──► Security Check   │
│         │                    ├─ Denylist      │
│         │                    ├─ Rate Anomaly  │
│         │                    └─ Risk Threshold│
│         ▼                    ┌─ PASS → Debit  │
│                              └─ BLOCK → Log   │
│  POST /stream/close     ──► Rate + Update Rep│
│  GET  /audit/{ref}      ──► Full Trail       │
└──────────────────────────────────────────────┘
```

---

## Security checks (per tick)

1. **Denylist** — blocked agents can't receive payments
2. **Rate anomaly** — sudden spikes in billing rate are flagged
3. **Risk threshold** — agents with risk score > 80 are blocked

All blocks are logged. Full audit trail available via `GET /audit/{ref}`.

---

## Reputation system

ELO-based, starting at 1200. K-factor = 32. Post-transaction ratings (1-5) update scores. Higher rep → lower risk score → up to 20% rate discount.

---

## Built for NandaHack 2026

Hosted by HCLTech + MIT Media Lab. SKILL.md submission at [nandatown.projectnanda.org/skills](https://nandatown.projectnanda.org/skills).

---

## Run locally

```bash
pip install fastapi uvicorn
python main.py
# → http://localhost:8000
```
