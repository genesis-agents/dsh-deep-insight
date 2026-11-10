from typing import Protocol


class PresentationInspector(Protocol):
    def slide_count(self, content: bytes) -> int: ...
