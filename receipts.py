import base64
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from canonical import canonical_json
from schemas import PROFILE


def _b64url_decode(value: str) -> bytes:
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _b64_decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def verify_receipt(receipt: dict, evaluation_id: str, input_digest: str,
                   verifier: dict) -> bool:
    try:
        jwk = verifier["publicKeyJwk"]
        if verifier["algorithm"] != "Ed25519":
            return False
        if jwk["kty"] != "OKP" or jwk["crv"] != "Ed25519":
            return False
        key = Ed25519PublicKey.from_public_bytes(_b64url_decode(jwk["x"]))
        unsigned = {k: v for k, v in receipt.items() if k != "receiptSignature"}
        envelope = {
            "profile": PROFILE,
            "evaluationId": evaluation_id,
            "inputDigest": input_digest,
            "receipt": unsigned,
        }
        key.verify(_b64_decode(receipt["receiptSignature"]),
                   canonical_json(envelope).encode("utf-8"))
        return True
    except (KeyError, TypeError, ValueError, UnicodeError, InvalidSignature):
        return False
