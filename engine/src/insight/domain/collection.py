"""Collection coverage is independent of the number of successfully fetched documents."""

from typing import Any

from insight.domain.contracts import FrozenInput, Observation, Source


def channel_of(source: Source) -> str:
    if source.origin:
        return source.origin.channel
    return {
        "local": "local",
        "youtube": "youtube",
        "x": "x",
        "conference": "conference",
        "feed": "feed",
    }.get(source.provider, "unclassified")


def collection_coverage(
    frozen: FrozenInput, observations: tuple[Observation, ...]
) -> dict[str, Any]:
    requirements = frozen.project.collection_requirements
    if requirements is None:
        return dict(
            assessed=False,
            complete=False,
            channels=[],
            detail="Historical run has no independent channel requirements; document success does not establish multi-channel completeness",
        )
    by_source = {o.source_id: o for o in observations}
    sources = {s.source_id: s for s in frozen.sources}
    channels = []
    complete = True
    for requirement in requirements:
        items = [
            i for i in frozen.plan.items if channel_of(sources[i.source_ref]) == requirement.channel
        ]
        matching = [i for i in items if not requirement.goals or i.goal in requirement.goals]
        if requirement.disposition == "required":
            matching = [i for i in matching if i.required]
        missing_goals = sorted(set(requirement.goals) - {i.goal for i in matching})
        states = [by_source[i.source_ref] for i in matching if i.source_ref in by_source]
        if requirement.disposition == "excluded":
            state = "excluded"
        elif not matching or missing_goals:
            state = "not_planned"
        elif len(states) < len(matching):
            state = "not_attempted"
        elif all(o.goal_result.state == "met" for o in states):
            state = "acquired"
        elif any(o.goal_result.state == "met" for o in states):
            state = "partial"
        elif any(o.goal_result.reason_code in ("ACCESS_REQUIRED", "RATE_LIMITED") for o in states):
            state = "access_required"
        elif any(
            o.goal_result.reason_code in ("UNSUPPORTED_CAPABILITY", "DEPENDENCY_REQUIRED")
            for o in states
        ):
            state = "unsupported"
        else:
            state = "failed"
        if requirement.disposition == "required" and state != "acquired":
            complete = False
        channels.append(
            dict(
                channel=requirement.channel,
                disposition=requirement.disposition,
                goals=list(requirement.goals),
                state=state,
                rationale=requirement.rationale,
                missing_goals=missing_goals,
                sources=[i.source_ref for i in matching],
                reasons=[o.goal_result.model_dump(mode="json") for o in states],
            )
        )
    return dict(
        assessed=True,
        complete=complete,
        channels=channels,
        detail="Required channels and goals checked against the independent project requirements",
    )
