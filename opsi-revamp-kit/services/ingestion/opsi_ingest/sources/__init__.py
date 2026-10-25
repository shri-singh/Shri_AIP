"""Source registry. Adapters are imported lazily so a missing optional client
library (e.g. ``elasticsearch``) only breaks the source that needs it."""
from __future__ import annotations

from ..config import Settings
from ..errors import ConfigError
from .base import Source

SOURCE_NAMES = ("elastic", "dynatrace_problems", "dynatrace_grail", "broadcom_oi")


def build_source(name: str, settings: Settings) -> Source:
    if name == "elastic":
        from .elastic import ElasticSource
        return ElasticSource(settings)
    if name == "dynatrace_problems":
        from .dynatrace_problems import DynatraceProblemsSource
        return DynatraceProblemsSource(settings)
    if name == "dynatrace_grail":
        from .dynatrace_grail import DynatraceGrailSource
        return DynatraceGrailSource(settings)
    if name == "broadcom_oi":
        from .broadcom_oi import BroadcomOISource
        return BroadcomOISource(settings)
    raise ConfigError(f"unknown source {name!r}; expected one of {', '.join(SOURCE_NAMES)}")
