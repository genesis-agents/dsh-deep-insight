from __future__ import annotations

import keyring
from keyring.errors import KeyringError

from insight.domain.contracts import PlatformError


class OperatingSystemSecrets:
    """Read a specifically requested secret reference, never enumerate credential stores."""

    def get(self, credential_ref: str) -> str | None:
        if not credential_ref.startswith("credential://"):
            raise PlatformError("INVALID_SPEC", "Expected a credential reference")
        try:
            return keyring.get_password(
                "personal-insight-platform", credential_ref.removeprefix("credential://")
            )
        except KeyringError as exc:
            raise PlatformError(
                "ACCESS_REQUIRED", "Operating-system credential backend is unavailable"
            ) from exc

    def set(self, credential_ref: str, value: str) -> None:
        if not credential_ref.startswith("credential://") or not value.strip():
            raise PlatformError(
                "INVALID_SPEC", "Expected a credential reference and nonempty secret"
            )
        try:
            keyring.set_password(
                "personal-insight-platform", credential_ref.removeprefix("credential://"), value
            )
        except KeyringError as exc:
            raise PlatformError(
                "ACCESS_REQUIRED", "Operating-system credential backend is unavailable"
            ) from exc
