from typing import Protocol


class MediaSetup(Protocol):
    def install_model(self, model: str) -> dict[str, str]: ...
