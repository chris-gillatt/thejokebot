import copy
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from thejokebot.commands import collect_dashboard_metrics as collector
from thejokebot.commands import dashboard_engagement as engagement
from thejokebot.commands import dashboard_history, dashboard_metrics

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def _existing():
    return {
        "schema_version": 1,
        "coverage_started_at": (NOW - timedelta(days=500)).isoformat(),
        "posts": [],
    }


def _publication(age, key="joke", count=3):
    created = NOW - timedelta(hours=age)
    uri = f"at://did:bot/app.bsky.feed.post/{key}"
    return (
        {"post_uri": uri, "ts": created.timestamp(), "provider": "groandeck"},
        {
            "uri": uri,
            "record": {"createdAt": created.isoformat(), "text": f"Public joke {key}"},
            "likeCount": count,
        },
    )


def _receipt(days, count, key):
    entry, post = _publication(days * 24, key, count)
    created = datetime.fromisoformat(post["record"]["createdAt"])
    return {
        "uri": entry["post_uri"],
        "created_at": created.isoformat(),
        "provider": entry["provider"],
        "checkpoints": {
            str(hours): {
                "status": "observed",
                "observed_at": (created + timedelta(hours=hours + 2)).isoformat(),
                "engagement": engagement.engagement(post),
            }
            for hours in (24, 168)
            if created + timedelta(hours=hours + 2) <= NOW
        },
    }, post


@pytest.mark.parametrize(
    ("hours", "age", "status"),
    [
        (24, 23.999, None),
        (24, 24, "observed"),
        (24, 29.999, "observed"),
        (24, 30, "missed"),
        (168, 167.999, None),
        (168, 168, "observed"),
        (168, 173.999, "observed"),
        (168, 174, "missed"),
    ],
)
def test_observation_windows_are_half_open(hours, age, status):
    entry, post = _publication(age)
    result = engagement.collect(_existing(), [entry], [post], NOW)
    actual = result["posts"][0]["checkpoints"].get(str(hours), {}).get("status")
    assert actual == status


def test_first_observation_is_immutable_and_survives_restart(tmp_path):
    entry, post = _publication(25)
    result = engagement.collect(_existing(), [entry], [post], NOW)
    original = copy.deepcopy(result)
    path = tmp_path / "checkpoint.json"
    assert engagement.load(path) is None
    dashboard_history._write_json(path, result)
    post["likeCount"] = 999
    updated = engagement.collect(
        engagement.load(path), [entry], [post], NOW + timedelta(hours=4)
    )
    assert updated == original
    assert result == original
    assert updated["posts"][0]["checkpoints"]["24"]["engagement"]["likes"] == 3


def test_hidden_post_can_be_observed_only_before_the_window_closes():
    entry, post = _publication(25)
    pending = engagement.collect(_existing(), [entry], [], NOW)
    assert "24" not in pending["posts"][0]["checkpoints"]
    recovered = engagement.collect(pending, [entry], [post], NOW + timedelta(hours=1))
    assert recovered["posts"][0]["checkpoints"]["24"]["status"] == "observed"
    missed = engagement.collect(pending, [entry], [], NOW + timedelta(hours=5))
    assert missed["posts"][0]["checkpoints"]["24"]["status"] == "missed"
    late = engagement.collect(missed, [entry], [post], NOW + timedelta(hours=6))
    assert late == missed


@pytest.mark.parametrize(
    ("collection_age", "observed_age", "status"),
    [(23.99, 24.01, "observed"), (29.99, 30.01, "missed"), (24.01, 23.99, None)],
)
def test_feed_response_time_controls_age_not_workflow_start_time(
    collection_age, observed_age, status
):
    entry, post = _publication(collection_age)
    observed = NOW + timedelta(hours=observed_age - collection_age)
    post["_dashboard_observed_at"] = observed.isoformat()
    result = engagement.collect(_existing(), [entry], [post], NOW)
    observation = result["posts"][0]["checkpoints"].get("24", {})
    assert observation.get("status") == status
    if status == "observed":
        assert observation["observed_at"] == observed.isoformat()


def test_feed_producer_stamps_the_actual_response_observation_without_mutation():
    _, post = _publication(24)
    post["author"] = {"did": "did:bot"}
    original = copy.deepcopy(post)
    posts = {}
    with patch.object(dashboard_metrics, "datetime") as clock:
        clock.now.return_value = NOW
        dashboard_metrics._collect_original_posts(posts, [{"post": post}], "did:bot")
    assert posts[post["uri"]]["_dashboard_observed_at"] == NOW.isoformat()
    assert post == original


