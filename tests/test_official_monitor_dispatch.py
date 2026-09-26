from scripts.official_monitor_dispatch import candidate_ready, resolve_dispatch


def test_scheduled_sync_without_candidate_requests_one_monitor_poll() -> None:
    decision = resolve_dispatch(
        event_name="schedule",
        notify=True,
        latest_financialjuice=False,
        manual_replay_count=0,
        has_candidate=False,
    )

    assert decision.should_dispatch is True
    assert decision.reason == "scheduled_monitor_poll"
    assert decision.payload_reason == "gmail-scheduled-monitor-poll"


def test_repository_dispatch_without_candidate_requests_monitor_poll() -> None:
    decision = resolve_dispatch(
        event_name="repository_dispatch",
        notify=True,
        latest_financialjuice=False,
        manual_replay_count=0,
        has_candidate=False,
    )

    assert decision.should_dispatch is True
    assert decision.reason == "repository_dispatch_monitor_poll"


def test_candidate_uses_one_candidate_dispatch_instead_of_additional_poll() -> None:
    decision = resolve_dispatch(
        event_name="schedule",
        notify=True,
        latest_financialjuice=False,
        manual_replay_count=0,
        has_candidate=True,
    )

    assert decision.should_dispatch is True
    assert decision.reason == "reviewed_candidate"
    assert decision.payload_reason == "gmail-reviewed-observation-or-recovery"


def test_manual_workflow_dispatch_without_candidate_stays_opt_in_and_quiet() -> None:
    decision = resolve_dispatch(
        event_name="workflow_dispatch",
        notify=True,
        latest_financialjuice=False,
        manual_replay_count=0,
        has_candidate=False,
    )

    assert decision.should_dispatch is False
    assert decision.reason == "manual_run_without_candidate"


def test_notify_false_blocks_periodic_and_candidate_dispatches() -> None:
    for event_name, has_candidate in (
        ("schedule", False),
        ("repository_dispatch", False),
        ("workflow_dispatch", True),
    ):
        decision = resolve_dispatch(
            event_name=event_name,
            notify=False,
            latest_financialjuice=False,
            manual_replay_count=0,
            has_candidate=has_candidate,
        )
        assert decision.should_dispatch is False
        assert decision.reason == "notify_disabled"


def test_latest_financialjuice_replay_never_triggers_monitor() -> None:
    decision = resolve_dispatch(
        event_name="repository_dispatch",
        notify=True,
        latest_financialjuice=True,
        manual_replay_count=0,
        has_candidate=True,
    )

    assert decision.should_dispatch is False
    assert decision.reason == "manual_replay_suppressed"


def test_manual_replay_marker_never_triggers_monitor() -> None:
    decision = resolve_dispatch(
        event_name="schedule",
        notify=True,
        latest_financialjuice=False,
        manual_replay_count=1,
        has_candidate=True,
    )

    assert decision.should_dispatch is False
    assert decision.reason == "manual_replay_suppressed"


def test_durable_pending_refs_and_counts_are_candidates() -> None:
    assert candidate_ready({
        "priority_pending_count": 1,
        "candidate_diagnostics": {"counts": {}},
    })
    assert candidate_ready({
        "candidate_diagnostics": {
            "counts": {},
            "priority_pending_refs": ["pending-1"],
        },
    })


def test_boolean_is_not_accepted_as_candidate_count() -> None:
    assert candidate_ready({
        "material_candidate_count": True,
        "priority_candidate_count": False,
        "candidate_diagnostics": {"counts": {"priority_candidate_detected": True}},
    }) is False
