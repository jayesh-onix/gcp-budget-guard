"""Manage expense per time series depending of the GCP Service."""

from google.cloud.monitoring_v3.services.metric_service.pagers import (
    ListTimeSeriesPager,
)

from config.prices.bigquery import BIGQUERY_PRICES
from config.prices.firestore import FIRESTORE_PRICES
from config.prices.vertex_ai import GEMINI_PRICES
from helpers.constants import GCP_LOGGER


class ExpenseControllerService:
    """Expense Controller Object that wrap each service expense control."""

    def __init__(self) -> None:
        pass

    def get_vertex_ai_expense(self, time_series: ListTimeSeriesPager) -> float:
        """
        Control each value and compute the price per token & model.

        Example of a time series (TS) object:
            time_series {
                metric {
                    labels {
                    key: "type"
                    value: "input"
                    }
                    type: "aiplatform.googleapis.com/publisher/online_serving/token_count"
                }
                resource {
                    type: "aiplatform.googleapis.com/PublisherModel"
                    labels {
                    key: "model_user_id"
                    value: "gemini-2.5-pro"
                    }
                    labels {
                    key: "project_id"
                    value: "your-project-id"
                    }
                }
                metric_kind: DELTA
                value_type: INT64
                points {
                    interval {
                    start_time {
                        seconds: 1761662833
                        nanos: 953400000
                    }
                    end_time {
                        seconds: 1761749233
                        nanos: 953400000
                    }
                    }
                    value {
                    int64_value: 6911
                    }
                }
            }
        """

        total_cost = 0.00

        for ts in time_series:

            model_name = ts.resource.labels.get("model_user_id")
            metric_type = ts.metric.labels.get("type")

            matched_model = None
            max_len = 0
            for key in GEMINI_PRICES:
                # pick the longest
                if model_name.startswith(key) and len(key) > max_len:
                    matched_model = key
                    max_len = len(key)

            if not matched_model:
                GCP_LOGGER.debug(
                    msg=f"[VERTEX_AI] - Model {model_name} not supported, check the doc to see why and/or contact admin."
                )
                continue

            for point in ts.points:
                token_price = GEMINI_PRICES[matched_model].get_price_per_token(
                    metric_type=metric_type
                )
                total_cost += point.value.int64_value * token_price

            # TODO: Manage Verbosity / ultra debug
            # GCP_LOGGER.debug(msg=time_series)
            GCP_LOGGER.debug(
                msg=f"[VERTEX_AI] - Model: {model_name}, Matched: {matched_model}, Type: {metric_type}, Cost: {total_cost}"
            )
        return round(number=total_cost, ndigits=2)

    def get_bigquery_scanned_bytes_expense(
        self, time_series: ListTimeSeriesPager
    ) -> float:
        """
                Control how much Big Query Scanned Bytes

                Example TS Object :
                {
          type: "bigquery.googleapis.com/query/scanned_bytes_billed"
        }
        resource {
          type: "global"
          labels {
            key: "project_id"
            value: "your-project-id"
          }
        }
        metric_kind: DELTA
        value_type: INT64
        points {
          interval {
            start_time {
              seconds: 1763203279
              nanos: 411633000
            }
            end_time {
              seconds: 1763289679
              nanos: 411633000
            }
          }
          value {
            int64_value: 10485760
          }
        }
        """
        bytes_per_tib = 1024**4
        scanned_billed_bytes = 0.00

        for ts in time_series:
            for point in ts.points:
                scanned_billed_bytes += point.value.int64_value

        total_scanned_billed_tib = round((scanned_billed_bytes / bytes_per_tib), 2)
        total_cost = total_scanned_billed_tib * BIGQUERY_PRICES.get("scanned_tb")

        GCP_LOGGER.debug(
            msg=f"[BIGQUERY] - Total bytes : {scanned_billed_bytes} - Tib : {total_scanned_billed_tib} - Total Cost: {total_cost}$"
        )

        return round(number=total_cost, ndigits=2)

    def get_firestore_expense(
        self, time_series: ListTimeSeriesPager, action: str
    ) -> float:
        """
        Return Firestore Expense Based on its Action Type :
            - Read
            - Write
            - Delete
            - TTL Delete
        """

        action_count: int = 0
        try:
            action_price = FIRESTORE_PRICES.get(action)
        except Exception:
            GCP_LOGGER.warning(
                msg=f"[FIRESTORE] - Action {action} not supported, check the doc to see why and/or contact admin."
            )
            return 0.0

        for ts in time_series:
            for point in ts.points:
                action_count += point.value.int64_value

        # paid per 100k
        total_cost: float = (action_count / 100_000) * action_price

        GCP_LOGGER.debug(
            msg=f"[FIRESTORE] - Action: {action} - Count: {action_count} - Total Cost: {total_cost}$"
        )

        return round(number=total_cost, ndigits=2)
