"""
Query utility functions.

Shared utilities used across query modules.
"""

import logging
import operator
from typing import List, Optional, Dict
from peewee import reduce

try:
    from ...models import MetricSeries
except ImportError:
    from models import MetricSeries

logger = logging.getLogger("dcmon.server")


def filter_series_by_labels(base_query, label_filters: Optional[List[Dict[str, str]]] = None):
    """
    Filter MetricSeries by exact label key-value pairs.

    Args:
        base_query: Base MetricSeries query
        label_filters: List of label filters, e.g. [{"sensor": "CPU Temp"}, {"sensor": "VRM Temp"}]

    Returns:
        Filtered query
    """
    if not label_filters:
        return base_query

    conditions = []
    for label_filter in label_filters:
        for key, value in label_filter.items():
            # Match exact key-value in JSON: {"sensor":"CPU Temp"}
            conditions.append(MetricSeries.labels.contains(f'"{key}":"{value}"'))

    if len(conditions) == 1:
        return base_query.where(conditions[0])
    else:
        combined_condition = reduce(operator.or_, conditions)
        return base_query.where(combined_condition)
