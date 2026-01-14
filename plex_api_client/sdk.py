"""Plex API SDK Core Module"""

import logging
from .search import SearchAPI


class PlexAPI:
    """Main Plex API client class
    
    Provides a high-level interface to the Plex Media Server API.
    """
    
    def __init__(self, access_token: str, server_url: str):
        """Initialize the Plex API client
        
        :param str access_token: Plex authentication token (X-Plex-Token)
        :param str server_url: Full URL of the Plex server (including port)
        """
        self.logger = logging.getLogger(__name__)
        self.access_token = access_token
        self.server_url = server_url.rstrip('/')
        
        # Initialize sub-APIs
        self.search = SearchAPI(self.server_url, self.access_token)
        
        self.logger.debug(f'PlexAPI initialized with server: {self.server_url}')
