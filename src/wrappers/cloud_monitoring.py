"""Manage Google Cloud Monitoring interactions."""

from datetime import datetime, timedelta, timezone

from google.cloud import monitoring_v3
from google.cloud.monitoring_v3.services.metric_service.pagers import (
    ListTimeSeriesPager,
)


class WrapperCloudMonitoring:
    """Object to wrap Google Cloud Monitoring interactions."""

    def __init__(self, project_id: str) -> None:
        self.monitoring_client = monitoring_v3.MetricServiceClient()
        self.project_id = project_id

    def get_metrics_time_series(
        self, request_filter: str, group_by_fields: list[str], day_interval: int
    ) -> ListTimeSeriesPager | None:
        """
        Control any metrics from GCP and return a TimeSeries (TS).

        TS are aggregated by days.
        """

        # Time / Interval variables to build Cloud Monitoring Request
        now = datetime.now(tz=timezone.utc)
        time_interval: monitoring_v3.TimeInterval = monitoring_v3.TimeInterval(
            end_time=now, start_time=now - timedelta(days=day_interval)
        )
        # How to aggregate Cloud Monitoring Result
        aggregation = monitoring_v3.Aggregation(
            alignment_period=timedelta(days=1),
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_SUM,  # Align per SUM to have full value
            cross_series_reducer=monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
            group_by_fields=group_by_fields,
        )

        #  Cloud Monitoring Request
        time_series = self.monitoring_client.list_time_series(
            request={
                "name": f"projects/{self.project_id}",
                "filter": request_filter,
                "interval": time_interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                "aggregation": aggregation,
            }
        )
        if time_series:
            return time_series
        return None
