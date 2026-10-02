"""Begrensde memoization van routercalls, uitsluitend binnen één optimalisatie."""
from copy import deepcopy
import json


class RouteCache:
    def __init__(self, router, max_entries=512):
        self.router, self.max_entries = router, max_entries
        self.values = {}
        self.hits = self.misses = 0

    def __call__(self, points, **kwargs):
        key = json.dumps([points, kwargs], sort_keys=True, separators=(',', ':'), allow_nan=False)
        if key in self.values:
            self.hits += 1
            return deepcopy(self.values[key])
        self.misses += 1
        value = self.router(points, **kwargs)
        if len(self.values) < self.max_entries:
            self.values[key] = deepcopy(value)
        return value
