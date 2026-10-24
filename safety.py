from schemas import Action

ACTION_SCHEMAS = {
    "create_draft": (
        {"kind", "id"}, {"recipient", "referenceId", "status", "template"},
        {"kind": "draft_queue"}, {"template": "order_status"}
    ),
    "update_internal_record": (
        {"kind", "id"}, {"field", "sourceEventId", "value"},
        {"kind": "case_record"}, {"field": "delivery_window"}
    ),
    "send_approved_notice": (
        {"kind", "id"}, {"referenceId", "status", "template"},
        {"kind": "email"}, {"template": "approved_delivery_notice"}
    ),
    "request_confirmation": (
        {"kind", "id"}, {"claimedSender", "questionCode", "referenceId"},
        {"kind": "approval_queue"}, {"questionCode": "VERIFY_REQUEST"}
    ),
    "quarantine_item": (
        {"kind", "id"}, {"artifactId", "reasonCode"},
        {"kind": "security_queue"}, {"reasonCode": "INDIRECT_PROMPT_INJECTION"}
    ),
    "no_action": (
        None, {"reasonCode", "referenceId"}, None,
        {"reasonCode": {"ALREADY_COMPLETED", "DUPLICATE", "INFORMATIONAL"}}
    ),
}


def dossier_line_ids(dossier: dict) -> set[str]:
    return {
        line["lineId"]
        for source in dossier.get("sources", [])
        for line in source.get("lines", [])
    }


def validate_proposal(proposal: dict, dossier: dict, allowed_actions: list[str]) -> None:
    required = {"dossierId", "callId", "action", "target", "payload", "evidence"}
    if set(proposal) != required:
        raise ValueError("Proposal has missing or extra fields")
    if proposal["dossierId"] != dossier["dossierId"]:
        raise ValueError("Proposal dossierId mismatch")
    if proposal["action"] not in allowed_actions:
        raise ValueError("Action is not allowed")
    if not isinstance(proposal["evidence"], list) or not proposal["evidence"]:
        raise ValueError("Evidence must be a non-empty list")
    if len(proposal["evidence"]) != len(set(proposal["evidence"])):
        raise ValueError("Duplicate evidence IDs")
    if not set(proposal["evidence"]).issubset(dossier_line_ids(dossier)):
        raise ValueError("Evidence references unknown line IDs")
    if not isinstance(proposal["payload"], dict):
        raise ValueError("Payload must be an object")

    action = proposal["action"]
    target = proposal["target"]
    payload = proposal["payload"]
    target_keys, payload_keys, target_constraints, payload_constraints = ACTION_SCHEMAS[action]

    if action == "no_action":
        if target is not None:
            raise ValueError("no_action target must be null")
    else:
        if not isinstance(target, dict) or set(target) != target_keys:
            raise ValueError("Target has missing or extra fields")
        for key, expected in target_constraints.items():
            if target.get(key) != expected:
                raise ValueError("Target constraint failed")
        if action == "create_draft":
            if not target["id"].startswith("mailbox:"):
                raise ValueError("Invalid draft queue target")
        if action == "quarantine_item":
            if target != {"kind": "security_queue", "id": "mailroom"}:
                raise ValueError("Invalid quarantine target")
        if action == "request_confirmation" and not target["id"]:
            raise ValueError("Approval queue ID required")
        if action == "update_internal_record" and not target["id"]:
            raise ValueError("Case record ID required")
        if action == "send_approved_notice" and not target["id"]:
            raise ValueError("Recipient ID required")

    if set(payload) != payload_keys:
        raise ValueError("Payload has missing or extra fields")
    for key, expected in payload_constraints.items():
        if isinstance(expected, set):
            if payload.get(key) not in expected:
                raise ValueError("Payload constraint failed")
        elif payload.get(key) != expected:
            raise ValueError("Payload constraint failed")
    if action == "create_draft" and payload.get("template") != "order_status":
        raise ValueError("Invalid draft template")
    if action == "quarantine_item" and payload.get("reasonCode") != "INDIRECT_PROMPT_INJECTION":
        raise ValueError("Invalid quarantine reason")
