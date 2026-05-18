"""Lead source plug-in contract.

Each scraper lives in workers/leads/<slug>.py and exposes a module-level
`source = MySource()`. The runner iterates them, calls discover(), then
classifier.py scores the raw hits with Haiku.

Lead != Job: a lead is a signal that a company runs Vicidial (or could
buy our offer). It may be a forum post, a hiring ad, a Reddit thread, or
a search-result snippet.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class RawLead:
    """One hit from a source. Persisted verbatim in `leads.raw_json`."""
    source: str
    source_url: str
    title: str | None = None
    excerpt: str | None = None
    company_guess: str | None = None
    company_domain: str | None = None
    signal_kind: str | None = None  # 'hiring' | 'customer_mention' | 'forum_post' | 'support_request' | 'job_post'
    posted_at: str | None = None    # ISO 8601
    raw_json: dict[str, Any] | None = None


class LeadSource(ABC):
    """Implement in workers/leads/<slug>.py and export `source = YourSource()`."""

    slug: str
    lead_kind: str = "vicidial"

    @abstractmethod
    def discover(self) -> Iterable[RawLead]:
        """Yield raw leads. Should be polite to the upstream (delays, UA)
        and dedupe within a single run."""
