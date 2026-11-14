import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests
from atproto import models
from atproto_client.exceptions import BadRequestError
from atproto_client.request import Response

from thejokebot import repost_reviews as reviews
from thejokebot import state
from thejokebot.commands import dashboard_reposts

BOT = "did:plc:bot"
AUTHOR = "did:plc:author"
NOW = datetime(2026, 11, 14, 9, tzinfo=timezone.utc)
COLLECTION = "app.bsky.feed.repost"


def post(author=AUTHOR, key="joke", **changes):
    return {
        "uri": f"at://{author}/app.bsky.feed.post/{key}",
        "cid": f"cid-{key}",
        "author": {"did": author, "handle": f"{author.rsplit(':', 1)[-1]}.test"},
        "record": {
            "$type": "app.bsky.feed.post",
            "text": "Test fixture",
            "createdAt": NOW.isoformat(),
        },
        "viewer": {},
        **changes,
    }


def record(subject=None, key="share"):
    subject = subject or post()
    return {
        "uri": f"at://{BOT}/{COLLECTION}/{key}",
        "cid": f"cid-{key}",
        "value": {
            "$type": COLLECTION,
            "createdAt": (NOW - timedelta(days=1)).isoformat(),
            "subject": {"uri": subject["uri"], "cid": subject["cid"]},
        },
    }


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    state.save_state(state._default_state(), domains="social")
    monkeypatch.setenv("BLUESKY_REPOSTS_ENABLED", "true")
    monkeypatch.setenv("BLUESKY_DRY_RUN", "false")
    monkeypatch.setattr(reviews, "retry_network_call", lambda fn, **_: fn())
    client = Mock()
    client.me.did = BOT
    client.com.atproto.repo.list_records.return_value = {"records": [record()]}
    client.get_posts.side_effect = lambda uris: {
        "posts": [post(key=uri.rsplit("/", 1)[-1]) for uri in uris]
    }
    client.get_author_feed.return_value = {"feed": [{"post": post(key="new")}]}
    client.repost.return_value = {
        "uri": f"at://{BOT}/{COLLECTION}/confirmed",
        "cid": "cid-confirmed",
    }
    client.com.atproto.repo.get_record.return_value = record(
        post(key="new"), key="confirmed"
    )
    return client


def proposal(client, now=NOW):
    report = reviews.discover(client, state.load_state(), now)
    return report["candidates"][0]


def save_review(candidate):
    candidate = {**candidate, "status": "approved"}
    state.update_state(
        lambda latest: latest["repost_reviews"]["candidates"].update(
            {candidate["key"]: copy.deepcopy(candidate)}
        ),
        domains="social",
    )


def test_discovery_is_read_only_and_excludes_already_reposted_posts(account):
    before = state.load_state()
    account.get_author_feed.return_value = {
        "feed": [
            {"post": post()},
            {"post": post(key="viewer", viewer={"repost": "at://already"})},
            {"post": post(key="new")},
        ]
    }
    report = reviews.discover(account, before, NOW)
    assert [entry["post"]["uri"] for entry in report["candidates"]] == [
        post(key="new")["uri"]
    ]
    assert report["inventory"]["entries"][0]["post_uri"] == post()["uri"]
    assert (
        report["candidates"][0]["expires_at"] == (NOW + timedelta(days=7)).isoformat()
    )
    assert state.load_state() == before
    account.repost.assert_not_called()


def test_daily_cap_rotation_and_persisted_rejections(account):
    authors = [f"did:plc:author{i}" for i in range(8)]
    account.com.atproto.repo.list_records.return_value = {
        "records": [
            record(post(author=author), key=str(i)) for i, author in enumerate(authors)
        ]
    }
    account.get_posts.side_effect = lambda uris: {
        "posts": [
            post(author=uri.split("/")[2], key=uri.rsplit("/", 1)[-1]) for uri in uris
        ]
    }
    account.get_author_feed.side_effect = lambda actor, **_: {
        "feed": [{"post": post(author=actor, key="new")}]
    }
    report = reviews.discover(account, state.load_state(), NOW)
    assert len(report["candidates"]) == 5
    reviews.checkpoint_discovery(state.load_state(), report)
    again = reviews.discover(account, state.load_state(), NOW)
    assert again["candidates"] == []
    tomorrow = reviews.discover(account, state.load_state(), NOW + timedelta(days=1))
    assert tomorrow["candidates"]
    assert not {item["post"]["uri"] for item in tomorrow["candidates"]} & {
        item["post"]["uri"] for item in report["candidates"]
    }