def test_bootstrap_does_not_invent_checkpoint_history():
    older, older_post = _publication(200, "older")
    upcoming, upcoming_post = _publication(100, "upcoming")
    active, active_post = _publication(25, "active")
    result = engagement.collect(
        None, [older, upcoming, active], [older_post, upcoming_post, active_post], NOW
    )
    records = {item["uri"]: item for item in result["posts"]}
    assert older["post_uri"] not in records
    assert records[upcoming["post_uri"]]["checkpoints"] == {
        "24": {"status": "before_coverage"}
    }
    assert records[active["post_uri"]]["checkpoints"]["24"]["status"] == "observed"
    summary = engagement.summary(result, [active_post], NOW)
    assert summary["checkpoints"]["24"]["coverage"]["before_coverage"] == 1
    assert summary["checkpoints"]["168"]["coverage"]["observed"] == 0


def test_receipts_are_retained_for_400_days_without_retaining_private_fields():
    old, _ = _receipt(401, 3, "expired")
    boundary, _ = _receipt(400, 4, "boundary")
    existing = _existing()
    existing["posts"] = [old, boundary]
    entry, post = _publication(24)
    entry["audience"] = "did:private:audience"
    entry["private_text"] = "private content"
    post["author"] = {"private_note": "private content"}
    result = engagement.collect(existing, [{}, entry], [post], NOW)
    assert {item["uri"] for item in result["posts"]} == {
        boundary["uri"],
        entry["post_uri"],
    }
    serialised = json.dumps(result)
    assert "private" not in serialised
    assert "Public joke" not in serialised
    assert set(result["posts"][-1]) == {
        "uri",
        "created_at",
        "provider",
        "checkpoints",
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda state: state.update(schema_version=9),
        lambda state: state.update(posts={}),
        lambda state: state.update(coverage_started_at="2026-10-28T00:00:00Z"),
        lambda state: state.update(coverage_started_at="2026-10-27T00:00:00"),
        lambda state: state["posts"][0].update(created_at="2026-10-28T00:00:00Z"),
        lambda state: state["posts"][0].update(checkpoints=[]),
        lambda state: state["posts"][0]["checkpoints"].update(
            {"48": {"status": "missed"}}
        ),
        lambda state: state["posts"][0]["checkpoints"]["24"].update(status="invented"),
        lambda state: state["posts"][0]["checkpoints"]["24"].update(
            observed_at="2026-10-27T00:00:00Z"
        ),
        lambda state: state["posts"][0]["checkpoints"]["24"]["engagement"].update(
            likes=-1
        ),
        lambda state: state["posts"][0]["checkpoints"]["24"]["engagement"].update(
            likes=True
        ),
        lambda state: state["posts"][0]["checkpoints"]["24"]["engagement"].pop("likes"),
    ],
)
def test_invalid_saved_state_fails_explicitly(change):
    record, _ = _receipt(10, 2, "sample")
    existing = _existing()
    existing["posts"] = [record]
    change(existing)
    with pytest.raises(ValueError):
        engagement.collect(existing, [], [], NOW)


def test_future_publication_is_rejected_and_old_publication_is_not_reintroduced():
    entry, post = _publication(-1)
    with pytest.raises(ValueError, match="future publication"):
        engagement.collect(None, [entry], [post], NOW)
    entry, post = _publication(401 * 24)
    assert engagement.collect(_existing(), [entry], [post], NOW)["posts"] == []


def _mature_data():
    receipts = _existing()
    visible = []
    for index, count in enumerate([0, 1, 1, 10]):
        record, post = _receipt(10, count, f"recent-{index}")
        receipts["posts"].append(record)
        visible.append(post)
    previous, post = _receipt(40, 2, "previous")
    receipts["posts"].append(previous)
    visible.append(post)
    return receipts, visible


def test_summary_uses_mature_publishing_cohorts_and_correct_statistics():
    receipts, visible = _mature_data()
    result = engagement.summary(receipts, visible, NOW)
    current = result["checkpoints"]["24"]["periods"]["recent"]
    previous = result["checkpoints"]["24"]["periods"]["previous"]
    assert (current["start"], current["end"]) == ("2026-09-26", "2026-10-26")
    assert (previous["start"], previous["end"]) == ("2026-08-27", "2026-09-26")
    assert current["observed"] == 4
    assert current["mean"] == 3
    assert current["median"] == 1
    assert current["zero_share"] == 25
    assert current["engagement"]["likes"] == 12
    assert previous["mean"] == 2
    assert result["checkpoints"]["168"]["periods"]["recent"]["end"] == "2026-10-20"
    assert result["checkpoints"]["24"]["providers"][0]["observed"] == 4
    assert result["checkpoints"]["24"]["publishing_hours"][0]["utc_hour"] == "12:00"
    top = result["checkpoints"]["24"]["top_posts"][0]
    assert top["engagement"]["likes"] == 10
    assert top["age_hours"] == 26
    assert len(result["checkpoints"]["24"]["months"]) == 2


