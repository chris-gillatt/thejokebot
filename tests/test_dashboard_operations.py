import copy
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from thejokebot.commands import (
    dashboard_history,
    dashboard_metrics,
    dashboard_workflows,
)
from thejokebot.commands import dashboard_operations as operations
from thejokebot.commands import collect_dashboard_metrics as collector
from thejokebot.commands import dashboard_engagement
from thejokebot.paths import PROJECT_ROOT
from test_dashboard_providers import _js

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
PERIOD = {"start": "2026-10-24", "end": "2026-10-31", "days": 7}


def _run(
    identifier=1, conclusion="failure", attempt=1, name="python_tests", day="2026-10-29"
):
    return {
        "id": identifier,
        "name": name,
        "run_attempt": attempt,
        "created_at": day + "T12:00:00Z",
        "updated_at": day + "T12:05:00Z",
        "status": "completed",
        "conclusion": conclusion,
    }


def _steps(name: object = "Run unit tests"):
    return [{"job_id": 999, "number": 7, "name": name}]


def _response(jobs):
    response = Mock()
    response.json.return_value = {"jobs": jobs}
    return response


def test_job_pagination_fetches_the_exact_run_attempt_and_only_allowlisted_names():
    session = Mock()
    jobs = [
        {
            "id": 999,
            "conclusion": "failure",
            "steps": [
                {"number": 7, "name": "Run unit tests", "conclusion": "failure"},
                {"number": 8, "name": "Run secret command", "conclusion": "failure"},
                {"number": 9, "name": "Success step", "conclusion": "success"},
            ],
        }
    ] + [{"id": index, "conclusion": "success"} for index in range(99)]
    session.get.side_effect = [_response(jobs), _response([])]
    results = operations.fetch_failed_steps(
        session, "chris-gillatt/thejokebot", 123, 2, {}, lambda fn, **kwargs: fn()
    )
    assert results == [
        _steps()[0],
        {"number": 8, "job_id": 999, "name": "Step 8 (name unavailable)"},
    ]
    assert "/123/attempts/2/jobs" in session.get.call_args_list[0].args[0]
    assert [call.kwargs["params"]["page"] for call in session.get.call_args_list] == [
        1,
        2,
    ]
    assert "secret" not in str(results)


@pytest.mark.parametrize(
    "jobs",
    [
        None,
        ["invalid"],
        [{"id": 1, "conclusion": "failure"}],
        [{"id": 1, "conclusion": "failure", "steps": [None]}],
    ],
)
def test_invalid_jobs_fail_explicitly(jobs):
    session = Mock()
    session.get.return_value = _response(jobs)
    with pytest.raises(ValueError):
        operations.fetch_failed_steps(
            session, "owner/repo", 1, 1, {}, lambda fn, **kwargs: fn()
        )


def test_jobs_safety_limit_does_not_return_partial_success():
    session = Mock()
    session.get.return_value = _response(
        [{"id": index, "conclusion": "success"} for index in range(100)]
    )
    with (
        patch.object(operations, "MAX_JOB_PAGES", 1),
        pytest.raises(RuntimeError, match="safety limit"),
    ):
        operations.fetch_failed_steps(
            session, "owner/repo", 1, 1, {}, lambda fn, **kwargs: fn()
        )


@pytest.mark.parametrize(
    "steps",
    [
        None,
        [{}],
        [{"number": True, "job_id": 1}],
        [{"number": -1, "job_id": 1}],
        [{"number": 1, "job_id": 0}],
    ],
)
def test_step_identity_validation(steps):
    with pytest.raises(ValueError):
        operations.sanitise_steps(steps)


def test_failed_job_without_a_failed_step_has_honest_unknown_step_metadata():
    result = operations._job_steps([{"id": 5, "conclusion": "failure", "steps": []}])
    assert result == [{"number": 0, "job_id": 5, "name": "Step 0 (name unavailable)"}]
    assert (
        operations.sanitise_steps(_steps(name=["private"]))[0]["name"]
        == "Step 7 (name unavailable)"
    )


