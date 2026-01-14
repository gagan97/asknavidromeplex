"""Main PlexAPI client class"""

import logging
from .search import Search


class PlexAPI:
    """Main Plex API SDK client

    Provides access to various Plex API endpoints through specialized service objects.
    """

    def __init__(self, access_token: str, server_url: str, timeout: int = 10):
        """Initialize Plex API client

        :param str access_token: Plex authentication token
        :param str server_url: Full server URL including port (e.g., http://localhost:32400)
        :param int timeout: Request timeout in seconds
        """
        self.logger = logging.getLogger(__name__)
        self.access_token = access_token
        self.server_url = server_url.rstrip('/')
        self.timeout = timeout

        # Initialize service objects
        self.search = Search(self)

        self.logger.debug(f'PlexAPI initialized for server: {self.server_url}')

    def get_headers(self) -> dict:
        """Get common headers for API requests

        :return: Dictionary of HTTP headers
        :rtype: dict
        """
        return {
            'Accept': 'application/json',
            'X-Plex-Token': self.access_token
        }
