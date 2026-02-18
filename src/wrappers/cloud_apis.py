"""Wrapper for enabling / disabling individual GCP service APIs.

IMPORTANT DESIGN DECISION
─────────────────────────
• We ONLY disable individual service APIs (e.g. firestore.googleapis.com).
• We NEVER delete the GCP project.
• We NEVER remove or unlink the billing account.
• `disable_dependent_services` is always False to prevent cascading outages.
"""

import time

from googleapiclient import discovery
from googleapiclient.errors import HttpError

from helpers.constants import APP_LOGGER, DRY_RUN_MODE


class WrapperCloudAPIs:
    """Enable / disable individual GCP service APIs."""

    def __init__(self, project_id: str) -> None:
        self.service_usage_client = discovery.build(
            serviceName="serviceusage", version="v1"
        )
        self.project_id = project_id
        APP_LOGGER.info(msg=f"Cloud APIs wrapper initialised for project {project_id}")

    # pylint: disable=no-member
    def disable_api(self, api_name: str, max_retries: int = 3) -> bool:
        """Disable a single API.  Returns True on success."""
        if DRY_RUN_MODE:
            APP_LOGGER.warning(
                msg=f"[DRY RUN] Would disable API: {api_name}"
            )
            return True

        for attempt in range(1, max_retries + 1):
            try:
                APP_LOGGER.info(
                    msg=f"Disabling API {api_name} (attempt {attempt}/{max_retries})"
                )
                request = self.service_usage_client.services().disable(
                    name=f"projects/{self.project_id}/services/{api_name}",
                    body={"disable_dependent_services": False},
                )
                response = request.execute()
                APP_LOGGER.warning(
                    msg=f"Successfully disabled API: {api_name}  response={response}"
                )
                return True

            except HttpError as http_err:
                status = http_err.resp.status
                reason = getattr(http_err, "reason", str(http_err))
                if status in (403, 400):
                    APP_LOGGER.error(
                        msg=f"Non-retryable error ({status}) disabling {api_name}: {reason}"
                    )
                    return False
                if status == 404:
                    APP_LOGGER.warning(
                        msg=f"API {api_name} not found / already disabled"
                    )
                    return True
                APP_LOGGER.error(
                    msg=f"HTTP {status} disabling {api_name} (attempt {attempt}): {reason}"
                )
            except Exception as exc:
                APP_LOGGER.error(
                    msg=f"Unexpected error disabling {api_name} (attempt {attempt}): {exc}"
                )

            if attempt < max_retries:
                wait = 2 ** attempt
                APP_LOGGER.info(msg=f"Retrying in {wait}s …")
                time.sleep(wait)

        APP_LOGGER.error(msg=f"Failed to disable {api_name} after {max_retries} attempts")
        return False

    def enable_api(self, api_name: str, max_retries: int = 3) -> bool:
        """Re-enable a previously disabled API.  Returns True on success."""
        if DRY_RUN_MODE:
            APP_LOGGER.warning(
                msg=f"[DRY RUN] Would enable API: {api_name}"
            )
            return True

        for attempt in range(1, max_retries + 1):
            try:
                APP_LOGGER.info(
                    msg=f"Enabling API {api_name} (attempt {attempt}/{max_retries})"
                )
                request = self.service_usage_client.services().enable(
                    name=f"projects/{self.project_id}/services/{api_name}",
                )
                response = request.execute()
                APP_LOGGER.info(
                    msg=f"Successfully enabled API: {api_name}  response={response}"
                )
                return True
            except HttpError as http_err:
                status = http_err.resp.status
                reason = getattr(http_err, "reason", str(http_err))
                if status == 403:
                    APP_LOGGER.error(
                        msg=f"Permission denied enabling {api_name}: {reason}"
                    )
                    return False
                APP_LOGGER.error(
                    msg=f"HTTP {status} enabling {api_name} (attempt {attempt}): {reason}"
                )
            except Exception as exc:
                APP_LOGGER.error(
                    msg=f"Unexpected error enabling {api_name} (attempt {attempt}): {exc}"
                )

            if attempt < max_retries:
                wait = 2 ** attempt
                APP_LOGGER.info(msg=f"Retrying in {wait}s …")
                time.sleep(wait)

        APP_LOGGER.error(msg=f"Failed to enable {api_name} after {max_retries} attempts")
        return False

    def get_api_status(self, api_name: str) -> str | None:
        """Return the state of an API ('ENABLED', 'DISABLED') or None on error."""
        try:
            request = self.service_usage_client.services().get(
                name=f"projects/{self.project_id}/services/{api_name}"
            )
            response = request.execute()
            return response.get("state", "UNKNOWN")
        except Exception as exc:
            APP_LOGGER.error(msg=f"Error getting status of {api_name}: {exc}")
            return None
