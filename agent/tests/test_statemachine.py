"""Stage order, retry classification, and backoff policy as data."""

from __future__ import annotations

import pytest

from minecraft_film_agent import statemachine
from minecraft_film_agent.production_models import ErrorClass, RetryScope, StageName


def test_stage_order_is_fixed_and_forward_only() -> None:
    assert statemachine.first_stage() is StageName.VALIDATE_PLAN
    # the v2 recording checkpoints, in the order that reflects real boundaries
    assert statemachine.next_stage(StageName.COMPOSE_TAKE) is StageName.PREPARE_RECORDING
    assert statemachine.next_stage(StageName.PREPARE_RECORDING) is StageName.START_RECORDING
    assert statemachine.next_stage(StageName.START_RECORDING) is StageName.RUN_TIMELINE
    assert statemachine.next_stage(StageName.RUN_TIMELINE) is StageName.STOP_RECORDING
    assert statemachine.next_stage(StageName.STOP_RECORDING) is StageName.SAVE_MOCAP
    assert statemachine.next_stage(StageName.SAVE_MOCAP) is StageName.AWAIT_REPLAY
    assert statemachine.next_stage(StageName.AWAIT_REPLAY) is StageName.APPLY_CAMERA
    assert statemachine.next_stage(StageName.APPROVE_FINAL) is None
    assert statemachine.is_legal_transition(StageName.SAVE_MOCAP, StageName.AWAIT_REPLAY)
    assert not statemachine.is_legal_transition(StageName.SAVE_MOCAP, StageName.COMPOSE_TAKE)
    assert not statemachine.is_legal_transition(StageName.VALIDATE_PLAN, StageName.EXPORT_SHOT)
    with pytest.raises(statemachine.InvalidStageTransition):
        statemachine.require_transition(StageName.VALIDATE_PLAN, StageName.EXPORT_SHOT)


def test_mocap_feedback_unknown_never_retries() -> None:
    policy = statemachine.retry_policy_for(ErrorClass.MOCAP_FEEDBACK_UNKNOWN)
    assert policy.scope is RetryScope.NONE


def test_transient_failures_get_bounded_backoff() -> None:
    policy = statemachine.retry_policy_for(ErrorClass.BRIDGE_UNAVAILABLE)
    assert policy.scope is RetryScope.STAGE
    assert policy.max_attempts == 5
    assert statemachine.backoff_sequence(policy) == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_timeout_unknown_is_resolvable_not_ignored() -> None:
    policy = statemachine.retry_policy_for(ErrorClass.OPERATION_TIMEOUT_UNKNOWN)
    assert policy.scope is RetryScope.STAGE
    assert statemachine.is_retryable(ErrorClass.OPERATION_TIMEOUT_UNKNOWN)


def test_media_failures_retry_export_only() -> None:
    for error_class in (ErrorClass.MEDIA_VALIDATION_FAILED, ErrorClass.EXPORT_FAILED):
        policy = statemachine.retry_policy_for(error_class)
        assert policy.scope is RetryScope.EXPORT_ONLY
        assert policy.max_attempts == 3


def test_version_path_and_approval_failures_never_retry() -> None:
    never = (
        ErrorClass.ENVIRONMENT_MISMATCH,
        ErrorClass.AUTHENTICATION_FAILED,
        ErrorClass.WORLD_MISMATCH,
        ErrorClass.ASSET_MISSING,
        ErrorClass.OPERATION_REJECTED,
        ErrorClass.APPROVAL_REQUIRED,
        ErrorClass.VALIDATION_FAILED,
        ErrorClass.EDITOR_NOT_READY,
        ErrorClass.MANUAL_INTERVENTION_REQUIRED,
    )
    for error_class in never:
        assert statemachine.retry_policy_for(error_class).scope is RetryScope.NONE
        assert not statemachine.is_retryable(error_class)
    assert statemachine.backoff_sequence(statemachine.retry_policy_for(ErrorClass.WORLD_MISMATCH)) == []
