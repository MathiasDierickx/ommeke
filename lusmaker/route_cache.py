"""Begrensde memoization van routercalls, uitsluitend binnen één optimalisatie."""
from copy import deepcopy
import json
from threading import Lock


class RouteCache:
    def __init__(self, router, max_entries=512):
        self.router, self.max_entries = router, max_entries
        self.values = {}
        self.hits = self.misses = 0
        self._lock = Lock()

    def __call__(self, points, **kwargs):
        key = json.dumps([points, kwargs], sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self._lock:
            if key in self.values:
                self.hits += 1
                return deepcopy(self.values[key])
            self.misses += 1
        value = self.router(points, **kwargs)
        # Houd de lock niet vast tijdens router-I/O. Gelijktijdige misses voor
        # dezelfde sleutel mogen elk routeren; capaciteit en tellers blijven exact.
        with self._lock:
            if len(self.values) < self.max_entries:
                self.values[key] = deepcopy(value)
        return value
