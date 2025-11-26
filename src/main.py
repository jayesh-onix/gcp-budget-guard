"""Main file that control the whole project's logic."""

from config.budget import ProjectBudget
from config.metrics_objects import (
    BigQueryScannedBytesMetrics,
    CloudMonitoringMetrics,
    FirestoreDocumentDeleteMetrics,
    FirestoreDocumentReadMetrics,
    FirestoreDocumentTTLDeleteMetrics,
    FirestoreDocumentWriteMetrics,
    GeminiModelsMetrics,
)
from helpers.constants import API_LIST, GCP_LOGGER, NUKE_MODE, PROJECT_ID
from wrappers.cloud_apis import WrapperCloudAPIs

# Define your project data
project_budget = ProjectBudget()
cloud_api_wrapper = WrapperCloudAPIs(project_id=PROJECT_ID)

metrics_to_control: list[CloudMonitoringMetrics] = [
    GeminiModelsMetrics(),
    BigQueryScannedBytesMetrics(),
    FirestoreDocumentReadMetrics(),
    FirestoreDocumentWriteMetrics(),
    FirestoreDocumentDeleteMetrics(),
    FirestoreDocumentTTLDeleteMetrics(),
]


# Each Metric
for metrics in metrics_to_control:

    GCP_LOGGER.info(msg=f"Adding Expense for: {metrics.__class__.__name__}")

    daily_ts = metrics.get_times_series(day_interval=1)
    weekly_ts = metrics.get_times_series(day_interval=7)
    monthly_ts = metrics.get_times_series(day_interval=30)

    project_budget.current_expense.daily += metrics.get_expense(time_series=daily_ts)
    project_budget.current_expense.weekly += metrics.get_expense(time_series=weekly_ts)
    project_budget.current_expense.monthly += metrics.get_expense(
        time_series=monthly_ts
    )

    GCP_LOGGER.info(msg=f"{project_budget.current_expense}")

GCP_LOGGER.info(f"Budget: {project_budget.expense_limit}")
if project_budget.check_expense_limit():
    if NUKE_MODE:
        GCP_LOGGER.info(msg="Project Budget Reached. Killing APIs.")
        for api in API_LIST:
            cloud_api_wrapper.disable_api(api_name=api)
    else:
        GCP_LOGGER.info(msg="Nuke MODE set to False, skipping disabling APIs.")
