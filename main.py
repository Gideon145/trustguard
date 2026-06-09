# TrustGuard — Reputation-Backed Secure Agent Payments
# FastAPI service for the NandaHack 2026 Skills submission
# 
# 5 endpoints combining:
#   🔐 Security — risk checks before every payment tick
#   💰 Payments — per-tick streaming with rep-gated rates  
#   ⭐ Reputation — ELO scores from post-transaction ratings

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TrustGuard",
    description="Reputation-backed secure payment streaming for AI agents",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AgentRegisterRequest(BaseModel):
    agent_id: str
    name: str
    capabilities: list[str] = []

class AgentProfile(BaseModel):
    agent_id: str
    name: str
    capabilities: list[str]
    reputation: int          # ELO score (starts at 1200)
    risk_score: int          # 0-100, lower is safer
    total_transactions: int
    avg_rating: float
    registered_at: float

class StreamOpenRequest(BaseModel):
    payer_id: str
    payee_id: str
    rate_per_tick: int       # base rate before rep discount
    max_total: int
    ref: str

class StreamStatus(BaseModel):
    ref: str
    payer_id: str
    payee_id: str
    rate_per_tick: int
    effective_rate: int      # after rep discount
    max_total: int
    total_billed: int
    ticks_elapsed: int
    open: bool
    security_blocks: int     # how many ticks were blocked
    opened_at: float

class StreamCloseRequest(BaseModel):
    ref: str
    rater_id: str
    rating: int              # 1-5

class StreamCloseResponse(BaseModel):
    ref: str
    total_billed: int
    payer_rep_change: int
    payee_rep_change: int
    receipt: dict

class AuditResponse(BaseModel):
    ref: str
    total_billed: int
    security_blocks: int
    block_reasons: list[str]
    rating_given: Optional[int]
    payer_rep: int
    payee_rep: int

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class StreamState:
    ref: str
    payer_id: str
    payee_id: str
    rate_per_tick: int
    effective_rate: int
    max_total: int
    total_billed: int = 0
    ticks_elapsed: int = 0
    open: bool = True
    security_blocks: int = 0
    block_reasons: list[str] = field(default_factory=list)
    opened_at: float = field(default_factory=time.time)

# In-memory stores (production: use Redis/DB)
agents: dict[str, dict] = {}
streams: dict[str, StreamState] = {}
audit_log: dict[str, list[dict]] = {}
denylist: set[str] = set()

# ---------------------------------------------------------------------------
# Reputation engine (ELO-like)
# ---------------------------------------------------------------------------

ELO_K = 32
INITIAL_REPUTATION = 1200


def _compute_rep_change(rater_rep: int, rated_rep: int, rating: int) -> int:
    """ELO delta: rating 1-5 maps to expected score 0.0-1.0."""
    expected = 1.0 / (1.0 + math.pow(10, (rated_rep - rater_rep) / 400.0))
    actual = (rating - 1) / 4.0  # 1→0.0, 3→0.5, 5→1.0
    return round(ELO_K * (actual - expected))


def _compute_risk_score(agent: dict) -> int:
    """Risk = f(rep, tx count, avg rating). Lower = safer.
    
    New agents start at moderate risk (~45).  Risk drops as they
    build reputation and complete transactions.  Malicious agents
    pushed to 80+ via denylist, not formula.
    """
    rep_penalty = max(0, (2000 - agent["reputation"]) // 25)   # 0-32
    tx_bonus = min(25, agent["total_transactions"] * 3)         # 0-25
    # No rating penalty for agents with 0 transactions (neutral, not risky)
    if agent["total_transactions"] == 0:
        rating_penalty = 0
    else:
        rating_penalty = max(0, int((5.0 - agent["avg_rating"]) * 12))  # 0-48
    return max(5, min(100, rep_penalty + rating_penalty - tx_bonus))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"service": "TrustGuard", "status": "operational", "agents": len(agents), "active_streams": sum(1 for s in streams.values() if s.open)}


