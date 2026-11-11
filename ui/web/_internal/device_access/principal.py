"""Identity established only by the separate HTTPS device gateway."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedMobileDevice:
    device_id: str
