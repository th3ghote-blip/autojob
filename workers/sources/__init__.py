"""Source registry. Adding a board = drop a file here + insert a row into
the `sources` table with a matching slug. The runner imports by slug.
"""
from __future__ import annotations

import importlib
from typing import Iterable

from .base import NormalizedJob, Source


def load(slug: str) -> Source:
    """Dynamically import workers.sources.<slug> and instantiate its `source` export.

    Slugs containing ':' (e.g. 'greenhouse:openai') resolve to the prefix module.
    """
    module_name = slug.split(":", 1)[0]
    mod = importlib.import_module(f"workers.sources.{module_name}")
    return mod.source  # each source module exports a module-level `source` instance


__all__ = ["NormalizedJob", "Source", "load"]