def test_cached_attempt_metadata_is_reused_but_retries_fetch_new_metadata():
    run = _run()
    cached = operations.public_runs(
        [{**run, "failure_metadata": "available", "failed_steps": _steps()}],
        {"python_tests"},
    )
    fetch = Mock(return_value=_steps())
    original = copy.deepcopy(run)
    first = operations.enrich_runs([run], cached, {"python_tests"}, fetch)
    assert fetch.call_count == 0
    assert first[0]["failure_metadata"] == "available"
    assert run == original
    retried = operations.enrich_runs(
        [{**run, "run_attempt": 2}], cached, {"python_tests"}, fetch
    )
    fetch.assert_called_once_with(1, 2)
    assert retried[0]["failed_steps"] == _steps()


def test_metadata_failure_warns_and_remains_unavailable_with_a_successful_retry(capsys):
    fetch = Mock(side_effect=requests.RequestException("GitHub API unavailable"))
    first = operations.enrich_runs([_run()], [], {"python_tests"}, fetch)
    assert first[0]["failure_metadata"] == "unavailable"
    assert "metadata unavailable for run 1" in capsys.readouterr().out
    cached = operations.public_runs(first, {"python_tests"})
    fetch.side_effect = None
    fetch.return_value = _steps()
    retried = operations.enrich_runs([_run()], cached, {"python_tests"}, fetch)
    assert retried[0]["failure_metadata"] == "available"
    assert fetch.call_count == 2


def test_running_cancelled_success_and_untracked_runs_do_not_fetch_failure_steps():
    fetch = Mock()
    runs = [
        _run(conclusion="cancelled"),
        _run(conclusion="success"),
        {**_run(), "status": "in_progress"},
        _run(name="third_party_workflow"),
    ]
    assert operations.enrich_runs(runs, [], {"python_tests"}, fetch) == runs
    fetch.assert_not_called()
    assert len(operations.public_runs(runs, {"python_tests"})) == 3


def test_failed_steps_round_trip_through_archive_and_collector_cache_without_private_text():
    run = {
        **_run(),
        "failure_metadata": "available",
        "failed_steps": _steps("Run token=private"),
    }
    record = operations.public_runs([run], {"python_tests"})[0]
    record["failed_steps"][0]["raw_log"] = "private"
    archived = dashboard_history._history_record(record, "automation_runs")
    assert "private" not in str(archived)
    partition = dashboard_history._empty_history_partition("2026-10")
    partition["automation_runs"] = [archived]
    rebuilt = dashboard_history._collector_existing(None, {"2026-10": partition}, NOW)
    assert rebuilt["automation_runs"] == [archived]
    data = _js(
        "DashboardHistory.merge(input.partitions,input.metrics)",
        {
            "partitions": [partition],
            "metrics": {"operations": {"workflow_runs": [archived]}},
        },
    )
    assert data["automation_runs"] == [archived]


def test_incidents_preserve_retry_identity_and_only_success_establishes_workflow_recovery():
    runs = [
        _run(),
        _run(2, conclusion="cancelled"),
        _run(3),
        _run(4, conclusion="success"),
        _run(5, day="2026-10-30"),
        {**_run(6), "status": "queued"},
    ]
    public = operations.public_runs(runs, {"python_tests"})
    result = _js(
        "DashboardHistory.incidents(input.data,input.period)",
        {"data": {"automation_runs": public}, "period": PERIOD},
    )
    assert len(result) == 2
    assert result[0]["recovery"] is None
    assert [run["id"] for run in result[1]["failures"]] == [1, 3]
    assert result[1]["recovery"]["id"] == 4
    retry = operations.public_runs(
        [_run(), _run(conclusion="success", attempt=2)], {"python_tests"}
    )
    result = _js(
        "DashboardHistory.incidents(input.data,input.period)",
        {"data": {"automation_runs": retry}, "period": PERIOD},
    )
    assert result[0]["recovery"]["attempt"] == 2


