"""Deterministic stage machine for the production chain.

Legal stage order is fixed; every transition is checked against it. Retry
behavior is a function of the structured ``ErrorClass`` — never of a model's
judgement — and follows implementation plan §10.3 / architecture spec §9:
reads may back off, timeout-unknown writes must be resolved by state reads,
media failures retry only the export node, and version/path/approval
failures never retry.
"""

from __future__ import annotations

from .production_models import (
    ErrorClass,
    RETRY_POLICIES,
    RetryPolicy,
    RetryScope,
    STAGE_ORDER,
    StageName,
)

# The explicit order lives in production_models (single source of truth).
STAGE_ORDER: list[StageName] = list(STAGE_ORDER)


class InvalidStageTransition(RuntimeError):
    pass


def first_stage() -> StageName:
    return STAGE_ORDER[0]


def next_stage(stage: StageName) -> StageName | None:
    index = STAGE_ORDER.index(stage)
    if index + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[index + 1]


def is_legal_transition(current: StageName, target: StageName) -> bool:
    """Forward-only movement through the fixed order."""

    try:
        return STAGE_ORDER.index(target) == STAGE_ORDER.index(current) + 1
    except ValueError:
        return False


def require_transition(current: StageName, target: StageName) -> None:
    if not is_legal_transition(current, target):
        raise InvalidStageTransition(
            f"illegal stage transition {current} -> {target}"
        )


def retry_policy_for(error_class: ErrorClass) -> RetryPolicy:
    return RETRY_POLICIES[error_class]

def is_retryable(error_class: ErrorClass) -> bool:
    return retry_policy_for(error_class).scope is not RetryScope.NONE


def backoff_sequence(policy: RetryPolicy) -> list[float]:
    """Delay before each allowed attempt: 1s → 2s → 4s → 8s → 16s (spec §9)."""

    if policy.scope is RetryScope.NONE:
        return []
    sequence: list[float] = []
    delay = policy.backoff_seconds
    for _ in range(policy.max_attempts):
        sequence.append(delay)
        delay = min(delay * 2, 16.0)
    return sequence