# --- Reputation ---

@app.post("/agents/register", response_model=AgentProfile)
def register_agent(body: AgentRegisterRequest):
    if body.agent_id in agents:
        raise HTTPException(400, "Agent already registered")
    agents[body.agent_id] = {
        "agent_id": body.agent_id,
        "name": body.name,
        "capabilities": body.capabilities,
        "reputation": INITIAL_REPUTATION,
        "total_transactions": 0,
        "ratings_sum": 0,
        "avg_rating": 0.0,
        "registered_at": time.time(),
    }
    return _profile(body.agent_id)


@app.get("/reputation/{agent_id}", response_model=AgentProfile)
def get_reputation(agent_id: str):
    if agent_id not in agents:
        raise HTTPException(404, "Agent not found")
    return _profile(agent_id)


def _profile(agent_id: str) -> AgentProfile:
    a = agents[agent_id]
    return AgentProfile(
        agent_id=a["agent_id"],
        name=a["name"],
        capabilities=a["capabilities"],
        reputation=a["reputation"],
        risk_score=_compute_risk_score(a),
        total_transactions=a["total_transactions"],
        avg_rating=round(a["avg_rating"], 1),
        registered_at=a["registered_at"],
    )


# --- Streams ---

@app.post("/stream/open", response_model=StreamStatus)
def open_stream(body: StreamOpenRequest):
    if body.ref in streams:
        raise HTTPException(400, "Duplicate stream reference")
    if body.payer_id not in agents:
        raise HTTPException(400, f"Payer '{body.payer_id}' not registered")
    if body.payee_id not in agents:
        raise HTTPException(400, f"Payee '{body.payee_id}' not registered")

    payee_rep = agents[body.payee_id]["reputation"]
    # Reputation discount: higher rep → up to 20% off
    discount = min(0.20, max(0.0, (payee_rep - 1000) / 5000))
    effective_rate = max(1, round(body.rate_per_tick * (1.0 - discount)))

    s = StreamState(
        ref=body.ref,
        payer_id=body.payer_id,
        payee_id=body.payee_id,
        rate_per_tick=body.rate_per_tick,
        effective_rate=effective_rate,
        max_total=body.max_total,
    )
    streams[body.ref] = s
    audit_log.setdefault(body.ref, []).append({"tick": 0, "event": "opened", "effective_rate": effective_rate, "ts": time.time()})
    return _stream_status(s)


@app.post("/stream/drain", response_model=StreamStatus)
def drain_stream(ref: str = Query(...)):
    s = streams.get(ref)
    if s is None:
        raise HTTPException(404, "Stream not found")
    if not s.open:
        raise HTTPException(400, "Stream already closed")
    if s.total_billed >= s.max_total:
        return _stream_status(s)

    # ---- SECURITY CHECK ----
    payer = agents.get(s.payer_id)
    payee = agents.get(s.payee_id)
    risk_payee = _compute_risk_score(payee) if payee else 50
    blocked = False
    reason = ""

    if s.payee_id in denylist:
        blocked = True
        reason = "payee denylisted"
    elif s.ticks_elapsed > 0 and s.effective_rate > s.total_billed / s.ticks_elapsed * 3:
        blocked = True
        reason = "rate spike anomaly"
    elif risk_payee > 80:
        blocked = True
        reason = f"payee risk too high ({risk_payee}/100)"

    if blocked:
        s.security_blocks += 1
        s.block_reasons.append(f"tick {s.ticks_elapsed}: {reason}")
        audit_log.setdefault(ref, []).append({"tick": s.ticks_elapsed, "event": "blocked", "reason": reason, "ts": time.time()})
        s.ticks_elapsed += 1
        return _stream_status(s)

    # ---- BILL ----
    available = s.max_total - s.total_billed
    debit = min(s.effective_rate, available)
    s.total_billed += debit
    s.ticks_elapsed += 1

    audit_log.setdefault(ref, []).append({"tick": s.ticks_elapsed, "event": "drained", "amount": debit, "cumulative": s.total_billed, "ts": time.time()})
    return _stream_status(s)


