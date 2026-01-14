"""Plex API Search Module"""

import logging
import urllib.parse
import requests
from .models import SearchResponse


class SearchAPI:
    """Search API for Plex Media Server"""
    
    def __init__(self, server_url: str, access_token: str):
        """Initialize the Search API
        
        :param str server_url: Base URL of the Plex server
        :param str access_token: Plex authentication token
        """
        self.logger = logging.getLogger(__name__)
        self.server_url = server_url
        self.access_token = access_token
        self.headers = {
            'Accept': 'application/json',
            'X-Plex-Token': self.access_token
        }
    
    def perform_search(self, query: str, section_id: int = None, limit: int = 20) -> SearchResponse:
        """Perform a search on the Plex server
        
        :param str query: The search query
        :param int section_id: Optional library section ID to scope the search
        :param int limit: Maximum number of results to return
        :return: SearchResponse object containing the results
        :rtype: SearchResponse
        """
        self.logger.debug(f'Performing search for: {query} (section_id: {section_id}, limit: {limit})')
        
        try:
            encoded_query = urllib.parse.quote(query)
            
            # Build URL with section_id if provided
            if section_id is not None:
                url = f"{self.server_url}/hubs/search?query={encoded_query}&sectionId={section_id}&limit={limit}"
            else:
                url = f"{self.server_url}/hubs/search?query={encoded_query}&limit={limit}"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                self.logger.debug(f'Search successful, status code: {response.status_code}')
                return SearchResponse(response)
            else:
                self.logger.warning(f'Search failed with status code: {response.status_code}')
                return SearchResponse(None)
                
        except requests.RequestException as e:
            self.logger.error(f'Search request failed: {e}')
            return SearchResponse(None)
