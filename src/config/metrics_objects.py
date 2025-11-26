"""Manage Google Cloud Monitoring interactions."""

from google.cloud.monitoring_v3.services.metric_service.pagers import (
    ListTimeSeriesPager,
)

from helpers.constants import PROJECT_ID
from services.expense_controller import ExpenseControllerService
from wrappers.cloud_monitoring import WrapperCloudMonitoring


class CloudMonitoringMetrics:
    """Object to wrap Google Cloud Monitoring interactions."""

    def __init__(self, project_id: str = PROJECT_ID) -> None:
        self.filter: str
        self.group_by_fields: list[str] | None = None
        self.project_id: str = project_id
        self.cloud_monitoring_client = WrapperCloudMonitoring(
            project_id=self.project_id
        )
        self.expense_controller = ExpenseControllerService()

    def get_times_series(self, day_interval: int) -> ListTimeSeriesPager | None:
        """
        Control any metrics from GCP and return a TimeSeries (TS).

        TS are aggregated by days.
        """
        return self.cloud_monitoring_client.get_metrics_time_series(
            request_filter=self.filter,
            group_by_fields=self.group_by_fields,
            day_interval=day_interval,
        )

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        """Define base Get Expense Method that will be create on child."""
        raise NotImplementedError(
            "Each child class must implement its own get_expense method"
        )


class GeminiModelsMetrics(CloudMonitoringMetrics):
    """Metrics based on PublisherModel & token_count."""

    def __init__(self) -> None:
        super().__init__()
        self.filter: str = (
            'metric.type = "aiplatform.googleapis.com/publisher/online_serving/token_count" '
            'AND resource.type = "aiplatform.googleapis.com/PublisherModel"'
        )

        self.group_by_fields: list[str] = ["resource.model_user_id", "metric.type"]

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        return self.expense_controller.get_vertex_ai_expense(time_series=time_series)


class BigQueryScannedBytesMetrics(CloudMonitoringMetrics):
    """Metrics based on Scanned Bytes on Big Query (Query Read)."""

    def __init__(self) -> None:
        super().__init__()
        self.filter: str = (
            'metric.type = "bigquery.googleapis.com/query/statement_scanned_bytes_billed"'
        )
        self.group_by_fields: list[str] = []

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        return self.expense_controller.get_bigquery_scanned_bytes_expense(
            time_series=time_series
        )


class FirestoreDocumentReadMetrics(CloudMonitoringMetrics):
    """Metric based on Firestore Document Read Count."""

    def __init__(self) -> None:
        super().__init__()
        self.filter: str = (
            'metric.type = "firestore.googleapis.com/document/read_count"'
        )

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        return self.expense_controller.get_firestore_expense(
            time_series=time_series, action="read"
        )


class FirestoreDocumentWriteMetrics(CloudMonitoringMetrics):
    """Metric based on Firestore Document Write Count."""

    def __init__(self) -> None:
        super().__init__()
        self.filter: str = (
            'metric.type = "firestore.googleapis.com/document/write_count"'
        )

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        return self.expense_controller.get_firestore_expense(
            time_series=time_series, action="write"
        )


class FirestoreDocumentDeleteMetrics(CloudMonitoringMetrics):
    """Metric based on Firestore Document Write Count."""

    def __init__(self) -> None:
        super().__init__()
        self.filter: str = (
            'metric.type = "firestore.googleapis.com/document/delete_count"'
        )

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        return self.expense_controller.get_firestore_expense(
            time_series=time_series, action="delete"
        )


class FirestoreDocumentTTLDeleteMetrics(CloudMonitoringMetrics):
    """Metric based on Firestore Document Write Count."""

    def __init__(self) -> None:
        super().__init__()
        self.filter: str = (
            'metric.type = "firestore.googleapis.com/document/ttl_deletion_count"'
        )

    def get_expense(self, time_series: ListTimeSeriesPager) -> float:
        return self.expense_controller.get_firestore_expense(
            time_series=time_series, action="ttl_delete"
        )
