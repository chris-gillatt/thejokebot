"""Saved-feed discovery selection, limits and failure safety."""

from types import SimpleNamespace
from unittest import mock

from atproto import models
import pytest
import requests

from thejokebot import discovery_feeds
from thejokebot import state as bot_state
from thejokebot.commands import follow_fellows
from thejokebot.followers import IncompletePaginationError

FEED_URI = "at://did:plc:creator/app.bsky.feed.generator/jokes"


def _saved(*items):
    return models.AppBskyActorDefs.SavedFeedsPrefV2(
        items=[
            models.AppBskyActorDefs.SavedFeed(
                id=str(index), pinned=False, type=kind, value=value
            )
            for index, (kind, value) in enumerate(items)
        ]
    )


def _post(did, **viewer):
    return SimpleNamespace(
        post=SimpleNamespace(author=SimpleNamespace(did=did, viewer=viewer))
    )


@pytest.fixture(autouse=True)
def no_retry_delays(monkeypatch):
    def call(operation, description):
        return operation()

    monkeypatch.setattr(discovery_feeds, "retry_network_call", call)
    monkeypatch.setattr(follow_fellows, "retry_network_call", call)


def test_saved_preferences_prefer_v2_and_ignore_lists_and_timelines():
    legacy = models.AppBskyActorDefs.SavedFeedsPref(saved=[FEED_URI], pinned=[])
    current = _saved(
        ("feed", FEED_URI + "2"),
        ("feed", FEED_URI + "2"),
        ("list", "at://did:plc:creator/app.bsky.graph.list/list"),
        ("timeline", "following"),
    )
    assert discovery_feeds.saved_feed_uris([legacy, current]) == [FEED_URI + "2"]
    assert discovery_feeds.saved_feed_uris([legacy, _saved()]) == []
    assert discovery_feeds.saved_feed_uris([legacy, legacy]) == [FEED_URI]
    assert discovery_feeds.saved_feed_uris([]) == []


def test_samples_bounded_feeds_and_uses_post_authors_not_reposters(capsys):
    client = mock.Mock()
    client.app.bsky.actor.get_preferences.return_value = SimpleNamespace(
        preferences=[_saved(*[("feed", FEED_URI + str(i)) for i in range(12)])]
    )
    post = _post("did:plc:author")
    post.reason = SimpleNamespace(by=SimpleNamespace(did="did:plc:reposter"))
    client.app.bsky.feed.get_feed.return_value = SimpleNamespace(
        feed=[
            post,
            _post("did:plc:blocked", blocking="at://block"),
            _post("did:plc:blockedby", blocked_by=True),
            _post("did:plc:muted", muted=True),
        ],
        cursor="more-posts",
    )
    candidates = discovery_feeds.fetch_saved_feed_users(client, limit=100)
    assert len(candidates) == 10
    assert all(users == ["did:plc:author"] for users in candidates.values())
    assert client.app.bsky.feed.get_feed.call_count == 10
    client.app.bsky.feed.get_feed.assert_any_call(
        {"feed": FEED_URI + "0", "limit": 100}
    )
    assert "first 10 custom feeds" in capsys.readouterr().out


def test_no_custom_feeds_leaves_tag_discovery_available():
    client = mock.Mock()
    client.app.bsky.actor.get_preferences.return_value = SimpleNamespace(preferences=[])
    assert discovery_feeds.fetch_saved_feed_users(client, limit=100) == {}
    client.app.bsky.feed.get_feed.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
def test_main_combines_sources_with_one_cap_and_preserves_exclusions(
    monkeypatch, dry_run
):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.app.bsky.actor.get_preferences.return_value = SimpleNamespace(
        preferences=[_saved(("feed", FEED_URI))]
    )
    client.app.bsky.feed.get_feed.return_value = SimpleNamespace(
        feed=[
            _post(did)
            for did in ["feed", "shared", "already", "unfollowed", client.me.did]
        ]
    )
    client.app.bsky.feed.search_posts.return_value = SimpleNamespace(
        posts=[
            SimpleNamespace(author=SimpleNamespace(did=did))
            for did in ["shared", "tag"]
        ]
    )
    state = bot_state._default_state()
    bot_state.record_unfollow(state, "unfollowed")
    monkeypatch.setattr(follow_fellows, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        follow_fellows,
        "get_runtime_controls",
        lambda: {"dry_run": dry_run, "action_delay_seconds": 0.01},
    )
    monkeypatch.setattr(follow_fellows.bot_state, "load_state", lambda: state)
    monkeypatch.setattr(follow_fellows, "hashtags", ["jokes"])
    monkeypatch.setattr(follow_fellows, "soft_tag_limit", 1)
    monkeypatch.setattr(follow_fellows, "global_follow_limit", 3)
    with (
        mock.patch.object(
            follow_fellows,
            "fetch_paginated_data",
            return_value=[SimpleNamespace(did="already")],
        ) as graph,
        mock.patch.object(follow_fellows.time, "sleep") as sleep,
        mock.patch.object(
            follow_fellows.bot_state,
            "update_state",
            side_effect=lambda mutator, **kwargs: mutator(state),
        ) as save,
    ):
        follow_fellows.main()
    graph.assert_called_once_with(
        client.get_follows, client.me.did, require_complete=True
    )
    assert sleep.call_count == 2
    if dry_run:
        client.follow.assert_not_called()
        save.assert_not_called()
    else:
        assert client.follow.call_args_list == [
            mock.call("feed"),
            mock.call("shared"),
            mock.call("tag"),
        ]
        assert bot_state.get_follow_grace_dids(state, cutoff_ts=0) == {
            "feed",
            "shared",
            "tag",
        }
        save.assert_called_once()


@pytest.mark.parametrize(
    "failure", ["following", "incomplete", "preferences", "feed", "second_feed"]
)
def test_read_failures_prevent_all_follow_actions(monkeypatch, failure):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.app.bsky.actor.get_preferences.return_value = SimpleNamespace(
        preferences=[_saved(("feed", FEED_URI), ("feed", FEED_URI + "2"))]
    )
    error = requests.RequestException("unavailable")
    graph_error = None
    if failure == "following":
        graph_error = error
    elif failure == "incomplete":
        graph_error = IncompletePaginationError("truncated graph")
    elif failure == "preferences":
        client.app.bsky.actor.get_preferences.side_effect = error
    elif failure == "feed":
        client.app.bsky.feed.get_feed.side_effect = error
    else:
        client.app.bsky.feed.get_feed.side_effect = [
            SimpleNamespace(feed=[_post("candidate")]),
            error,
        ]
    monkeypatch.setattr(follow_fellows, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        follow_fellows,
        "get_runtime_controls",
        lambda: {"dry_run": False, "action_delay_seconds": 0},
    )
    with (
        mock.patch.object(
            follow_fellows,
            "fetch_paginated_data",
            return_value=[],
            side_effect=graph_error,
        ),
        mock.patch.object(
            follow_fellows.bot_state,
            "load_state",
            return_value=bot_state._default_state(),
        ),
        mock.patch.object(follow_fellows.bot_state, "update_state") as save,
        pytest.raises((requests.RequestException, IncompletePaginationError)),
    ):
        follow_fellows.main()
    client.follow.assert_not_called()
    save.assert_not_called()


def test_zero_budget_selects_nobody():
    assert follow_fellows._take_unseen_users("feed:1", ["did:plc:a"], set(), 0) == []
    assert (
        follow_fellows.select_users({"feed:1": ["did:plc:a"]}, ["feed:1"], 1, 0) == []
    )
