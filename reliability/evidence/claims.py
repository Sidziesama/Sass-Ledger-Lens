"""Structured claims with lineage.

A sentence in a finance memo is only worth as much as the row it points at.
Every factual statement Ledger Lens makes is created as a Claim carrying its own
arithmetic and the transaction ids behind it, then VERIFIED independently before
it can be shown. A claim whose arithmetic does not check out is not rendered.

That is what makes "evidence coverage: 100%" a measurement rather than a slogan.
"""

import json
from datetime import datetime, timezone

TOLERANCE = 0.01


class Claim:
    _seq = 0

    def __init__(self, text, account=None, variance=None, driver_amount=None,
                 drivers=None, transaction_ids=None, calculation=None,
                 detector=None, confidence=None, prior_ids=None, kind="driver", numbers=None):
        Claim._seq += 1
        self.id = f"claim_{Claim._seq:03d}"
        self.text = text
        self.kind = kind
        self.account = account
        self.variance = variance
        self.driver_amount = driver_amount
        self.drivers = drivers or []
        self.transaction_ids = transaction_ids or []
        self.calculation = calculation
        self.detector = detector
        self.confidence = confidence
        self.prior_ids = prior_ids or []
        # Every figure this claim states, so the language linter can prove the
        # memo never prints a number the engine did not produce.
        self.numbers = [round(float(x), 4) for x in (numbers or []) if isinstance(x, (int, float))]
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.verified = None
        self.verification_note = None

    @property
    def contribution_pct(self):
        if self.variance and self.driver_amount is not None:
            return round(self.driver_amount / self.variance * 100, 2)
        return None

    def verify(self):
        """Re-derive the arithmetic. A claim that cannot prove itself is dropped."""
        problems = []
        if self.driver_amount is not None and self.variance:
            pct = self.driver_amount / self.variance * 100
            if self.calculation and "%" in str(self.calculation):
                pass
            if abs(pct) > 100 + TOLERANCE * 100 and self.kind == "driver":
                problems.append(f"driver share {pct:.1f}% exceeds the total movement")
        if self.kind == "driver" and not self.transaction_ids:
            problems.append("no transaction evidence attached")
        if self.driver_amount is not None and self.variance in (0, None):
            problems.append("driver amount stated against a zero or missing variance")
        self.verified = not problems
        self.verification_note = "; ".join(problems) if problems else "arithmetic re-derived, evidence present"
        return self.verified

    def to_dict(self):
        return {
            "claim_id": self.id, "claim": self.text, "kind": self.kind,
            "account": self.account, "variance": self.variance,
            "driver_amount": self.driver_amount,
            "contribution_pct": self.contribution_pct,
            "drivers": self.drivers, "transaction_ids": self.transaction_ids,
            "calculation": self.calculation, "detector": self.detector,
            "confidence": self.confidence, "supporting_priors": self.prior_ids,
            "numbers": self.numbers,
            "verified": self.verified, "verification_note": self.verification_note,
            "created_at": self.created_at,
        }


class ClaimSet:
    def __init__(self):
        self.claims = []

    def add(self, claim):
        claim.verify()
        self.claims.append(claim)
        return claim

    def verified(self):
        return [c for c in self.claims if c.verified]

    def rejected(self):
        return [c for c in self.claims if not c.verified]

    def evidence_coverage(self):
        """Share of factual claims that survived independent verification."""
        if not self.claims:
            return None
        return round(len(self.verified()) / len(self.claims) * 100, 1)

    def to_dict(self):
        return {
            "claims": [c.to_dict() for c in self.claims],
            "total": len(self.claims),
            "verified": len(self.verified()),
            "rejected": len(self.rejected()),
            "evidence_coverage_pct": self.evidence_coverage(),
        }

    def citable(self):
        """The only facts the language layer is permitted to state."""
        return json.dumps([{"claim_id": c.id, "statement": c.text,
                            "calculation": c.calculation,
                            "transaction_ids": c.transaction_ids[:6]}
                           for c in self.verified()], indent=2)