def test_image_only_reply_retains_parent_context(account):
    parent = post(key="parent")
    image = post(
        key="new",
        embed={
            "$type": "app.bsky.embed.images#view",
            "images": [{"fullsize": "https://cdn.bsky.app/img/test.jpg", "alt": ""}],
        },
    )
    image["record"]["text"] = ""
    image["record"]["reply"] = {
        "root": {"uri": parent["uri"], "cid": parent["cid"]},
        "parent": {"uri": parent["uri"], "cid": parent["cid"]},
    }
    account.get_author_feed.return_value = {"feed": [{"post": image}]}
    candidate = proposal(account)
    assert candidate["post"]["kind"] == "image"
    assert candidate["post"]["is_reply"] is True
    assert candidate["context"][0]["uri"] == parent["uri"]
    assert candidate["post"]["images"][0]["alt"] == ""


@pytest.mark.parametrize("failure", ["network", "missing-viewer", "changed-parent"])
def test_unverifiable_candidate_reads_fail_closed(account, failure):
    if failure == "network":
        account.get_author_feed.side_effect = requests.Timeout("unavailable")
    else:
        item = post(key="new")
        if failure == "missing-viewer":
            del item["viewer"]
        else:
            item["record"]["reply"] = {
                "parent": {"uri": post()["uri"], "cid": "changed"},
                "root": {"uri": post()["uri"], "cid": "changed"},
            }
        account.get_author_feed.return_value = {"feed": [{"post": item}]}
    if failure == "changed-parent":
        assert reviews.discover(account, state.load_state(), NOW)["candidates"] == []
    else:
        with pytest.raises((ValueError, requests.Timeout)):
            reviews.discover(account, state.load_state(), NOW)
    account.repost.assert_not_called()


def test_publish_rechecks_current_repost_status_without_creating_again(account):
    candidate = proposal(account)
    save_review(candidate)
    account.get_posts.side_effect = None
    account.get_posts.return_value = {
        "posts": [post(key="new", viewer={"repost": f"at://{BOT}/{COLLECTION}/manual"})]
    }
    result = reviews.publish(account, state.load_state(), candidate["key"], NOW)
    assert result["status"] == "already_reposted"
    account.repost.assert_not_called()


@pytest.mark.parametrize("failure", ["cid", "expiry", "disabled", "dry-run"])
def test_publication_requires_unchanged_unexpired_enabled_content(
    account, monkeypatch, failure
):
    candidate = proposal(account)
    save_review(candidate)
    now = NOW
    if failure == "cid":
        account.get_posts.side_effect = None
        account.get_posts.return_value = {"posts": [post(key="new", cid="different")]}
    elif failure == "expiry":
        now += timedelta(days=7)
    elif failure == "disabled":
        monkeypatch.setenv("BLUESKY_REPOSTS_ENABLED", "false")
    else:
        monkeypatch.setenv("BLUESKY_DRY_RUN", "true")
    with pytest.raises(ValueError):
        reviews.publish(account, state.load_state(), candidate["key"], now)
    account.repost.assert_not_called()


def test_confirmed_publication_protects_creator_and_reaches_stats(account):
    candidate = proposal(account)
    save_review(candidate)
    result = reviews.publish(account, state.load_state(), candidate["key"], NOW)
    assert result["status"] == "published"
    fresh = state.load_state()
    assert AUTHOR in fresh["follow_tracking"]["content_creator_dids"]
    metrics = dashboard_reposts.collect(fresh, NOW)
    assert metrics["confirmed_publications"] == 1
    assert metrics["confirmed_removals"] == 0
    reviews.publish(account, fresh, candidate["key"], NOW)
    assert account.repost.call_count == 1


def test_sdk_reply_models_preserve_thread_context(account):
    child = post(key="new", indexedAt=NOW.isoformat())
    child["record"]["reply"] = {
        "root": {"uri": post()["uri"], "cid": post()["cid"]},
        "parent": {"uri": post()["uri"], "cid": post()["cid"]},
    }
    typed = models.AppBskyFeedDefs.PostView.model_validate(child)
    account.get_author_feed.return_value = {
        "feed": [models.AppBskyFeedDefs.FeedViewPost(post=typed)]
    }
    assert proposal(account)["context"][0]["uri"] == post()["uri"]