def test_missing_samples_are_not_zeroes_and_deleted_posts_keep_only_aggregates():
    receipts, visible = _mature_data()
    missing, _ = _receipt(12, 0, "missing")
    missing["checkpoints"]["24"] = {"status": "missed"}
    receipts["posts"].append(missing)
    summary = engagement.summary(receipts, [], NOW)["checkpoints"]["24"]
    assert summary["periods"]["recent"]["observed"] == 4
    assert summary["periods"]["recent"]["missed"] == 1
    assert summary["periods"]["recent"]["mean"] == 3
    assert summary["top_posts"] == []
    empty = engagement.summary(_existing(), visible, NOW)["checkpoints"]["24"]
    assert empty["periods"]["recent"]["mean"] is None
    assert empty["periods"]["recent"]["median"] is None
    assert empty["periods"]["recent"]["zero_share"] is None


def test_collector_writes_receipts_but_does_not_export_them_in_pages(tmp_path):
    entry, post = _publication(25)
    profile = {
        "did": "did:bot",
        "handle": "bot.bsky.social",
        "followersCount": 1,
        "followsCount": 1,
        "postsCount": 1,
    }
    state_path = tmp_path / "state" / "dashboard_engagement.json"
    metrics_path = tmp_path / "dashboard" / "metrics.json"
    history_path = tmp_path / "history"
    write_history = dashboard_history._write_history
    with (
        patch.dict("os.environ", {"BLUESKY_USERNAME": "bot.bsky.social"}),
        patch.object(collector, "datetime") as clock,
        patch.object(engagement, "STATE_FILE", state_path),
        patch.object(collector, "METRICS_FILE", metrics_path),
        patch.object(dashboard_history, "_load_history_partitions", return_value={}),
        patch.object(
            dashboard_history,
            "_collector_existing",
            return_value={"schema_version": 11, "snapshots": []},
        ),
        patch.object(
            dashboard_history,
            "_write_history",
            side_effect=lambda partitions, now, activity: write_history(
                partitions, now, activity, history_path
            ),
        ),
        patch.object(collector, "fetch_workflow_runs", return_value=[]),
        patch.object(collector, "collect_workflow_activity", return_value={}),
        patch.object(collector, "fetch_profile", return_value=profile),
        patch.object(collector, "fetch_post", return_value=post),
        patch.object(collector, "fetch_original_posts", return_value=[post]) as fetch,
        patch.object(
            collector.bot_state, "load_state", return_value={"posted_jokes": [entry]}
        ),
    ):
        clock.now.return_value = NOW
        collector.main()
        receipts = engagement.load(state_path)
        assert receipts is not None
        public = json.loads(metrics_path.read_text())
        assert receipts["posts"][0]["checkpoints"]["24"]["status"] == "observed"
        assert "engagement_checkpoints" not in public
        assert (
            public["joke_performance"]["checkpoints"]["24"]["coverage"]["observed"] == 1
        )
        assert all(
            "engagement_checkpoints" not in path.read_text()
            for path in history_path.rglob("*.json")
        )
        first_state = state_path.read_text()
        first_metrics = metrics_path.read_text()
        fetch.side_effect = RuntimeError("Author-feed pagination incomplete")
        with pytest.raises(RuntimeError, match="incomplete"):
            collector.main()
        assert state_path.read_text() == first_state
        assert metrics_path.read_text() == first_metrics
    assert dashboard_history._load_history_partitions(history_path)