def test_historical_incidents_outside_period_are_excluded_without_inventing_recovery():
    public = operations.public_runs([_run(day="2026-09-10")], {"python_tests"})
    assert (
        _js(
            "DashboardHistory.incidents(input.data,input.period)",
            {"data": {"automation_runs": public}, "period": PERIOD},
        )
        == []
    )


def test_retry_recovery_uses_outcome_time_not_the_original_run_creation_time():
    runs = operations.public_runs(
        [
            {**_run(day="2026-09-01"), "updated_at": "2026-10-29T12:00:00Z"},
            _run(2, day="2026-10-30"),
            {
                **_run(day="2026-09-01", conclusion="success", attempt=2),
                "updated_at": "2026-10-30T14:00:00Z",
            },
        ],
        {"python_tests"},
    )
    episodes = _js(
        "DashboardHistory.incidents(input.data,input.period)",
        {"data": {"automation_runs": runs}, "period": PERIOD},
    )
    assert len(episodes) == 1
    assert [run["id"] for run in episodes[0]["failures"]] == [1, 2]
    assert episodes[0]["recovery"]["attempt"] == 2
    assert episodes[0]["first_failure_at"] == "2026-10-29T12:00:00Z"


def test_slot_exceptions_use_single_publication_matching_and_closed_slots():
    start = NOW.replace(hour=0)
    slots = [start, start + timedelta(hours=4), start + timedelta(hours=8)]
    publications = [
        start + timedelta(minutes=30),
        start + timedelta(hours=4, minutes=31),
    ]
    summary = dashboard_metrics._summarise_posting_slots(
        slots, publications, timedelta(hours=2), include_exceptions=True
    )
    assert summary["delivered"] == 2
    assert summary["delayed"] == 1
    assert summary["exceptions"] == [
        {
            "slot_at": slots[1].isoformat(),
            "published_at": publications[1].isoformat(),
            "outcome": "delayed",
        },
        {"slot_at": slots[2].isoformat(), "published_at": None, "outcome": "missed"},
    ]
    delivery = dashboard_metrics._posting_delivery(
        {"posted_jokes": []}, "0 */4 * * *", NOW
    )
    assert all(
        datetime.fromisoformat(item["slot_at"]) + timedelta(hours=2) <= NOW
        for item in delivery["closed_slot_exceptions"]
    )
    assert not any(
        item["slot_at"].endswith("12:00:00+00:00")
        and item["slot_at"].startswith("2026-10-31")
        for item in delivery["closed_slot_exceptions"]
    )


def test_component_observations_use_real_cached_times_and_preserve_last_success():
    runs = [
        _run(name="bluesky_follows_and_likes", conclusion="success", day="2026-10-29"),
        _run(2, name="bluesky_follows_and_likes", day="2026-10-30"),
        {
            **_run(3, name="bluesky_follows_and_likes", conclusion="success"),
            "status": "in_progress",
        },
    ]
    automation = dashboard_workflows._workflow_metrics(runs, NOW)
    components = operations.component_observations(
        {
            "joke_requests": {"last_checked_at": (NOW - timedelta(days=2)).timestamp()},
            "provider": {
                "health_checks": {
                    "jokeapi": {"last_check_at": (NOW - timedelta(days=3)).timestamp()}
                }
            },
        },
        {
            "runs": [
                {
                    "workflow": "bluesky_follows_and_likes",
                    "social_summary_observed": True,
                    "created_at": "2026-10-29T12:00:00Z",
                },
                {
                    "workflow": "bluesky_follows_and_likes",
                    "social_summary_observed": False,
                    "created_at": "2026-10-31T12:00:00Z",
                },
            ]
        },
        automation,
        NOW,
    )
    values = {item["name"]: item for item in components}
    assert values["Joke-request checkpoint"]["overdue"]
    assert values["Social action summary"]["observed_at"] == "2026-10-29T12:00:00Z"
    assert values["Social action summary"]["last_success_at"] == "2026-10-29T12:05:00Z"
    assert values["Moderation summary"]["observed_at"] is None
    assert values["jokeapi availability"]["observed_at"] != NOW.isoformat()