@app.post("/stream/close", response_model=StreamCloseResponse)
def close_stream(body: StreamCloseRequest):
    s = streams.get(body.ref)
    if s is None:
        raise HTTPException(404, "Stream not found")
    if not s.open:
        raise HTTPException(400, "Stream already closed")
    if body.rater_id not in (s.payer_id, s.payee_id):
        raise HTTPException(400, "Only payer or payee can rate")
    if body.rating < 1 or body.rating > 5:
        raise HTTPException(400, "Rating must be 1-5")

    s.open = False
    rated_id = s.payee_id if body.rater_id == s.payer_id else s.payer_id
    rater = agents[body.rater_id]
    rated = agents[rated_id]

    delta = _compute_rep_change(rater["reputation"], rated["reputation"], body.rating)
    rated["reputation"] = max(0, rated["reputation"] + delta)
    rated["total_transactions"] += 1
    rated["ratings_sum"] += body.rating
    rated["avg_rating"] = rated["ratings_sum"] / max(1, rated["total_transactions"])

    rater["total_transactions"] += 1
    rater["ratings_sum"] += body.rating
    rater["avg_rating"] = rater["ratings_sum"] / max(1, rater["total_transactions"])

    audit_log.setdefault(body.ref, []).append({"tick": s.ticks_elapsed, "event": "closed", "rating": body.rating, "rep_delta": delta, "ts": time.time()})

    return StreamCloseResponse(
        ref=body.ref,
        total_billed=s.total_billed,
        payer_rep_change=delta if body.rater_id == s.payer_id else 0,
        payee_rep_change=delta if body.rater_id == s.payee_id else 0,
        receipt={
            "ref": body.ref,
            "payer": s.payer_id,
            "payee": s.payee_id,
            "total_billed": s.total_billed,
            "security_blocks": s.security_blocks,
            "rating": body.rating,
        },
    )


@app.get("/stream/{ref}", response_model=StreamStatus)
def get_stream(ref: str):
    s = streams.get(ref)
    if s is None:
        raise HTTPException(404, "Stream not found")
    return _stream_status(s)


@app.get("/audit/{ref}", response_model=AuditResponse)
def get_audit(ref: str):
    s = streams.get(ref)
    if s is None:
        raise HTTPException(404, "Stream not found")
    payer = agents.get(s.payer_id, {})
    payee = agents.get(s.payee_id, {})
    log_entries = audit_log.get(ref, [])
    rating_given = None
    for entry in log_entries:
        if entry.get("event") == "closed":
            rating_given = entry.get("rating")
    return AuditResponse(
        ref=ref,
        total_billed=s.total_billed,
        security_blocks=s.security_blocks,
        block_reasons=s.block_reasons,
        rating_given=rating_given,
        payer_rep=payer.get("reputation", 0),
        payee_rep=payee.get("reputation", 0),
    )


# --- Denylist (admin) ---

@app.post("/admin/denylist/{agent_id}")
def add_to_denylist(agent_id: str):
    denylist.add(agent_id)
    return {"denylisted": agent_id, "denylist_size": len(denylist)}


@app.delete("/admin/denylist/{agent_id}")
def remove_from_denylist(agent_id: str):
    denylist.discard(agent_id)
    return {"removed": agent_id}


# --- Helper ---

def _stream_status(s: StreamState) -> StreamStatus:
    return StreamStatus(
        ref=s.ref,
        payer_id=s.payer_id,
        payee_id=s.payee_id,
        rate_per_tick=s.rate_per_tick,
        effective_rate=s.effective_rate,
        max_total=s.max_total,
        total_billed=s.total_billed,
        ticks_elapsed=s.ticks_elapsed,
        open=s.open,
        security_blocks=s.security_blocks,
        opened_at=s.opened_at,
    )


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
