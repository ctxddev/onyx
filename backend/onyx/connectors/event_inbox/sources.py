"""The list of event-based sources, and the import that registers them.

A source's spec, handler and search behaviour only exist once the module
that declares them is imported, and nothing imports a source by accident:
the connector registry loads source modules lazily, and the webhook server
never loads them at all. So the modules are named here and imported on
purpose.

Add a source by appending its module path. That module registers itself at
import time.
"""

import importlib

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.handlers import (
    event_handler_sources,
    unregister_event_handler,
)
from onyx.connectors.event_inbox.source_registry import (
    registered_webhook_sources,
    unregister_webhook_source,
    webhook_source_for,
)
from onyx.context.search.enrichment.registry import (
    enrichment_source_types,
    unregister_enrichment_source,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Module paths, not objects: importing this list must not pull a source's SDK
# into every process that only wants to know which sources exist.
EVENT_SOURCE_MODULES: tuple[str, ...] = ()

_loaded = False


def _claimed_sources() -> set[DocumentSource]:
    """Every source that holds a registration of any kind."""
    return (
        {spec.source for spec in registered_webhook_sources()}
        | set(enrichment_source_types())
        | event_handler_sources()
    )


def _give_up(source: DocumentSource) -> None:
    """Undo every registration one source holds."""
    spec = webhook_source_for(source)
    if spec is not None:
        unregister_webhook_source(spec.slug)
    unregister_enrichment_source(source)
    unregister_event_handler(source)


def load_event_sources() -> None:
    """Import every event source so its registrations exist.

    Called by the webhook server when it builds its routes, by the drain
    before it reads the queue, and by the search path before it withholds a
    source, because those run in different processes and each needs the
    registrations. Safe to call repeatedly.
    """
    global _loaded
    if _loaded:
        return

    for module_path in EVENT_SOURCE_MODULES:
        before = _claimed_sources()
        try:
            importlib.import_module(module_path)
        except Exception:
            # A module claims several registries in turn and can raise
            # between two of them. Drop only what it added, so one broken
            # source leaves the others alone: a missing route is better
            # than one serving a half-registered spec.
            for source in _claimed_sources() - before:
                _give_up(source)
            logger.exception("Could not load event source %s", module_path)

    _loaded = True
