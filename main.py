import json
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

load_dotenv()

from canonical import input_digest, proposal_digest, dossier_fingerprint, canonical_json
from decision import propose_for_dossier
from receipts import verify_receipt
from schemas import PROFILE, ProposeRequest, CommitRequest
from safety import validate_proposal
import storage

app = FastAPI(title="Safe AI Mailroom", version="1.0.0")
storage.init_db()
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "1048576"))


@app.exception_handler(ValidationError)
async def validation_error_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": "Request schema validation failed"})


@app.post("/")
async def mailroom(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request too large")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    operation = data.get("operation")
    try:
        if operation == "propose":
            req = ProposeRequest.model_validate(data)
            return await handle_propose(req.model_dump(mode="json"))
        if operation == "commit":
            req = CommitRequest.model_validate(data)
            return await handle_commit(req.model_dump(mode="json"))
    except ValidationError:
        raise HTTPException(status_code=422, detail="Request schema validation failed")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    raise HTTPException(status_code=400, detail="Invalid operation")


async def handle_propose(data):
    if data["profile"] != PROFILE:
        raise HTTPException(422, "Unsupported profile")
    dossiers = data["dossiers"]
    ids = [d["dossierId"] for d in dossiers]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate dossier IDs")
    # Check line ID uniqueness within each dossier.
    for d in dossiers:
        line_ids = [line["lineId"] for s in d["sources"] for line in s["lines"]]
        if len(line_ids) != len(set(line_ids)):
            raise HTTPException(422, "Duplicate line IDs in dossier")
    digest = input_digest(dossiers)
    existing = storage.get_evaluation(data["evaluationId"])
    if existing:
        if existing["input_digest"] != digest or existing["request_json"] != canonical_json(data):
            raise HTTPException(409, "Evaluation ID reused with changed content")
        return json.loads(existing["propose_response"])

    proposals = []
    for dossier in dossiers:
        fingerprint = dossier_fingerprint(dossier)
        cached = storage.get_cached_proposal(fingerprint) if dossier["partition"] == "stable_core" else None
        if cached:
            # Dossier IDs are opaque and can differ even for semantically similar data;
            # cache fingerprint includes dossierId, so the stored proposal remains exact.
            proposal = cached
        else:
            try:
                proposal = await propose_for_dossier(dossier, data["allowedActions"])
            except Exception as exc:
                # Fail closed; do not fabricate a safe-looking proposal.
                raise HTTPException(502, f"Decision engine failed: {type(exc).__name__}")
            if dossier["partition"] == "stable_core":
                storage.save_cached_proposal(fingerprint, proposal)
        validate_proposal(proposal, dossier, data["allowedActions"])
        proposals.append(proposal)

    response = {
        "profile": PROFILE,
        "evaluationId": data["evaluationId"],
        "status": "awaiting_receipts",
        "inputDigest": digest,
        "proposals": proposals,
    }
    try:
        storage.save_evaluation_and_proposals(
            data["evaluationId"], digest, data, data["receiptVerifier"],
            response, proposals
        )
    except Exception:
        existing = storage.get_evaluation(data["evaluationId"])
        if existing and existing["input_digest"] == digest:
            return json.loads(existing["propose_response"])
        raise HTTPException(409, "Evaluation could not be stored")
    return response


async def handle_commit(data):
    evaluation = storage.get_evaluation(data["evaluationId"])
    if evaluation is None:
        raise HTTPException(409, "Unknown evaluation")
    if data["inputDigest"] != evaluation["input_digest"]:
        raise HTTPException(409, "Input digest mismatch")
    if evaluation["commit_response"]:
        if evaluation["commit_request_json"] == canonical_json(data):
            return json.loads(evaluation["commit_response"])
        raise HTTPException(409, "Evaluation already committed with different content")

    proposals_rows = storage.get_proposals(data["evaluationId"])
    proposals = {row["dossier_id"]: json.loads(row["proposal_json"]) for row in proposals_rows}
    receipts = data["receipts"]
    if len(receipts) != len(proposals):
        raise HTTPException(422, "Receipt count mismatch")
    dossier_ids = [r["dossierId"] for r in receipts]
    receipt_ids = [r["receiptId"] for r in receipts]
    call_ids = [r["callId"] for r in receipts]
    if len(set(dossier_ids)) != len(dossier_ids) or len(set(receipt_ids)) != len(receipt_ids) or len(set(call_ids)) != len(call_ids):
        raise HTTPException(422, "Duplicate receipt bindings")

    verifier = json.loads(evaluation["verifier_json"])
    # Verify ALL signatures and bindings before recording any receipt/effect.
    checked = []
    for receipt in receipts:
        proposal = proposals.get(receipt["dossierId"])
        if proposal is None:
            raise HTTPException(422, "Receipt references unknown dossier")
        pdigest = proposal_digest(proposal)
        if (receipt["callId"] != proposal["callId"]
            or receipt["action"] != proposal["action"]
            or receipt["proposalDigest"] != pdigest):
            raise HTTPException(422, "Receipt does not match persisted proposal")
        if not verify_receipt(receipt, data["evaluationId"], data["inputDigest"], verifier):
            raise HTTPException(422, "Invalid receipt signature")
        checked.append((receipt, True))

    outcomes = []
    for receipt in receipts:
        outcomes.append({
            "dossierId": receipt["dossierId"],
            "callId": receipt["callId"],
            "action": receipt["action"],
            "proposalDigest": receipt["proposalDigest"],
            "receiptId": receipt["receiptId"],
            "status": "executed" if receipt["accepted"] is True else "rejected",
        })
    response = {
        "profile": PROFILE,
        "evaluationId": data["evaluationId"],
        "status": "completed",
        "inputDigest": data["inputDigest"],
        "outcomes": outcomes,
    }
    try:
        storage.save_commit(data["evaluationId"], data, response, checked)
    except Exception:
        # Another identical concurrent commit may have won the transaction.
        latest = storage.get_evaluation(data["evaluationId"])
        if latest and latest["commit_response"] and latest["commit_request_json"] == canonical_json(data):
            return json.loads(latest["commit_response"])
        raise HTTPException(409, "Commit could not be stored")
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}