def test_sdk_strong_reference_receipt_confirms_publication(account):
    candidate = proposal(account)
    save_review(candidate)
    receipt = record(post(key="new"), key="confirmed")
    receipt["value"] = models.AppBskyFeedRepost.Record.model_validate(receipt["value"])
    account.com.atproto.repo.get_record.return_value = (
        models.ComAtprotoRepoGetRecord.Response.model_validate(receipt)
    )
    result = reviews.publish(account, state.load_state(), candidate["key"], NOW)
    assert result["status"] == "published"


def test_uncertain_create_is_not_blindly_retried(account):
    candidate = proposal(account)
    save_review(candidate)
    account.repost.side_effect = requests.Timeout("response lost")
    with pytest.raises(requests.Timeout):
        reviews.publish(account, state.load_state(), candidate["key"], NOW)
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["status"]
        == "uncertain"
    )
    with pytest.raises(ValueError, match="uncertain"):
        reviews.publish(account, state.load_state(), candidate["key"], NOW)
    assert account.repost.call_count == 1


def test_stats_rank_authors_with_window_specific_shares_and_no_private_identifiers(
    account,
):
    inventory = reviews.read_inventory(account, NOW)
    first = inventory["entries"][0]
    inventory["entries"] += [
        {**first, "post_uri": post(key="second")["uri"]},
        {
            **first,
            "post_uri": post(author="did:plc:other")["uri"],
            "author_did": "did:plc:other",
            "handle": "other.test",
            "created_at": (NOW - timedelta(days=10)).isoformat(),
            "kind": "image",
            "is_reply": True,
        },
    ]
    working = {"repost_reviews": {"inventory": inventory, "candidates": {}}}
    metrics = dashboard_reposts.collect(working, NOW)
    assert metrics["windows"]["all"]["total"] == 3
    assert metrics["windows"]["all"]["authors"][0]["count"] == 2
    assert metrics["windows"]["all"]["authors"][0]["share"] == pytest.approx(2 / 3)
    assert metrics["windows"]["7"]["total"] == 2
    assert metrics["windows"]["7"]["authors"][0]["share"] == 1
    assert metrics["windows"]["30"]["image"] == 1
    assert metrics["windows"]["30"]["replies"] == 1
    assert "did:plc:" not in str(metrics)
    assert dashboard_reposts.collect({}, NOW)["windows"] == {}


@pytest.mark.parametrize(
    "failure",
    [
        "posts-list",
        "unexpected-post",
        "duplicate-post",
        "foreign-author",
        "feed-list",
        "image-origin",
        "future-record",
        "non-post",
    ],
)
def test_invalid_discovery_responses_never_checkpoint_or_repost(account, failure):
    before = state.load_state()
    if failure in ("posts-list", "unexpected-post", "duplicate-post"):
        account.get_posts.side_effect = None
        account.get_posts.return_value = {
            "posts": None
            if failure == "posts-list"
            else (
                [post(key="unexpected")]
                if failure == "unexpected-post"
                else [post(), post()]
            )
        }
    elif failure == "foreign-author":
        account.get_author_feed.return_value = {
            "feed": [{"post": post(author="did:plc:other")}]
        }
    elif failure == "feed-list":
        account.get_author_feed.return_value = {"feed": None}
    elif failure == "image-origin":
        account.get_author_feed.return_value = {
            "feed": [
                {
                    "post": post(
                        key="new",
                        embed={
                            "$type": "app.bsky.embed.images#view",
                            "images": [
                                {"fullsize": "https://evil.test/image.jpg", "alt": ""}
                            ],
                        },
                    )
                }
            ]
        }
    else:
        entry = record()
        if failure == "future-record":
            entry["value"]["createdAt"] = (NOW + timedelta(seconds=1)).isoformat()
        else:
            entry["value"]["subject"]["uri"] = f"at://{AUTHOR}/app.bsky.feed.repost/key"
        account.com.atproto.repo.list_records.return_value = {"records": [entry]}
    with pytest.raises(ValueError):
        reviews.discover(account, before, NOW)
    assert state.load_state() == before
    account.repost.assert_not_called()


@pytest.mark.parametrize(
    "reason", ["label", "block-list", "mute", "unsupported", "reposted-feed-item"]
)
def test_excluded_or_unsupported_source_posts_are_not_queued(account, reason):
    item = post(key="new")
    feed_entry = {"post": item}
    if reason == "label":
        item["labels"] = [{"val": "porn", "neg": False}]
    elif reason == "block-list":
        item["author"]["viewer"] = {"blockingByList": {"uri": "at://blocked-list"}}
    elif reason == "mute":
        item["author"]["viewer"] = {"muted": True}
    elif reason == "unsupported":
        item["embed"] = {"$type": "app.bsky.embed.video#view"}
    else:
        feed_entry["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost"}
    account.get_author_feed.return_value = {"feed": [feed_entry]}
    assert reviews.discover(account, state.load_state(), NOW)["candidates"] == []