def test_zero_checkpoint_is_unobserved_not_a_fabricated_epoch_observation():
    components = operations.component_observations(
        {"joke_requests": {"last_checked_at": 0}},
        None,
        dashboard_workflows._workflow_metrics([], NOW),
        NOW,
    )
    checkpoint = next(
        item for item in components if item["name"] == "Joke-request checkpoint"
    )
    assert checkpoint["observed_at"] is None
    assert not checkpoint["overdue"]


def test_incident_browser_links_and_ci_production_classification():
    runs = operations.public_runs(
        [{**_run(), "failed_steps": _steps()}, _run(2, conclusion="success")],
        {"python_tests"},
    )
    result = _js(
        "(()=>{metrics={operations:{ci_workflows:['python_tests']}};"
        "historicalViews.operations={data:{automation_runs:input.runs},period:input.period};"
        "renderIncidentHistory();const text=n=>[n.textContent,...n.children.map(text)].join('|');"
        "const body=get('#incident-table tbody');return {text:text(body),link:body.children[0].children[2].children[0].children[0].children[0].href};})()",
        {"runs": runs, "period": PERIOD},
        controller=True,
    )
    assert "Python tests (CI)" in result["text"]
    assert "Run unit tests" in result["text"]
    assert "Successful run 2" in result["text"]
    assert result["link"].endswith("/actions/runs/1/attempts/1")
    invalid = _js(
        "(()=>{try{return runLink({id:-1,attempt:1},'bad');}catch(error){return error.message;}})()",
        {},
        controller=True,
    )
    assert invalid == "Invalid workflow run identity."


def test_collector_fetch_wrapper_reuses_the_existing_github_request_contract():
    session = Mock()
    with patch.object(operations, "fetch_failed_steps", return_value=_steps()) as fetch:
        assert (
            collector.fetch_failed_steps(session, "owner/repo", 123, 2, None)
            == _steps()
        )
    assert fetch.call_args.args[:4] == (session, "owner/repo", 123, 2)
    assert fetch.call_args.args[4] == dashboard_workflows._github_headers(None)


def test_main_persists_sanitised_failure_receipts_and_reuses_the_archive(tmp_path):
    history_dir = tmp_path / "history"
    metrics_file = tmp_path / "metrics.json"
    receipt_file = tmp_path / "engagement.json"
    original_load = dashboard_history._load_history_partitions
    original_existing = dashboard_history._collector_existing
    original_write = dashboard_history._write_history
    uri = "at://did:bot/app.bsky.feed.post/joke"
    post = {
        "uri": uri,
        "record": {
            "text": "Public test joke",
            "createdAt": (NOW - timedelta(hours=26)).isoformat(),
        },
    }
    profile = {
        "did": "did:bot",
        "handle": "bot.bsky.social",
        "followersCount": 1,
        "followsCount": 1,
        "postsCount": 1,
    }
    with (
        patch.dict("os.environ", {"BLUESKY_USERNAME": "bot.bsky.social"}),
        patch.object(collector, "datetime") as clock,
        patch.object(collector, "METRICS_FILE", metrics_file),
        patch.object(dashboard_engagement, "STATE_FILE", receipt_file),
        patch.object(
            dashboard_history,
            "_load_history_partitions",
            side_effect=lambda: original_load(history_dir),
        ),
        patch.object(
            dashboard_history,
            "_collector_existing",
            side_effect=lambda existing, partitions, now: original_existing(
                existing, partitions, now, history_dir
            ),
        ),
        patch.object(
            dashboard_history,
            "_write_history",
            side_effect=lambda partitions, now, activity: original_write(
                partitions, now, activity, history_dir
            ),
        ),
        patch.object(
            collector,
            "fetch_workflow_runs",
            return_value=[{**_run(), "private_branch": "private"}],
        ),
        patch.object(collector, "fetch_failed_steps", return_value=_steps()) as steps,
        patch.object(collector, "collect_workflow_activity", return_value={}),
        patch.object(collector, "fetch_profile", return_value=profile),
        patch.object(collector, "fetch_post", return_value=post),
        patch.object(collector, "fetch_original_posts", return_value=[post]),
        patch.object(
            collector.bot_state,
            "load_state",
            return_value={
                "posted_jokes": [
                    {"post_uri": uri, "ts": (NOW - timedelta(hours=26)).timestamp()}
                ]
            },
        ),
    ):
        clock.now.return_value = NOW
        collector.main()
        public = json.loads(metrics_file.read_text())
        assert public["operations"]["workflow_runs"][0]["failed_steps"] == _steps()
        assert "private" not in metrics_file.read_text()
        assert (
            original_load(history_dir)["2026-10"]["automation_runs"][0]["failed_steps"]
            == _steps()
        )
        collector.main()
        assert steps.call_count == 1


