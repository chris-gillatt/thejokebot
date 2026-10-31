import base64
import copy
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from thejokebot.commands import dashboard_history, dashboard_metrics
from thejokebot.commands import dashboard_provider_telemetry as telemetry
from thejokebot.commands import dashboard_workflows, post_joke
from thejokebot import state as bot_state

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def _counters(**values):
    return {**dict.fromkeys(telemetry.FIELDS, 0), **values}


def _record(name="jokeapi", **values):
    return {"name": name, **_counters(**values)}


def _run(identifier=1, day="2026-10-30", source="jokeapi", posted=True, details=None):
    run = {
        "id": identifier,
        "attempt": 1,
        "workflow": "bluesky_post_joke",
        "created_at": day + "T12:00:00Z",
        "provider_attempts": 1,
        "starting_provider": "jokeapi",
        "successful_source": source,
        "posted": posted,
        "fallthrough": False,
        "static_fallback": source == "fallback",
    }
    if details is not None:
        run["provider_candidates"] = details
    return run


def _log(details, source="jokeapi", posted=True):
    return (
        post_joke._provider_summary_line([], "jokeapi", source, posted)
        + "\nProvider candidates: "
        + json.dumps({"schema_version": 1, "providers": details})
    )


def _js(expression, payload, controller=False):
    browser = ""
    if controller:
        browser = (
            "class Node{constructor(){this.textContent='';this.children=[];this.hidden=false;}"
            "append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}}"
            "const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Node());return elements.get(id);};"
            "const document={getElementById:get,querySelector:get,createElement:()=>new Node()};"
            "class Chart{constructor(element,config){this.data=config.data;}destroy(){}}"
            + (ROOT / "dashboard/app.js")
            .read_text()
            .removesuffix("void initialise();\n")
        )
    result = subprocess.run(
        [
            "node",
            "-e",
            "const fs=require('node:fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));"
            + (ROOT / "dashboard/history.js").read_text()
            + browser
            + f";console.log(JSON.stringify({expression}));",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_selection_counts_rejects_before_eventual_success_without_changing_result():
    duplicate = "Old joke"
    recent = {base64.b64encode(duplicate.encode()).decode()}
    fetch = Mock(side_effect=[duplicate, "x" * 500, "Fresh joke"])
    counters = _counters()
    with patch.dict(post_joke.joke_providers.PROVIDERS, {"sample": fetch}):
        result = post_joke.pick_joke(recent, "sample", telemetry=counters)
    assert result == ("Fresh joke", base64.b64encode(b"Fresh joke").decode())
    assert counters == _counters(
        fetches=3, candidates=3, duplicate=1, too_long=1, selected=1
    )
    assert telemetry.sanitise([{"name": "sample", **counters}])


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private error"),
        ValueError("private error"),
        requests.RequestException("private error"),
    ],
)
def test_fetch_failure_keeps_earlier_rejects_and_does_not_expose_error_text(error):
    counters = _counters()
    duplicate = base64.b64encode(b"Old joke").decode()
    with patch.dict(
        post_joke.joke_providers.PROVIDERS,
        {"sample": Mock(side_effect=["Old joke", error])},
    ):
        with pytest.raises(type(error)):
            post_joke.pick_joke({duplicate}, "sample", telemetry=counters)
    assert counters["fetches"] == 2
    assert counters["candidates"] == 1
    assert counters["duplicate"] == 1
    assert counters["exhausted"] == 0
    assert (
        counters[
            "network_error"
            if isinstance(error, (TimeoutError, requests.RequestException))
            else "provider_error"
        ]
        == 1
    )
    assert "private" not in json.dumps(
        telemetry.sanitise([{"name": "sample", **counters}])
    )


def test_exhaustion_is_not_an_endpoint_error():
    counters = _counters()
    with (
        patch.object(post_joke, "MAX_ATTEMPTS", 2),
        patch.dict(
            post_joke.joke_providers.PROVIDERS, {"sample": Mock(return_value="x" * 500)}
        ),
    ):
        with pytest.raises(post_joke.JokeSelectionExhausted):
            post_joke.pick_joke(set(), "sample", telemetry=counters)
    assert counters == _counters(fetches=2, candidates=2, too_long=2, exhausted=1)


