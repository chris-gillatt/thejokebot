import json
import subprocess
from pathlib import Path

import pytest

from thejokebot.commands import dashboard_history


ROOT = Path(__file__).resolve().parents[1]
HISTORY_JS = ROOT / "dashboard" / "history.js"


def _javascript(expression, payload=None, *, controller=False):
    browser = ""
    if controller:
        browser = (
            "const elements=new Map();"
            "const node=()=>({textContent:'',hidden:false,append(){},replaceChildren(){},"
            "classList:{toggle(){}}});"
            "const document={getElementById:id=>{if(!elements.has(id))elements.set(id,node());"
            "return elements.get(id);},querySelector:()=>node(),querySelectorAll:()=>[],"
            "createElement:()=>node()};"
            "class Chart {constructor(element,config){this.data=config.data;}destroy(){}}"
            + (ROOT / "dashboard" / "app.js")
            .read_text()
            .removesuffix("void initialise();\n")
        )
    result = subprocess.run(
        [
            "node",
            "-e",
            'const fs = require("node:fs");'
            'const input = JSON.parse(fs.readFileSync(0, "utf8"));'
            + HISTORY_JS.read_text()
            + browser
            + ";(async () => { const result = await ("
            + expression
            + "); console.log(JSON.stringify(result)); })().catch(error => {"
            + "console.error(error.message);process.exitCode=1;});",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("selection", "generated", "custom", "start", "end", "days"),
    [
        ("7", "2026-10-27T13:00:00Z", {}, "2026-10-20", "2026-10-27", 7),
        ("90", "2026-01-01T00:01:00Z", {}, "2025-10-03", "2026-01-01", 90),
        ("ytd", "2024-03-01T12:00:00Z", {}, "2024-01-01", "2024-03-01", 60),
        (
            "custom",
            "2024-03-02T00:00:00Z",
            {"start": "2024-02-28", "end": "2024-02-29"},
            "2024-02-28",
            "2024-03-01",
            2,
        ),
    ],
)
def test_history_ranges_use_complete_utc_days(
    selection, generated, custom, start, end, days
):
    actual = _javascript(
        "DashboardHistory.range(input.selection,input.generated,input.custom)",
        {"selection": selection, "generated": generated, "custom": custom},
    )
    assert actual == {"start": start, "end": end, "days": days}
    previous = _javascript("DashboardHistory.previous(input)", actual)
    assert previous["end"] == start
    assert previous["days"] == days


@pytest.mark.parametrize(
    "custom",
    [
        {"start": "2026-02-29", "end": "2026-03-01"},
        {"start": "2026-10-28", "end": "2026-10-26"},
        {"start": "2026-10-20", "end": "2026-10-27"},
        {"start": "", "end": "2026-10-26"},
    ],
)
def test_invalid_or_incomplete_date_ranges_fail_explicitly(custom):
    actual = _javascript(
        "(() => { try { DashboardHistory.range('custom', '2026-10-27T12:00:00Z', input);"
        "return false; } catch (error) { return error.message; } })()",
        custom,
    )
    assert isinstance(actual, str)
    assert actual


def test_loading_fetches_only_required_months_and_does_not_trust_index_paths():
    actual = _javascript(
        "(async () => { const paths=[];"
        "await DashboardHistory.loadPartitions(input.index,input.period,async path=>{"
        "paths.push(path);return {month:path.slice(13,17)+'-'+path.slice(18,20)};});"
        "return paths; })()",
        {
            "index": {
                "schema_version": 1,
                "months": [
                    {"month": month, "path": "https://invalid.example/private"}
                    for month in ("2026-02", "2026-08", "2026-09", "2026-10")
                ],
            },
            "period": {"start": "2026-10-20", "end": "2026-10-27", "days": 7},
        },
    )
    assert actual == ["data/history/2026/10.json"]


def test_history_loading_errors_are_reported_and_can_be_retried():
    actual = _javascript(
        "(async () => { const index={schema_version:1,months:[{month:'2026-10'}]};"
        "const period={start:'2026-10-20',end:'2026-10-27',days:7};let failure;"
        "try { await DashboardHistory.loadPartitions(index,period,async()=>{throw new Error('HTTP 503');});"
        "} catch(error) { failure=error.message; }"
        "const retried=await DashboardHistory.loadPartitions(index,period,async()=>({month:'2026-10'}));"
        "return {failure,months:retried.map(p=>p.month)}; })()"
    )
    assert actual == {"failure": "HTTP 503", "months": ["2026-10"]}


def test_archived_producer_data_is_deduplicated_and_rolling_values_are_not_summed():
    metrics = {
        "generated_at": "2026-10-26T18:05:00+00:00",
        "snapshots": [
            {
                "period_start": "2026-10-25T18:00:00+00:00",
                "collected_at": "2026-10-25T18:05:00+00:00",
                "followers": 100,
                "engagement_total": 200,
                "source": "bluesky_snapshot",
            },
            {
                "period_start": "2026-10-26T18:00:00+00:00",
                "collected_at": "2026-10-26T18:05:00+00:00",
                "followers": 104,
                "engagement_total": 215,
                "source": "bluesky_snapshot",
            },
        ],
        "daily_activity": [
            {"date": "2026-10-26", "joke_posts": 6, "follows": 10, "unfollows": 0}
        ],
        "posting_delivery": {"windows": {"7": {"delivery_rate": 100}}},
        "workflow_activity": {
            "runs": [
                {
                    "id": 42,
                    "attempt": 1,
                    "workflow": "bluesky_post_joke",
                    "created_at": "2026-10-26T12:00:00Z",
                    "posted": True,
                    "fallthrough": True,
                }
            ]
        },
    }
    automation = [
        {
            "id": 42,
            "run_attempt": attempt,
            "name": "bluesky_post_joke",
            "created_at": "2026-10-26T12:00:00Z",
            "status": "completed",
            "conclusion": conclusion,
        }
        for attempt, conclusion in ((1, "failure"), (2, "success"))
    ]
    partitions = dashboard_history._history_from_collection(metrics, automation)
    actual = _javascript(
        "(() => {const data=DashboardHistory.merge(input.partitions,input.metrics);"
        "const period={start:'2026-10-26',end:'2026-10-27',days:1};"
        "return {summary:DashboardHistory.summary(data,period),"
        "series:DashboardHistory.series(data,period),runs:data.activity_runs.length};})()",
        {"partitions": list(partitions.values()), "metrics": metrics},
    )
    assert actual["runs"] == 1
    summary = actual["summary"]
    assert summary["followers"] == 4
    assert summary["engagement"] == 15
    assert summary["jokes"] == 6
    assert summary["follows"] == 10
    assert summary["completed"] == 2
    assert summary["failed"] == 1
    assert summary["successRate"] == 50
    assert summary["fallthroughRate"] == 100
    assert actual["series"][0]["deliveryRate"] == 100
    assert "delivered" not in summary


def test_missing_history_is_a_gap_not_a_zero_or_complete_period_total():
    actual = _javascript(
        "(() => {const data=DashboardHistory.merge([],input);"
        "const period={start:'2026-10-25',end:'2026-10-27',days:2};"
        "return {summary:DashboardHistory.summary(data,period),"
        "series:DashboardHistory.series(data,period),availability:DashboardHistory.availability(data)};})()",
        {
            "daily_activity": [{"date": "2026-10-26", "joke_posts": 0}],
            "snapshots": [],
        },
    )
    assert actual["summary"]["jokes"] is None
    assert actual["summary"]["observedActivity"]["jokes"] == {"days": 1, "total": 0}
    assert actual["summary"]["followers"] is None
    assert actual["summary"]["successRate"] is None
    assert actual["summary"]["fallthroughRate"] is None
    assert actual["series"][0]["joke_posts"] is None
    assert actual["series"][1]["joke_posts"] == 0
    assert actual["availability"]["audience"] is None
    assert actual["availability"]["activity"] == "2026-10-26"


def test_compact_daily_history_supports_audience_comparisons_without_monthly_downloads():
    actual = _javascript(
        "(() => {const data=DashboardHistory.merge([],input.metrics,input.daily);"
        "return {summary:DashboardHistory.summary(data,{start:'2026-10-26',end:'2026-10-27',days:1}),"
        "snapshots:data.snapshots.length};})()",
        {
            "metrics": {
                "snapshots": [
                    {
                        "period_start": "2026-10-26T18:00:00Z",
                        "collected_at": "2026-10-26T18:30:00Z",
                        "followers": 110,
                        "source": "bluesky_snapshot",
                    }
                ]
            },
            "daily": {
                "schema_version": 1,
                "snapshots": [
                    {
                        "period_start": "2026-10-25T18:00:00Z",
                        "collected_at": "2026-10-25T18:30:00Z",
                        "followers": 100,
                        "source": "bluesky_daily",
                    }
                ],
                "daily_activity": [
                    {"date": "2026-10-26", "joke_posts": 6, "follows": 0}
                ],
            },
        },
    )
    assert actual["snapshots"] == 2
    assert actual["summary"]["followers"] == 10
    assert actual["summary"]["jokes"] == 6


def test_authoritative_activity_replaces_matching_legacy_attempt_only():
    actual = _javascript(
        "DashboardHistory.merge([],input).activity_runs.map(run=>[run.workflow,run.attempt])",
        {
            "workflow_activity": {
                "runs": [
                    {"id": 42, "attempt": 1, "workflow": "legacy_activity"},
                    {"id": 42, "attempt": 1, "workflow": "bluesky_post_joke"},
                    {"id": 42, "attempt": 2, "workflow": "legacy_activity"},
                ]
            }
        },
    )
    assert actual == [["bluesky_post_joke", 1], ["legacy_activity", 2]]


@pytest.mark.parametrize(
    "expression",
    [
        "DashboardHistory.requestedMonths({schema_version:2,months:[]}, {})",
        "DashboardHistory.requestedMonths({schema_version:1,months:[{month:'../private'}]},{start:'2026-10-20',end:'2026-10-27',days:7})",
        "DashboardHistory.merge([{schema_version:1,month:'2026-10'}],{})",
        "DashboardHistory.merge([],{}, {schema_version:2,snapshots:[],daily_activity:[]})",
    ],
)
def test_malformed_history_is_rejected_explicitly(expression):
    actual = _javascript(
        "(() => {try {"
        + expression
        + ";return false;}catch(error){return error.message;}})()"
    )
    assert isinstance(actual, str)
    assert actual


def test_history_controller_retries_errors_and_keeps_view_periods_independent():
    actual = _javascript(
        "(async()=>{metrics=input;let fail=true;const urls=[];"
        "globalThis.fetch=async url=>{urls.push(url);return {ok:!fail,status:503,"
        "json:async()=>url.endsWith('index.json')?{schema_version:1,months:[]}:"
        "{schema_version:1,snapshots:[],daily_activity:[]}};};"
        "await updateHistoricalView('audience','7');"
        "const failure=document.getElementById('audience-history-status').textContent;"
        "const unchanged=historicalViews.audience.selection;"
        "fail=false;await updateHistoricalView('audience','7');"
        "await updateHistoricalView('operations','30');"
        "return {failure,unchanged,audience:historicalViews.audience.selection,"
        "operations:historicalViews.operations.selection,"
        "indexFetches:urls.filter(url=>url.endsWith('index.json')).length,"
        "cleared:document.getElementById('audience-history-status').hidden};})()",
        {
            "generated_at": "2026-10-27T13:00:00Z",
            "snapshots": [],
            "daily_activity": [],
        },
        controller=True,
    )
    assert "503" in actual["failure"]
    assert actual["unchanged"] == "30"
    assert actual["audience"] == "7"
    assert actual["operations"] == "30"
    assert actual["indexFetches"] == 2
    assert actual["cleared"]


def test_rapid_history_selection_cannot_publish_an_outdated_response():
    actual = _javascript(
        "(async()=>{metrics=input;globalThis.fetch=async url=>({ok:true,json:async()=>"
        "url.endsWith('index.json')?{schema_version:1,months:[]}:"
        "{schema_version:1,snapshots:[],daily_activity:[]}});"
        "await Promise.all([updateHistoricalView('audience','7'),"
        "updateHistoricalView('audience','90')]);"
        "return {selection:historicalViews.audience.selection,"
        "days:historicalViews.audience.period.days};})()",
        {
            "generated_at": "2026-10-27T13:00:00Z",
            "snapshots": [],
            "daily_activity": [],
        },
        controller=True,
    )
    assert actual == {"selection": "90", "days": 90}


def test_source_history_weights_observed_samples_and_does_not_invent_missing_days():
    actual = _javascript(
        "DashboardHistory.series(input,{start:'2026-10-25',end:'2026-10-27',days:2})",
        {
            "snapshots": [],
            "daily_activity": [],
            "activity_runs": [],
            "automation_runs": [],
            "operational_observations": [
                {
                    "collected_at": "2026-10-26T18:00:00Z",
                    "audience_growth": {
                        "cohorts": {
                            "periods": [
                                {
                                    "source": "discovery",
                                    "checkpoints": {
                                        "30": {"observed": 10, "still_following": 1}
                                    },
                                },
                                {
                                    "source": "discovery",
                                    "checkpoints": {
                                        "30": {"observed": 30, "still_following": 15}
                                    },
                                },
                            ]
                        }
                    },
                }
            ],
        },
    )
    assert actual[0]["sourceOutcomes"]["discovery"] is None
    assert actual[1]["sourceOutcomes"]["discovery"] == 40
    assert actual[1]["sourceOutcomes"]["followback"] is None


@pytest.mark.parametrize(
    ("current", "previous", "rate", "expected"),
    [
        (5, 0, False, "+5 vs previous period (0)"),
        (None, 5, False, "Comparison unavailable"),
        (5, None, False, "Comparison unavailable"),
        (99.5, 98, True, "+1.5 percentage points vs previous period"),
    ],
)
def test_comparison_handles_zero_baselines_and_rate_units(
    current, previous, rate, expected
):
    actual = _javascript(
        "historyComparison(input.current,input.previous,input.rate)",
        {"current": current, "previous": previous, "rate": rate},
        controller=True,
    )
    assert actual == expected