def _render_browser(performance, *, click_age=None):
    source = (
        (ROOT / "dashboard" / "app.js").read_text().removesuffix("void initialise();\n")
    )
    script = (
        "const fs=require('node:fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));"
        "class Node {constructor(){this.textContent='';this.children=[];this.hidden=false;"
        "this.dataset={};this.events={};this.attributes={};this.classList={toggle(){}};}"
        "append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}"
        "addEventListener(name,fn){this.events[name]=fn;}setAttribute(k,v){this.attributes[k]=v;}}"
        "const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Node());return elements.get(id);};"
        "const buttons=['24','168'].map(age=>{const b=new Node();b.dataset.performanceAge=age;return b;});"
        "const document={getElementById:get,querySelector:get,createElement:()=>new Node(),"
        "querySelectorAll:q=>q==='[data-performance-age]'?buttons:[]};"
        "class Chart {constructor(element,config){this.data=config.data;}destroy(){}}"
        + source
        + ";metrics=input.metrics;renderJokePerformance();"
        "if(input.clickAge){bindRangeControls();buttons.find(b=>b.dataset.performanceAge===input.clickAge).events.click();}"
        "const text=n=>[n.textContent,...n.children.map(text)].join('|');"
        "const result={};for(const id of ['performance-coverage','performance-period','performance-mean',"
        "'performance-median','performance-zero','performance-samples','performance-empty','performance-breakdown'])"
        "result[id]=get(id).textContent;"
        "result.hidden=get('performance-content').hidden;"
        "result.groups=text(get('#performance-comparison-table tbody'));"
        "result.posts=text(get('performance-posts'));result.chart=charts.jokePerformance?.data;"
        "result.selected=selectedPerformanceAge;result.pressed=buttons.map(b=>b.attributes['aria-pressed']);"
        "console.log(JSON.stringify(result));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(
            {
                "metrics": {
                    "generated_at": NOW.isoformat(),
                    "account": {"handle": "bot.bsky.social"},
                    "joke_performance": performance,
                },
                "clickAge": click_age,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_producer_to_browser_renders_statistics_samples_and_real_observation_age():
    receipts, visible = _mature_data()
    performance = engagement.summary(receipts, visible, NOW)
    result = _render_browser(performance)
    assert result["performance-mean"] == "3"
    assert result["performance-median"] == "1"
    assert result["performance-zero"] == "25%"
    assert result["performance-samples"] == "4 / 4"
    assert "26 hours old" in result["posts"]
    assert "Needs 30 observations" in result["groups"]
    assert "likes: 12" in result["performance-breakdown"]
    assert result["chart"]["datasets"][0]["data"] == [2, 3]
    switched = _render_browser(performance, click_age="168")
    assert switched["selected"] == "168"
    assert switched["pressed"] == ["false", "true"]
    assert "168–174-hour" in switched["performance-period"]


def test_browser_empty_legacy_and_immature_states_do_not_invent_zeroes():
    legacy = _render_browser(None)
    assert legacy["hidden"]
    assert "cannot be reconstructed" in legacy["performance-coverage"]
    entry, post = _publication(12)
    performance = engagement.summary(
        engagement.collect(None, [entry], [post], NOW), [post], NOW
    )
    result = _render_browser(performance)
    assert not result["hidden"]
    assert result["performance-mean"] == "--"
    assert result["performance-median"] == "--"
    assert result["performance-zero"] == "--"
    assert "Missing observations are not zero" in result["performance-empty"]
    assert "unavailable" in result["performance-breakdown"]


def test_group_comparisons_require_30_observations_and_top_posts_are_bounded():
    receipts = _existing()
    visible = []
    for index in range(30):
        record, post = _receipt(10, 1, f"sample-{index}")
        receipts["posts"].append(record)
        visible.append(post)
    performance = engagement.summary(receipts, visible, NOW)
    result = _render_browser(performance)
    assert "Needs 30" not in result["groups"]
    assert "30 observed / 0 missed|1|1|0%" in result["groups"]
    assert len(performance["checkpoints"]["24"]["top_posts"]) == 6


def test_display_does_not_round_a_valid_observation_up_to_the_excluded_boundary():
    entry, post = _publication(29.9999)
    receipts = engagement.collect(_existing(), [entry], [post], NOW)
    performance = engagement.summary(receipts, [post], NOW + timedelta(days=2))
    result = _render_browser(performance)
    assert "29.99 hours old" in result["posts"]
    assert "30 hours old" not in result["posts"]


def test_checkpoint_engagement_retains_all_interaction_types():
    entry, post = _publication(24)
    post.update(
        replyCount=2, repostCount=3, quoteCount=4, bookmarkCount=5, likeCount=-1
    )
    result = engagement.collect(None, [entry], [post], NOW)
    assert result["posts"][0]["checkpoints"]["24"]["engagement"] == {
        "likes": 0,
        "replies": 2,
        "reposts": 3,
        "quotes": 4,
        "bookmarks": 5,
    }
    assert dashboard_metrics.ENGAGEMENT_FIELDS == engagement.ENGAGEMENT_FIELDS
