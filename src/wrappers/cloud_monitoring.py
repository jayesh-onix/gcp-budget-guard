"""Wrapper for Google Cloud Monitoring – time-series queries.

Queries are scoped to the current calendar month (1st of month → now)
so that cost estimates match the monthly billing cycle.
"""

from datetime import timedelta

from google.cloud import monitoring_v3
from google.cloud.monitoring_v3.services.metric_service.pagers import (
    ListTimeSeriesPager,
)

from helpers import utils
from helpers.constants import APP_LOGGER, PROJECT_ID


class WrapperCloudMonitoring:
    """Query Cloud Monitoring time-series data."""

    def __init__(self) -> None:
        self.client = monitoring_v3.MetricServiceClient()
        APP_LOGGER.info(msg="Cloud Monitoring wrapper initialised.")

    def get_total_units(
        self,
        metric_name: str,
        metric_filter: str | None = None,
        group_by_fields: list[str] | None = None,
    ) -> int:
        """Return the aggregate count of units for a metric this month."""
        ts_pager = self._query_time_series(metric_name, metric_filter, group_by_fields)
        if ts_pager is None:
            return 0

        total = 0
        for ts in ts_pager:
            for point in ts.points:
                total += point.value.int64_value
        APP_LOGGER.debug(msg=f"Metric {metric_name}: total units = {total}")
        return total

    # ── internal ──────────────────────────────────────────────────────────

    def _query_time_series(
        self,
        metric_name: str,
        metric_filter: str | None,
        group_by_fields: list[str] | None,
    ) -> ListTimeSeriesPager | None:
        """Build and execute a Cloud Monitoring list_time_series request."""
        interval = monitoring_v3.TimeInterval(
            start_time=utils.first_day_of_current_month_utc(),
            end_time=utils.now_utc(),
        )

        aggregation = monitoring_v3.Aggregation(
            alignment_period=timedelta(days=1),
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
            cross_series_reducer=monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
            group_by_fields=group_by_fields or [],
        )

        full_filter = f'metric.type = "{metric_name}"'
        if metric_filter:
            full_filter += f" AND {metric_filter}"

        APP_LOGGER.debug(msg=f"Monitoring query: filter={full_filter}")

        try:
            pager = self.client.list_time_series(
                request={
                    "name": f"projects/{PROJECT_ID}",
                    "filter": full_filter,
                    "interval": interval,
                    "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                    "aggregation": aggregation,
                }
            )
            return pager if pager else None
        except Exception as exc:
            APP_LOGGER.error(msg=f"Error querying metric {metric_name}: {exc}")
            return None
