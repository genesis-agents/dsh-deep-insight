"""Inspect collector configuration and independent channel scope through the application boundary."""

from collections.abc import Callable
from typing import Any

from insight.domain.collection import collection_coverage
from insight.domain.contracts import FrozenInput, PlatformError
from insight.ports.media import MediaSetup
from insight.ports.sources import SourceProvider
from insight.ports.storage import ProfileStore, Transaction


class CollectorService:
    def __init__(
        self,
        tx: Transaction,
        providers: dict[str, SourceProvider],
        profiles: ProfileStore,
        code_ref: str,
        clock: Callable[[], str],
        media_setup: MediaSetup | None = None,
    ) -> None:
        self.tx, self.providers, self.profiles, self.code_ref, self.clock = (
            tx,
            providers,
            profiles,
            code_ref,
            clock,
        )
        self.media_setup = media_setup

    def setup_asr(self, model: str) -> dict[str, str]:
        if self.media_setup is None:
            raise PlatformError("DEPENDENCY_REQUIRED", "Local ASR runtime is not configured")
        return self.media_setup.install_model(model)

    def catalog(self) -> dict[str, Any]:
        return {
            name: dict(
                capabilities=list(provider.capabilities()),
                live_success="must_be_proved_for_the_actual_source_and_goal",
            )
            for name, provider in self.providers.items()
        }

    def preflight(self, plan_id: str) -> dict[str, Any]:
        with self.tx(None) as repo:
            plan = repo.plan(plan_id)
            project = repo.project(plan.project_id, plan.project_revision)
            frozen = FrozenInput(
                project=project,
                plan=plan,
                profile=self.profiles.get(project.profile_ref),
                sources=tuple(repo.source(i.source_ref) for i in plan.items),
                code_ref=self.code_ref,
            )
        return dict(
            plan_id=plan_id,
            collection_coverage=collection_coverage(frozen, ()),
            collectors=self.catalog(),
        )

    def probe(self, run_id: str, source_id: str) -> dict[str, Any]:
        with self.tx(None) as repo:
            source = next(
                (s for s in repo.frozen_input(run_id).sources if s.source_id == source_id), None
            )
        if source is None:
            raise PlatformError("NOT_FOUND", "Source not in the frozen run")
        provider = self.providers.get(source.provider)
        try:
            result = provider.probe(source) if provider else dict(state="unsupported")
        except PlatformError as exc:
            result = dict(state="blocked", code=exc.code, detail=exc.detail)
        with self.tx(None) as repo:
            repo.event(
                run_id, "collector_probed", dict(source_id=source_id, result=result), self.clock()
            )
        return dict(source_id=source_id, **result)
