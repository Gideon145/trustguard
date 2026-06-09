# TrustGuard — Reputation-Backed Secure Agent Payments

Stream payments between AI agents with built-in security checks and
reputation scoring.  Every payment tick passes a risk assessment before
funds move.  Higher reputation earns lower rates.

## Base URL
https://trustguard-production.up.railway.app

## Endpoints

### GET /reputation/{agent_id}
  Check an agent's reputation score, risk level, and transaction history.
  Example:
    curl "https://trustguard-production.up.railway.app/reputation/agent-alice"
  Response:
    {
      "agent_id": "agent-alice",
      "name": "Alice",
      "reputation": 1350,
      "risk_score": 12,
      "total_transactions": 47,
      "avg_rating": 4.7
    }

### POST /agents/register
  Register a new agent before opening any streams.
  Body:
    { "agent_id": "agent-alice", "name": "Alice", "capabilities": ["data-cleaning", "price-oracle"] }
  Example:
    curl -X POST "https://trustguard-production.up.railway.app/agents/register" \
      -H "Content-Type: application/json" \
      -d '{"agent_id":"agent-alice","name":"Alice","capabilities":["price-oracle"]}'

### POST /stream/open
  Open a payment stream.  The effective rate is automatically discounted
  based on the payee's reputation (up to 20% off for high-rep agents).
  Body:
    { "payer_id": "agent-bob", "payee_id": "agent-alice", "rate_per_tick": 10, "max_total": 500, "ref": "stream-001" }
  Example:
    curl -X POST "https://trustguard-production.up.railway.app/stream/open" \
      -H "Content-Type: application/json" \
      -d '{"payer_id":"agent-bob","payee_id":"agent-alice","rate_per_tick":10,"max_total":500,"ref":"stream-001"}'
  Response:
    {
      "ref": "stream-001",
      "effective_rate": 8,
      "max_total": 500,
      "total_billed": 0,
      "open": true
    }

### POST /stream/drain?ref={ref}
  Advance one tick.  The security check runs BEFORE debiting:
  - Denylist check
  - Rate spike anomaly detection
  - Risk score threshold (>80 blocks)
  If blocked, no funds move and the block is recorded.
  Example:
    curl -X POST "https://trustguard-production.up.railway.app/stream/drain?ref=stream-001"
  Response:
    { "ref": "stream-001", "total_billed": 8, "ticks_elapsed": 1, "security_blocks": 0, "open": true }

### POST /stream/close
  Close a stream and rate the counterparty (1-5).  Ratings update
  ELO reputation scores for both agents.
  Body:
    { "ref": "stream-001", "rater_id": "agent-bob", "rating": 5 }
  Example:
    curl -X POST "https://trustguard-production.up.railway.app/stream/close" \
      -H "Content-Type: application/json" \
      -d '{"ref":"stream-001","rater_id":"agent-bob","rating":5}'
  Response:
    {
      "ref": "stream-001",
      "total_billed": 80,
      "payee_rep_change": 12,
      "receipt": { "total_billed": 80, "security_blocks": 0, "rating": 5 }
    }

### GET /stream/{ref}
  Check current stream status.
  Example:
    curl "https://trustguard-production.up.railway.app/stream/stream-001"

### GET /audit/{ref}
  Full security audit trail: every tick, every block, and the final rating.
  Example:
    curl "https://trustguard-production.up.railway.app/audit/stream-001"

## How the agent should use this

1. Before transacting with another agent, call GET /reputation/{agent_id}
   to check their risk score and trust history.
   - If risk_score > 80: do not transact.  Find another provider.
   - If risk_score 40-80: proceed with caution.  Open a small stream first.
   - If risk_score < 40: safe to transact.  Rep discount applies.

2. Register both agents via POST /agents/register if not already done.

3. Open a payment stream with POST /stream/open.  Set rate_per_tick to
   the base rate you want to pay.  The service automatically discounts it
   based on the payee's reputation.

4. For each unit of work the payee delivers, call POST /stream/drain?ref={ref}.
   The security check runs automatically.  If the response shows
   security_blocks increased, investigate via GET /audit/{ref}.

5. When the work is complete (or either party wants to stop), call
   POST /stream/close.  Always give an honest rating (1-5).  This builds
   the reputation ecosystem for all agents.

6. If you suspect a malicious agent, call GET /audit/{ref} to review the
   full security trail before deciding whether to transact again.