def test_production_pulse_does_not_treat_a_ci_failure_as_a_posting_failure():
    result = _js(
        "(()=>{metrics={generated_at:new Date().toISOString(),operations:{ci_workflows:['python_tests'],"
        "components:[{name:'Joke-request checkpoint',observed_at:'2026-10-30T12:00:00Z',overdue:true}]},"
        "posting_delivery:{closed_slot_exceptions:[]}};"
        "renderOperationalPulse({alerts:[{kind:'workflow_failure_streak',workflow:'python_tests',count:2}]});"
        "const text=n=>[n.textContent,...n.children.map(text)].join('|');"
        "return {production:text(get('operational-pulse')),ci:text(get('ci-pulse')),checkpoint:get('production-checkpoint').textContent,"
        "freshness:text(get('#component-freshness-table tbody'))};})()",
        {},
        controller=True,
    )
    assert "No production alerts" in result["production"]
    assert "Python tests failed 2" in result["ci"]
    assert "30 Oct" in result["checkpoint"]
    assert "Overdue at collection" in result["freshness"]


def test_production_pulse_retains_stale_collection_and_actual_workflow_failure_alerts():
    result = _js(
        "(()=>{metrics={generated_at:'2000-01-01T00:00:00Z',operations:{ci_workflows:['python_tests'],components:[]}};"
        "renderOperationalPulse({alerts:[{kind:'workflow_failure',workflow:'bluesky_post_joke'}]});"
        "const text=n=>[n.textContent,...n.children.map(text)].join('|');return text(get('operational-pulse'));})()",
        {},
        controller=True,
    )
    assert "Dashboard collection is overdue" in result
    assert "Post joke failed most recently" in result


def test_legacy_slot_detail_is_unavailable_not_a_fabricated_healthy_result():
    result = _js(
        "(()=>{metrics={};renderComponentFreshness();return get('slot-exceptions-empty').textContent;})()",
        {},
        controller=True,
    )
    assert (
        result == "Closed-slot exception detail unavailable in this metrics snapshot."
    )


def test_slot_inspection_button_focuses_the_region_without_a_static_tab_stop():
    result = _js(
        "(()=>{metrics={generated_at:'2026-10-31T12:00:00Z'};"
        "document.querySelectorAll=()=>[];Node.prototype.addEventListener=function(type,handler){this[type]=handler;};"
        "Node.prototype.focus=function(){this.focused=true;};bindRangeControls();"
        "get('slot-exceptions-inspect').click();return get('slot-exceptions-region').focused;})()",
        {},
        controller=True,
    )
    assert result is True
    html = (PROJECT_ROOT / "dashboard/index.html").read_text()
    assert (
        '<section id="slot-exceptions-region" class="table-scroll" tabindex="-1"'
        in html
    )
    assert 'aria-controls="slot-exceptions-region"' in html
