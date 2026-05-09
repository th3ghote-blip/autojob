"""Source plug-in contract.

Each board lives in workers/sources/<slug>.py and exposes a module-level
`source = MySource()`. The runner loads it by slug, calls discover() to
get raw listings, then parse() to normalize each into a NormalizedJob.

The rest of the system never knows or cares which board a job came from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class RawListing:
    """One listing as fetched from the source. Stored verbatim in job_raw."""
    external_id: str
    payload_json: dict[str, Any]
    payload_html: str | None = None


@dataclass
class NormalizedJob:
    """Parsed listing in the shape the rest of the system expects."""
    external_id: str
    title: str
    company_name: str
    company_domain: str | None = None
    company_website: str | None = None
    description: str | None = None
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str = "USD"
    location: str | None = None
    remote: bool = False
    employment_type: str | None = None  # full_time | contract | consulting
    contact_name: str | None = None
    contact_email: str | None = None
    contact_role: str | None = None
    url: str | None = None
    posted_at: str | None = None  # ISO 8601


class Source(ABC):
    """Implement this in workers/sources/<slug>.py and export `source = YourSource()`."""

    slug: str
    kind: str  # 'html' | 'api' | 'ats' | 'rss'

    @abstractmethod
    def discover(self, config: dict[str, Any]) -> Iterable[RawListing]:
        """Fetch from the source. Yield RawListing per item found.

        Should respect rate limits, retry transient failures, and avoid
        re-fetching listings already in job_raw if cheap to do so.
        """

    @abstractmethod
    def parse(self, raw: RawListing) -> NormalizedJob | None:
        """Convert a RawListing into a NormalizedJob. Return None to skip."""