@pytest.mark.parametrize("published", [True, False])
def test_real_posting_to_parser_records_source_selection_and_publication_separately(
    capsys, published
):
    client = Mock()
    client.me.handle = "bot.bsky.social"
    client.send_post.return_value = {
        "uri": "at://did:bot/app.bsky.feed.post/joke",
        "cid": "cid",
    }
    if not published:
        client.send_post.side_effect = requests.RequestException("posting failed")
    state = bot_state._default_state()
    with (
        patch.object(post_joke.bot_state, "load_state", return_value=state),
        patch.object(post_joke.bot_state, "update_state"),
        patch.object(post_joke, "login_client", return_value=(client, None)),
        patch.object(
            post_joke,
            "_provider_order_for_run",
            return_value=(["jokeapi", "groandeck"], "jokeapi"),
        ),
        patch.object(post_joke.joke_denylist, "load_denylist", return_value={}),
        patch.dict(
            post_joke.joke_providers.PROVIDERS,
            {
                "jokeapi": Mock(side_effect=TimeoutError("offline")),
                "groandeck": Mock(return_value="Fresh test joke"),
            },
        ),
    ):
        post_joke.main()
    counts = dashboard_workflows._provider_activity_counts(capsys.readouterr().out)
    assert counts is not None
    details = counts["provider_candidates"]
    assert details == [
        _record("jokeapi", fetches=1, network_error=1),
        _record(
            "groandeck", fetches=1, candidates=1, selected=1, published=int(published)
        ),
    ]
    assert counts["posted"] is published
    assert client.send_post.call_count == 1
    assert "Fresh test joke" in client.send_post.call_args.kwargs["text"]


def test_static_fallback_is_a_publication_not_an_invented_candidate_fetch(capsys):
    client = Mock()
    client.me.handle = "bot.bsky.social"
    with (
        patch.object(
            post_joke.bot_state, "load_state", return_value=bot_state._default_state()
        ),
        patch.object(post_joke.bot_state, "update_state"),
        patch.object(post_joke, "login_client", return_value=(client, None)),
        patch.object(
            post_joke, "_provider_order_for_run", return_value=(["jokeapi"], "jokeapi")
        ),
        patch.object(post_joke.joke_denylist, "load_denylist", return_value={}),
        patch.dict(
            post_joke.joke_providers.PROVIDERS,
            {"jokeapi": Mock(side_effect=ValueError("invalid payload"))},
        ),
    ):
        post_joke.main()
    counts = dashboard_workflows._provider_activity_counts(capsys.readouterr().out)
    assert counts is not None
    assert counts["successful_source"] == "fallback"
    assert counts["provider_candidates"] == [_record(fetches=1, provider_error=1)]


@pytest.mark.parametrize(
    "bad",
    [
        {},
        ["bad"],
        [_record(name="../private")],
        [_record(fetches=-1)],
        [_record(fetches=True)],
        [_record(fetches=1)],
        [_record(candidates=1)],
        [_record(selected=1)],
        [_record(published=1)],
        [_record(exhausted=2)],
        [_record(), _record()],
        [_record(fetches=2, candidates=2, selected=2)],
        [_record(fetches=1, candidates=1, selected=1, exhausted=1)],
    ],
)
def test_invalid_counter_shapes_and_invariants_are_rejected(bad):
    with pytest.raises(ValueError):
        telemetry.sanitise(bad)


