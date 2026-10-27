"""Persist report receipts and resolution operations against fresh moderation state."""

import copy
import hashlib
import time

from thejokebot import state as bot_state
from thejokebot import state_transactions

ACK_FIELDS = (
    "source_reply_uri",
    "reply_cid",
    "root_uri",
    "root_cid",
    "source_post_uri",
)
PROPOSAL_FIELDS = (
    "b64",
    "source_provider",
    "source_post_uri",
    "source_reply_uri",
    "reason",
)


def proposal_key(proposal):
    target = (
        "jokebook"
        if proposal.get("source_provider") == "jokebot_jokebook"
        else "denylist"
    )
    return hashlib.sha256(f"{target}:{proposal['b64']}".encode()).hexdigest()


def pending_proposals(state):
    return state.setdefault("reports", {}).setdefault("pending_proposals", {})


def _queue_proposals(state, proposals):
    receipts = state.setdefault("reports", {}).setdefault("proposal_deliveries", {})
    pending = pending_proposals(state)
    for proposal in proposals:
        if not isinstance(proposal.get("b64"), str) or not proposal["b64"]:
            continue
        key = proposal_key(proposal)
        if key not in receipts:
            pending.setdefault(
                key, {field: proposal.get(field) for field in PROPOSAL_FIELDS}
            )


def enqueue_proposals(state, proposals):
    state_transactions.apply(
        state, lambda latest: _queue_proposals(latest, proposals), domains="moderation"
    )


def confirm_delivery(state, proposal, proof):
    key = proposal_key(proposal)

    def record(latest):
        pending_proposals(latest).pop(key, None)
        receipts = latest["reports"].setdefault("proposal_deliveries", {})
        receipts[key] = {"number": proof["number"], "state": proof["state"]}
        while len(receipts) > 5000:
            del receipts[next(iter(receipts))]

    state_transactions.apply(state, record, domains="moderation")


def pending_acknowledgements(state):
    return state.setdefault("reports", {}).setdefault("pending_acknowledgements", {})


def receipt(state, uri, *, deleted=False):
    def record(latest):
        if deleted:
            bot_state.record_deleted_post_uri(latest, uri)
        else:
            bot_state.record_acknowledged_report_uri(latest, uri)
            pending_acknowledgements(latest).pop(uri, None)

    state_transactions.apply(state, record, domains="moderation")


def scan(state, processed, changes, proposals):
    checked_at = int(time.time())

    def record(latest):
        known = bot_state.get_processed_notification_uris(latest)
        for uri in changes.get("resolved", ()):
            bot_state.clear_unresolved_notification_attempt(latest, uri)
        for uri in changes.get("attempted", ()):
            if uri in known:
                continue
            count = bot_state.increment_unresolved_notification_attempt(latest, uri)
            if count >= changes["max_attempts"]:
                bot_state.record_processed_notification(latest, uri)
                known.add(uri)
                bot_state.clear_unresolved_notification_attempt(latest, uri)
        for uri in processed:
            bot_state.record_processed_notification(latest, uri)
            bot_state.clear_unresolved_notification_attempt(latest, uri)
        _queue_acknowledgements(latest, proposals)
        _queue_proposals(latest, proposals)
        bot_state.prune_processed_notifications(latest)
        bot_state.prune_unresolved_notification_attempts(latest)
        if changes.get("complete"):
            reports = latest["reports"]
            reports["last_checked_at"] = max(
                reports.get("last_checked_at") or 0, checked_at
            )
        return copy.deepcopy(latest["reports"])

    state["reports"] = bot_state.update_state(record, domains="moderation")


def _queue_acknowledgements(state, proposals):
    acknowledged = bot_state.get_acknowledged_report_uris(state)
    pending = pending_acknowledgements(state)
    for proposal in proposals:
        uri = proposal.get("source_reply_uri")
        if uri and uri not in acknowledged:
            pending.setdefault(
                uri, {field: proposal.get(field) for field in ACK_FIELDS}
            )