def test_deleted_inventory_subject_is_unknown_not_invented_text_content(account):
    account.get_posts.side_effect = None
    account.get_posts.return_value = {"posts": []}
    inventory = reviews.read_inventory(account, NOW)
    metrics = dashboard_reposts.collect(
        {"repost_reviews": {"inventory": inventory}}, NOW
    )
    assert metrics["windows"]["all"]["total"] == 1
    assert metrics["windows"]["all"]["text"] == 0
    assert metrics["windows"]["all"]["unknown_format"] == 1
    assert metrics["windows"]["all"]["authors"][0]["handle"] is None


@pytest.mark.parametrize(
    "failure", ["wrong-cid", "foreign-receipt", "malformed-response"]
)
def test_unverified_writes_are_uncertain_and_never_report_success(account, failure):
    candidate = proposal(account)
    save_review(candidate)
    if failure == "wrong-cid":
        account.com.atproto.repo.get_record.return_value["cid"] = "different"
    elif failure == "foreign-receipt":
        account.repost.return_value["uri"] = f"at://{AUTHOR}/{COLLECTION}/key"
    else:
        account.repost.return_value = {}
    with pytest.raises(ValueError):
        reviews.publish(account, state.load_state(), candidate["key"], NOW)
    saved = state.load_state()
    assert (
        saved["repost_reviews"]["candidates"][candidate["key"]]["status"] == "uncertain"
    )
    assert dashboard_reposts.collect(saved, NOW)["confirmed_publications"] == 0


def test_confirmed_receipt_recovers_without_a_second_create(account):
    candidate = proposal(account)
    save_review(candidate)
    account.com.atproto.repo.get_record.side_effect = requests.Timeout(
        "read unavailable"
    )
    with pytest.raises(requests.Timeout):
        reviews.publish(account, state.load_state(), candidate["key"], NOW)
    account.com.atproto.repo.get_record.side_effect = None
    assert (
        reviews.publish(
            account, state.load_state(), candidate["key"], NOW + timedelta(days=8)
        )["status"]
        == "published"
    )
    assert account.repost.call_count == 1


def test_stale_approval_cannot_overwrite_a_completed_review(account):
    candidate = proposal(account)
    save_review(candidate)
    stale = state.load_state()
    reviews.update_review(
        state.load_state(),
        candidate["key"],
        status="published",
        published_at=NOW.isoformat(),
    )
    with pytest.raises(reviews.state_transactions.CheckpointError, match="stale"):
        reviews.publish(account, stale, candidate["key"], NOW)
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["status"]
        == "published"
    )
    account.repost.assert_not_called()


def test_expiry_during_final_checks_prevents_publication(account, monkeypatch):
    candidate = proposal(account)
    save_review(candidate)
    checks = iter((NOW, NOW + timedelta(days=7)))
    monkeypatch.setattr(
        reviews,
        "utc_now",
        lambda value=None: (
            value.astimezone(timezone.utc) if value is not None else next(checks)
        ),
    )
    with pytest.raises(ValueError, match="expired"):
        reviews.publish(account, state.load_state(), candidate["key"])
    account.repost.assert_not_called()


def test_changed_thread_context_prevents_publication(account):
    candidate = proposal(account)
    candidate["context"] = [
        {**candidate["post"], "text": "Previously reviewed context"}
    ]
    save_review(candidate)
    with pytest.raises(ValueError, match="context changed"):
        reviews.publish(account, state.load_state(), candidate["key"], NOW)
    account.repost.assert_not_called()


def test_new_moderation_after_review_prevents_publication(account):
    candidate = proposal(account)
    save_review(candidate)
    account.get_posts.side_effect = None
    account.get_posts.return_value = {
        "posts": [post(key="new", labels=[{"val": "sexual"}])]
    }
    with pytest.raises(ValueError, match="no longer eligible"):
        reviews.publish(account, state.load_state(), candidate["key"], NOW)
    account.repost.assert_not_called()