def test_parser_and_history_allowlist_do_not_publish_private_fields():
    details = [_record(fetches=2, candidates=2, duplicate=1, selected=1, published=1)]
    details[0]["private_text"] = "secret"
    parsed = dashboard_workflows._provider_activity_counts(_log(details))
    assert parsed is not None
    run = _run(details=parsed["provider_candidates"])
    run["private_log"] = "secret"
    run["provider_candidates"][0]["audience_did"] = "secret"
    archive = dashboard_history._history_record(run, "activity_runs")
    metrics = dashboard_metrics._provider_pressure_metrics({"runs": [run]}, NOW)
    assert "secret" not in json.dumps(archive)
    assert "secret" not in json.dumps(metrics)
    assert archive["provider_candidates"][0]["duplicate"] == 1
    assert (
        dashboard_workflows._provider_activity_counts("No recognised summary") is None
    )
    legacy = post_joke._provider_summary_line([], "jokeapi", "jokeapi", True)
    legacy_counts = dashboard_workflows._provider_activity_counts(legacy)
    assert legacy_counts is not None
    assert "provider_candidates" not in legacy_counts
    mixed_counts = dashboard_workflows._provider_activity_counts(
        _log(details) + "\n" + legacy
    )
    assert mixed_counts is not None
    assert "provider_candidates" not in mixed_counts
    with pytest.raises(ValueError):
        dashboard_workflows._provider_activity_counts(
            legacy + '\nProvider candidates: {"schema_version":99,"providers":[]}'
        )
    with pytest.raises(ValueError):
        dashboard_workflows._provider_activity_counts(
            legacy + "\nProvider candidates: {broken}"
        )
    for malformed in ('{"schema_version":1}', "[]", '{"schema_version":1,'):
        with pytest.raises(ValueError):
            dashboard_workflows._provider_activity_counts(
                legacy + "\nProvider candidates: " + malformed
            )


def test_failed_publication_does_not_count_as_a_successful_source():
    pressure = dashboard_metrics._provider_pressure_metrics(
        {"runs": [_run(posted=False), _run(2, source="groandeck")]}, NOW
    )
    assert pressure["windows"]["7"]["successful_sources"] == {"groandeck": 1}


def test_malformed_details_report_a_collection_warning_instead_of_inventing_zeroes(
    capsys,
):
    result = dashboard_workflows._collect_run_activity(
        Mock(),
        "chris-gillatt/thejokebot",
        None,
        "bluesky_post_joke",
        123,
        NOW,
        None,
        fetch_logs=lambda *args: _log([{"name": "jokeapi"}]),
    )
    assert result == (None, NOW, None)
    assert "could not collect activity from workflow run 123" in capsys.readouterr().out


def _supply_fixture():
    return {
        "activity_runs": [
            _run(
                details=[
                    _record(
                        fetches=3, candidates=3, duplicate=2, selected=1, published=1
                    )
                ]
            ),
            _run(2, source="groandeck"),
            _run(
                3,
                source="jokeapi",
                posted=False,
                details=[_record(fetches=1, network_error=1)],
            ),
            _run(4, source="fallback", details=[]),
            _run(
                5,
                day="2026-10-29",
                details=[_record(fetches=1, candidates=1, selected=1, published=1)],
            ),
            _run(6, day="2026-10-23", source="groandeck"),
        ],
        "automation_runs": [],
        "snapshots": [],
        "daily_activity": [],
        "operational_observations": [],
    }


def test_period_aggregation_separates_legacy_outcomes_detailed_samples_and_concentration():
    result = _js(
        "DashboardHistory.providerSupply(input.data,input.period)",
        {
            "data": _supply_fixture(),
            "period": {"start": "2026-10-24", "end": "2026-10-31", "days": 7},
        },
    )
    assert result["measuredRuns"] == 5
    assert result["detailedRuns"] == 4
    assert result["published"] == 4
    assert result["failedPublications"] == 1
    assert result["leadingSource"] == "jokeapi"
    assert result["leadingShare"] == 50
    assert result["concentration"] == 0.375
    provider = result["providers"][0]
    assert provider["published"] == 2
    assert provider["fetches"] == 5
    assert provider["rejectionRate"] == 50
    assert provider["errorRate"] == 20
    assert provider["selected"] == 2
    assert provider["visits"] == 3
    assert (
        next(item for item in result["providers"] if item["name"] == "groandeck")[
            "detailed"
        ]
        is False
    )


def test_missing_days_and_failed_only_days_have_no_publication_concentration():
    data = _supply_fixture()
    data["activity_runs"].append(_run(7, day="2026-10-28", posted=False))
    result = _js(
        "DashboardHistory.series(input.data,input.period)",
        {
            "data": data,
            "period": {"start": "2026-10-27", "end": "2026-10-31", "days": 4},
        },
    )
    assert [item["providerLeadingShare"] for item in result] == [
        None,
        None,
        100,
        100 / 3,
    ]
    assert [item["providerConcentration"] for item in result] == [None, None, 1, 1 / 3]


