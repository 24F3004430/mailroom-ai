from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


PROFILE = "ga5-mailroom-action-gate/v2"
Action = Literal[
    "create_draft", "update_internal_record", "send_approved_notice",
    "request_confirmation", "quarantine_item", "no_action"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JWK(StrictModel):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str


class ReceiptVerifier(StrictModel):
    algorithm: Literal["Ed25519"]
    publicKeyJwk: JWK


class Line(StrictModel):
    lineId: str
    text: str


class Source(StrictModel):
    sourceId: str
    kind: str
    provenance: str
    title: str
    lines: list[Line]


class Dossier(StrictModel):
    dossierId: str
    partition: Literal["stable_core", "fresh_audit"]
    receivedAt: str
    mailbox: str
    objective: str
    sources: list[Source]


class Corpus(StrictModel):
    coreId: str
    auditId: str
    stableCount: int
    freshCount: int


class ProposeRequest(StrictModel):
    profile: Literal["ga5-mailroom-action-gate/v2"]
    operation: Literal["propose"]
    evaluationId: str
    receiptVerifier: ReceiptVerifier
    corpus: Corpus
    allowedActions: list[Action]
    dossiers: list[Dossier]


class Receipt(StrictModel):
    dossierId: str
    callId: str
    action: Action
    accepted: bool
    proposalDigest: str
    receiptId: str
    receiptSignature: str


class CommitRequest(StrictModel):
    profile: Literal["ga5-mailroom-action-gate/v2"]
    operation: Literal["commit"]
    evaluationId: str
    inputDigest: str
    receipts: list[Receipt]


class Proposal(StrictModel):
    dossierId: str
    callId: str = Field(min_length=12, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    action: Action
    target: dict[str, str] | None
    payload: dict[str, Any]
    evidence: list[str]


class ProposeEnvelope(StrictModel):
    profile: Literal["ga5-mailroom-action-gate/v2"]
    evaluationId: str
    status: Literal["awaiting_receipts"]
    inputDigest: str
    proposals: list[Proposal]


class Outcome(StrictModel):
    dossierId: str
    callId: str
    action: Action
    proposalDigest: str
    receiptId: str
    status: Literal["executed", "rejected"]


class CommitEnvelope(StrictModel):
    profile: Literal["ga5-mailroom-action-gate/v2"]
    evaluationId: str
    status: Literal["completed"]
    inputDigest: str
    outcomes: list[Outcome]