def test_stats_periods_end_at_scan_without_inventing_later_zero_days(account):
    inventory = reviews.read_inventory(account, NOW)
    inventory["collected_at"] = (NOW - timedelta(days=2)).isoformat()
    inventory["entries"][0]["created_at"] = (NOW - timedelta(days=8)).isoformat()
    metrics = dashboard_reposts.collect(
        {"repost_reviews": {"inventory": inventory}}, NOW
    )
    assert metrics["windows"]["7"]["total"] == 1
    assert (
        metrics["windows"]["7"]["daily"][-1]["date"]
        == (NOW - timedelta(days=2)).date().isoformat()
    )


@pytest.mark.parametrize(
    "failure",
    ["absent", "read-error", "wrong-record", "delete-false", "expired", "unapproved"],
)
def test_removal_never_confuses_unverified_outcomes_with_success(account, failure):
    candidate = proposal(account)
    candidate.update(
        {
            "action": "remove",
            "post": {**candidate["post"], "uri": post()["uri"], "cid": post()["cid"]},
            "repost_uri": record()["uri"],
            "repost_cid": record()["cid"],
        }
    )
    save_review(candidate)
    account.com.atproto.repo.get_record.return_value = record()
    account.delete_repost.return_value = False
    if failure in ("absent", "read-error"):
        account.com.atproto.repo.get_record.side_effect = BadRequestError(
            Response(
                False,
                400,
                {
                    "error": "RecordNotFound"
                    if failure == "absent"
                    else "InvalidRequest"
                },
                {},
            )
        )
    elif failure == "wrong-record":
        account.com.atproto.repo.get_record.return_value["cid"] = "changed"
    elif failure == "unapproved":
        reviews.update_review(state.load_state(), candidate["key"], status="proposed")
    when = NOW + timedelta(days=7) if failure == "expired" else NOW
    if failure == "absent":
        result = reviews.remove(account, state.load_state(), candidate["key"], when)
        assert result["status"] == "already_removed"
    else:
        with pytest.raises((ValueError, BadRequestError)):
            reviews.remove(account, state.load_state(), candidate["key"], when)
    assert dashboard_reposts.collect(state.load_state(), NOW)["confirmed_removals"] == 0
    if failure != "delete-false":
        account.delete_repost.assert_not_called()
    else:
        assert (
            state.load_state()["repost_reviews"]["candidates"][candidate["key"]][
                "status"
            ]
            == "uncertain"
        )


@pytest.mark.parametrize("context", ["missing", "changed", "moderated"])
def test_unavailable_reply_context_skips_candidate_without_blocking_other_originals(
    account, context
):
    parent = post(key="parent")
    ref = {"uri": parent["uri"], "cid": parent["cid"]}
    child = post(
        key="reply", record={**post()["record"], "reply": {"root": ref, "parent": ref}}
    )
    account.get_author_feed.return_value = {
        "feed": [{"post": child}, {"post": post(key="safe")}]
    }
    if context == "changed":
        parent["cid"] = "changed"
    elif context == "moderated":
        parent["labels"] = [{"val": "sexual"}]
    account.get_posts.side_effect = lambda uris: {
        "posts": ([] if context == "missing" else [parent])
        if uris == [parent["uri"]]
        else [post(key=uri.rsplit("/", 1)[-1]) for uri in uris]
    }
    report = reviews.discover(account, state.load_state(), NOW)
    assert [candidate["post"]["uri"] for candidate in report["candidates"]] == [
        post(key="safe")["uri"]
    ]
    account.repost.assert_not_called()


def test_uncertain_removal_reconciles_absence_without_another_delete(account):
    candidate = proposal(account)
    candidate.update(
        {
            "action": "remove",
            "post": {**candidate["post"], "uri": post()["uri"], "cid": post()["cid"]},
            "repost_uri": record()["uri"],
            "repost_cid": record()["cid"],
        }
    )
    save_review(candidate)
    account.com.atproto.repo.get_record.return_value = record()
    account.delete_repost.side_effect = requests.Timeout("delete response lost")
    with pytest.raises(requests.Timeout):
        reviews.remove(account, state.load_state(), candidate["key"], NOW)
    assert dashboard_reposts.collect(state.load_state(), NOW)["uncertain_outcomes"] == 1
    account.com.atproto.repo.get_record.side_effect = BadRequestError(
        Response(False, 400, {"error": "RecordNotFound"}, {})
    )
    result = reviews.remove(
        account, state.load_state(), candidate["key"], NOW + timedelta(days=8)
    )
    assert result["status"] == "already_removed"
    assert account.delete_repost.call_count == 1
    metrics = dashboard_reposts.collect(state.load_state(), NOW)
    assert metrics["uncertain_outcomes"] == 0
    assert metrics["confirmed_removals"] == 0