def test_recent_metrics_and_archives_deduplicate_attempts_and_retain_candidate_counters():
    run = _run(details=[_record(fetches=1, candidates=1, selected=1, published=1)])
    partition = dashboard_history._empty_history_partition("2026-10")
    partition["activity_runs"] = [
        dashboard_history._history_record(run, "activity_runs")
    ]
    pressure = dashboard_metrics._provider_pressure_metrics({"runs": [run]}, NOW)
    result = _js(
        "DashboardHistory.merge(input.partitions,input.metrics).activity_runs",
        {
            "partitions": [partition],
            "metrics": {"provider_pressure": pressure},
        },
    )
    assert len(result) == 1
    assert result[0]["provider_candidates"][0]["published"] == 1
    different_attempt = copy.deepcopy(run)
    different_attempt["attempt"] = 2
    partition["activity_runs"].append(different_attempt)
    result = _js(
        "DashboardHistory.merge(input.partitions,input.metrics).activity_runs",
        {
            "partitions": [partition],
            "metrics": {"provider_pressure": pressure},
        },
    )
    assert len(result) == 2


def test_producer_to_browser_supply_table_uses_period_and_explicit_unavailable_states():
    result = _js(
        "(()=>{historicalViews.operations={data:input.data,period:input.period};"
        "renderProviderSupply(DashboardHistory.series(input.data,input.period),baseOptions());"
        "const text=n=>[n.textContent,...n.children.map(text)].join('|');"
        "return {table:text(get('#provider-supply-table tbody')),coverage:get('provider-supply-coverage').textContent,"
        "share:get('provider-leading-share').textContent,change:get('provider-leading-change').textContent,"
        "chart:charts.providerConcentration.data};})()",
        {
            "data": _supply_fixture(),
            "period": {"start": "2026-10-24", "end": "2026-10-31", "days": 7},
        },
        controller=True,
    )
    assert result["share"] == "50%"
    assert "-50 percentage points" in result["change"]
    assert "5/5" in result["coverage"]
    assert "4 have per-provider" in result["coverage"]
    assert "50% (2/4)" in result["table"]
    assert "20% (1/5)" in result["table"]
    assert "Not measured" in result["table"]
    assert "Historical detail unavailable" in result["table"]
    assert "2 duplicate · 1 network" in result["table"]
    assert "publicationShare" not in result["table"]
    assert "2 published" not in result["table"]
    assert "1 detailed" not in result["table"]
    assert result["chart"]["datasets"][0]["data"][-1] == pytest.approx(100 / 3)


def test_empty_provider_browser_view_has_no_invented_rates_or_zero_baseline_comparison():
    data = _supply_fixture()
    data["activity_runs"] = []
    result = _js(
        "(()=>{historicalViews.operations={data:input.data,period:input.period};"
        "renderProviderSupply(DashboardHistory.series(input.data,input.period),baseOptions());"
        "return {share:get('provider-leading-share').textContent,index:get('provider-concentration').textContent,"
        "change:get('provider-leading-change').textContent,empty:!get('provider-supply-empty').hidden};})()",
        {
            "data": data,
            "period": {"start": "2026-10-24", "end": "2026-10-31", "days": 7},
        },
        controller=True,
    )
    assert result == {
        "share": "--",
        "index": "--",
        "change": "Comparison unavailable",
        "empty": True,
    }


def test_invalid_browser_candidate_counts_surface_an_error():
    data = _supply_fixture()
    data["activity_runs"][0]["provider_candidates"][0]["fetches"] = -1
    result = _js(
        "(()=>{try{DashboardHistory.providerSupply(input.data,input.period);return null;}"
        "catch(error){return error.message;}})()",
        {
            "data": data,
            "period": {"start": "2026-10-24", "end": "2026-10-31", "days": 7},
        },
    )
    assert result == "Invalid provider candidate counters in history."
