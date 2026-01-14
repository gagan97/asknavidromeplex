"""Plex API Models"""

import logging


class SearchResponse:
    """Wrapper for search response from Plex API"""
    
    def __init__(self, raw_response):
        """Initialize search response
        
        :param raw_response: The raw requests.Response object or None
        """
        self.logger = logging.getLogger(__name__)
        self.raw_response = raw_response
        
    def __bool__(self):
        """Check if response is valid"""
        return self.raw_response is not None and self.raw_response.status_code == 200
    
    def json(self):
        """Get JSON data from response"""
        if self.raw_response:
            return self.raw_response.json()
        return {}


__all__ = ['SearchResponse']
