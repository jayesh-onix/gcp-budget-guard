"""Manage Google Cloud APIs."""

from googleapiclient import discovery

from helpers.constants import GCP_LOGGER


class WrapperCloudAPIs:
    """Object to wrap Google Cloud APIs interactions."""

    def __init__(self, project_id: str) -> None:
        self.service_usage_client = discovery.build(
            serviceName="serviceusage", version="v1"
        )
        self.project_id = project_id

    # pylint: disable=no-member
    def disable_api(self, api_name: str) -> None:
        """
        Disables a specified API for the project.
        """
        try:
            request = self.service_usage_client.services().disable(
                name=f"projects/{self.project_id}/services/{api_name}",
                body={"disable_dependent_services": True},
            )
            response = request.execute()
            GCP_LOGGER.info(msg=f"API '{api_name}' disabled: {response}")
        except Exception as e:
            GCP_LOGGER.error(msg=f"Error disabling API '{api_name}': {e}")
