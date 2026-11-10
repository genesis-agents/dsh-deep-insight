"""Project persisted review receipts for readers without duplicating model transcripts."""


def reader_events(events):
    """Retain verdicts and identifiers; full requests and responses remain in storage."""
    result = []
    for event in events:
        payload = dict(event["payload"])
        if event["kind"] in {"review_requested", "capability_requested"}:
            payload.pop("messages", None)
        elif event["kind"] in {"review_completed", "review_failed", "capability_completed", "capability_failed"}:
            payload.pop("output", None)
        result.append({**event, "payload": payload})
    return result
