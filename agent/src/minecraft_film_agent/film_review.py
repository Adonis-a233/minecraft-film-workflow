"""Human review records are separate from technical render receipts.

Records bind to content and output hashes. Nothing in the executor creates an
approval; the CLI only stores an explicitly supplied review after validation.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .locking import RunLease, write_json


class FilmReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: str = Field(pattern=r"^(shot:[A-Za-z0-9_-]{1,64}|chapter:[A-Za-z0-9_-]{1,64}|film)$")
    spec_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_hashes: dict[str, str] = Field(min_length=1)
    reviewer: str = Field(min_length=1, max_length=200)
    reviewed_at: str
    decision: Literal["approved", "rejected"]
    normal_speed_watched: bool
    checks: dict[str, Literal["pass", "fail", "not_applicable"]]
    notes: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def valid_review(self):
        import re
        if not self.reviewer.strip() or not self.notes.strip():
            raise ValueError("reviewer and notes must not be blank")
        timestamp = datetime.fromisoformat(self.reviewed_at)
        if timestamp.tzinfo is None:
            raise ValueError("reviewed_at must include a timezone")
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in self.output_hashes.values()):
            raise ValueError("output hashes must be SHA-256")
        expected = {"geometry", "performance", "composition", "continuity", "sound"}
        if set(self.checks) != expected:
            raise ValueError(f"checks must contain {sorted(expected)}")
        if self.decision == "approved":
            if not self.normal_speed_watched or "fail" in self.checks.values():
                raise ValueError("approval requires normal-speed viewing and no failed checks")
            if any(self.checks[key] != "pass" for key in expected - {"sound"}):
                raise ValueError("visual checks cannot be waived")
            # Silent shot exports can waive sound; chapters and films cannot.
            if not self.target.startswith("shot:") and self.checks["sound"] != "pass":
                raise ValueError("chapter and film approval require sound review")
        return self


def load_reviews(root: Path, plan_id: str) -> list[dict]:
    from .film_master import FilmMasterError, _master_dir, _read_json
    path = _master_dir(root, plan_id) / "human-reviews.json"
    if not path.is_file():
        return []
    doc = _read_json(path)
    if doc.get("plan_id") != plan_id:
        raise FilmMasterError("human review journal belongs to another plan")
    return [FilmReview.model_validate(record).model_dump() for record in doc["reviews"]]


def review_status(reviews: list[dict], target: str, spec_digest: str,
                  output_hashes: dict[str, str], *, available: bool) -> dict:
    info = {"target": target, "spec_digest": spec_digest, "output_hashes": output_hashes,
            "status": "needs_review" if available else "unavailable"}
    if available:
        matching = [record for record in reviews if record["target"] == target
                    and record["spec_digest"] == spec_digest
                    and record["output_hashes"] == output_hashes]
        if matching:
            info["status"] = matching[-1]["decision"]
    return info


def record_review(root: Path, plan_ref: Path, record: dict) -> dict:
    from .film_master import FilmMasterError, _master_dir, build_report, load_plan
    review = FilmReview.model_validate(record).model_dump()
    root = root.resolve()
    plan = load_plan(root, plan_ref)
    directory = _master_dir(root, plan["plan_id"])
    with RunLease(directory / "master-journal.lock"):
        report = build_report(root, plan_ref)
        target = review["target"]
        if target == "film":
            info = report["film"]
        else:
            kind, identifier = target.split(":", 1)
            info = report[kind + "s"].get(identifier)
        if not info or info["review"]["status"] == "unavailable":
            raise FilmMasterError(f"review target is missing or not technically ready: {target}")
        binding = info["review"]
        if any(review[key] != binding[key] for key in ("spec_digest", "output_hashes")):
            raise FilmMasterError("review refers to changed content or outputs; inspect the current preview")
        records = load_reviews(root, plan["plan_id"])
        records.append(review)
        write_json(directory / "human-reviews.json", {"plan_id": plan["plan_id"], "reviews": records})
    return {"ok": True, "review": review}
