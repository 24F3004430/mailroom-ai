import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Recursively sort object keys and emit compact UTF-8-safe JSON."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def input_digest(dossiers: list[dict]) -> str:
    return sha256_json(dossiers)


def proposal_digest(proposal: dict) -> str:
    normalized = {
        "dossierId": proposal["dossierId"],
        "callId": proposal["callId"],
        "action": proposal["action"],
        "target": proposal.get("target"),
        "payload": proposal["payload"],
        "evidence": sorted(proposal["evidence"]),
    }
    return sha256_json(normalized)


def dossier_fingerprint(dossier: dict) -> str:
    return sha256_json(dossier)
