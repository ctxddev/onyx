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

from onyx.configs.app_configs import EXTRA_EVENT_SOURCE_MODULES
from onyx.connectors.event_inbox.registration import (
    claimed_event_sources,
    unregister_event_source,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Module paths, not objects: importing this list must not pull a source's SDK
# into every process that only wants to know which sources exist.
#
# The ones shipped in this repository, then the ones a deployment installs
# beside it. A source outside this repository needs no change here.
_BUILT_IN_EVENT_SOURCE_MODULES: tuple[str, ...] = ()
EVENT_SOURCE_MODULES: tuple[str, ...] = (
    _BUILT_IN_EVENT_SOURCE_MODULES + EXTRA_EVENT_SOURCE_MODULES
)

_loaded = False


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
        before = claimed_event_sources()
        try:
            importlib.import_module(module_path)
        except Exception:
            # A module claims several registries in turn and can raise
            # between two of them. Drop only what it added, so one broken
            # source leaves the others alone: a missing route is better
            # than one serving a half-registered spec.
            for source in claimed_event_sources() - before:
                unregister_event_source(source)
            logger.exception("Could not load event source %s", module_path)

    _loaded = True
