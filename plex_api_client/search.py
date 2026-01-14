"""Search functionality for Plex API SDK"""

import logging
import urllib.parse
import requests
from typing import Optional


class SearchResponse:
    """Response object for search operations"""

    def __init__(self, raw_response: requests.Response):
        """Initialize search response

        :param requests.Response raw_response: The raw HTTP response
        """
        self.raw_response = raw_response
        self.status_code = raw_response.status_code

    def is_success(self) -> bool:
        """Check if the search was successful

        :return: True if successful
        :rtype: bool
        """
        return 200 <= self.status_code < 300


class Search:
    """Search service for Plex API

    Provides methods to search for content in Plex libraries.
    """

    def __init__(self, client):
        """Initialize search service

        :param PlexAPI client: The parent PlexAPI client instance
        """
        self.client = client
        self.logger = logging.getLogger(__name__)

    def perform_search(
        self,
        query: str,
        section_id: Optional[int] = None,
        limit: int = 20
    ) -> SearchResponse:
        """Perform a search using the Plex hub search API

        This method uses the /hubs/search endpoint with optional section filtering.

        :param str query: The search query string
        :param int section_id: Optional library section ID to limit search scope
        :param int limit: Maximum number of results to return
        :return: Search response object
        :rtype: SearchResponse
        """
        self.logger.debug(f'SDK search: query="{query}", section_id={section_id}, limit={limit}')

        try:
            # Build the search URL
            encoded_query = urllib.parse.quote(query)
            url = f"{self.client.server_url}/hubs/search?query={encoded_query}&limit={limit}"

            # Add section ID if provided
            if section_id is not None:
                url += f"&sectionId={section_id}"

            # Make the request
            response = requests.get(
                url,
                headers=self.client.get_headers(),
                timeout=self.client.timeout
            )

            self.logger.debug(f'SDK search response: status={response.status_code}')

            return SearchResponse(response)

        except requests.RequestException as e:
            self.logger.error(f'SDK search request failed: {e}')
            # Return a failed response

            class FailedResponse:
                status_code = 500
                raw_response = None

                def json(self):
                    return {}

            failed = FailedResponse()
            return SearchResponse(failed)
