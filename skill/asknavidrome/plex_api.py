import logging
import os
import urllib.parse
from typing import Union, Optional, List, Any
from difflib import SequenceMatcher
import requests
import plexapi
from plexapi.server import PlexServer
from plexapi.library import MusicSection
from plexapi.audio import Track as PlexTrack
import plexapi.exceptions





class PlexConnection:
    """Class with methods to interact with Plex Media Server"""

    def __init__(self, server_url: str, token: str, port: int = 32400, prefer_high_bitrate: bool = False) -> None:
        """
        :param str server_url: The URL of the Plex Media Server
        :param str token: Plex authentication token (X-Plex-Token)
        :param int port: Port the Plex server is listening on (default 32400)
        :param bool prefer_high_bitrate: Whether to prefer higher bitrate tracks when multiple matches exist
        :return: None
        """

        self.logger = logging.getLogger(__name__)

        self.server_url = server_url.rstrip('/')
        self.token = token
        self.port = port
        self.base_url = f"{self.server_url}:{self.port}"
        self.headers = {
            'Accept': 'application/json',
            'X-Plex-Token': self.token
        }
        self.prefer_high_bitrate = prefer_high_bitrate
        self._music_library_key = None  # Cache the music library key
        self._music_section: Optional[MusicSection] = None  # Cache the music section object

        # Initialize official PlexServer SDK
        self._plex_sdk: Optional[PlexServer] = None
        try:
            self._plex_sdk = PlexServer(self.server_url, self.token)
            self.logger.debug('Plex SDK (plexapi) initialized successfully')
        except Exception as e:
            self.logger.warning(f'Failed to initialize Plex SDK: {e}')
            self._plex_sdk = None

        self.logger.debug('PlexConnection initialized')

    def ping(self) -> bool:
        """Ping Plex server

        Verify the connection to the Plex server is working

        :return: True if the connection works, False if it does not
        :rtype: bool
        """

        self.logger.debug('In function ping()')

        try:
            response = requests.get(f"{self.base_url}/", headers=self.headers, timeout=10)

            if response.status_code == 200:
                self.logger.info('Successfully connected to Plex')
                return True
            else:
                self.logger.error(f'Failed to connect to Plex: {response.status_code}')
                return False
        except requests.RequestException as e:
            self.logger.error(f'Failed to connect to Plex: {e}')
            return False

    def _get_music_library_key(self) -> Union[str, None]:
        """Get the library key for the music library
        
        This method checks for a MUSIC_SECTION environment variable to get
        the section name, then uses HTTP API to find the matching section.
        If MUSIC_SECTION is not set, it finds the first music library by type.

        :return: The library key or None if not found
        :rtype: str | None
        """

        self.logger.debug('In function _get_music_library_key()')

        # Return cached value if available
        if self._music_library_key:
            return self._music_library_key

        music_section_name = os.getenv('MUSIC_SECTION', '').strip()
        
        try:
            response = requests.get(f"{self.base_url}/library/sections", headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                directories = data.get('MediaContainer', {}).get('Directory', [])
                
                # If MUSIC_SECTION env var is set, look for section by name
                if music_section_name:
                    self.logger.info(f'Looking for music library section by name: {music_section_name}')
                    for directory in directories:
                        if directory.get('title', '').lower() == music_section_name.lower():
                            self._music_library_key = directory.get('key')
                            self.logger.debug(f'Found music library "{directory.get("title")}" with key {self._music_library_key}')
                            return self._music_library_key
                    # Section name not found, log warning and fall through to type-based search
                    self.logger.warning(f'Music section "{music_section_name}" not found, falling back to type-based search')
                
                # Fallback: Find first music library by type
                for directory in directories:
                    if directory.get('type') == 'artist':
                        self._music_library_key = directory.get('key')
                        self.logger.debug(f'Found music library "{directory.get("title")}" with key {self._music_library_key} via HTTP API')
                        return self._music_library_key
                        
        except requests.RequestException as e:
            self.logger.error(f'Error getting music library: {e}')

        return None

    def _get_music_section(self) -> Optional[MusicSection]:
        """Get the MusicSection object from the official plexapi SDK
        
        This method uses the MUSIC_SECTION environment variable to find
        the music library section by name, or falls back to finding the
        first music section available.

        :return: The MusicSection object or None if not found
        :rtype: MusicSection | None
        """

        self.logger.debug('In function _get_music_section()')

        # Return cached value if available
        if self._music_section:
            return self._music_section

        if not self._plex_sdk:
            self.logger.debug('Plex SDK not available, cannot get music section')
            return None

        music_section_name = os.getenv('MUSIC_SECTION', '').strip()
        
        try:
            # If MUSIC_SECTION env var is set, look for section by name
            if music_section_name:
                self.logger.info(f'Looking for music library section by name: {music_section_name}')
                try:
                    section = self._plex_sdk.library.section(music_section_name)
                    if isinstance(section, MusicSection):
                        self._music_section = section
                        self.logger.debug(f'Found music section "{section.title}" with key {section.key}')
                        return self._music_section
                    else:
                        self.logger.warning(f'Section "{music_section_name}" is not a music section')
                except plexapi.exceptions.NotFound:
                    self.logger.warning(f'Music section "{music_section_name}" not found via SDK')
            
            # Fallback: Find first music library by type
            for section in self._plex_sdk.library.sections():
                if isinstance(section, MusicSection):
                    self._music_section = section
                    self.logger.debug(f'Found music section "{section.title}" with key {section.key} via SDK')
                    return self._music_section
                        
        except Exception as e:
            self.logger.error(f'Error getting music section from SDK: {e}')

        return None

    def _fuzzy_match(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings using SequenceMatcher

        :param str s1: First string
        :param str s2: Second string
        :return: Similarity ratio (0.0 to 1.0)
        :rtype: float
        """
        if not s1 or not s2:
            return 0.0
        return SequenceMatcher(None, s1.lower().strip(), s2.lower().strip()).ratio()

    def _normalize_string(self, s: str) -> str:
        """Normalize string for better matching

        :param str s: Input string
        :return: Normalized string
        :rtype: str
        """
        if not s:
            return ""
        s = s.lower().strip()
        # Remove 'the' at the start
        if s.startswith('the '):
            s = s[4:]
        return s

    def _extract_track_hub(self, json_data: dict) -> Union[dict, None]:
        """Extract only the track hub from search results

        :param dict json_data: The JSON data from the search response
        :return: The track hub data or None if not found
        :rtype: dict | None
        """
        if 'MediaContainer' in json_data and 'Hub' in json_data['MediaContainer']:
            hubs = json_data['MediaContainer']['Hub']
            for hub in hubs:
                if hub.get('type') == 'track' or hub.get('hubIdentifier') == 'track':
                    return hub
        return None

    def _extract_all_properties(self,obj: Any, property_paths: List[str]) -> List[str]:
        """
        Extract ALL available properties from an object using multiple possible paths.
        Unlike extract_property which returns the first found value, this returns all unique non-empty values.
        
        Args:
            obj: The object to extract properties from
            property_paths: List of possible property paths to try
            
        Returns:
            List[str]: List of all unique non-empty values found, in order of property_paths priority
        """
        if obj is None:
            return []
        
        found_values = []
        seen = set()  # Track seen values to avoid duplicates
        
        for path in property_paths:
            try:
                value = None
                
                # Handle nested paths with dots
                if '.' in path:
                    parts = path.split('.')
                    current = obj
                    for part in parts:
                        # If current is a list, try to get the first element
                        if isinstance(current, list):
                            if current:
                                current = current[0]
                            else:
                                current = None
                                break
                        if hasattr(current, part):
                            current = getattr(current, part)
                        elif isinstance(current, dict) and part in current:
                            current = current[part]
                        elif hasattr(current, '__getitem__') and not isinstance(current, str):
                            try:
                                current = current[part]
                            except (KeyError, TypeError, IndexError):
                                current = None
                                break
                        else:
                            current = None
                            break
                    value = current
                # Handle direct attribute access
                elif hasattr(obj, path):
                    value = getattr(obj, path)
                # Handle dictionary-style access
                elif isinstance(obj, dict) and path in obj:
                    value = obj[path]
                elif hasattr(obj, '__getitem__') and not isinstance(obj, str):
                    try:
                        if path in obj:
                            value = obj[path]
                    except (KeyError, TypeError):
                        pass
                
                # Add value if it's non-empty and not already seen
                if value and isinstance(value, str) and value.strip():
                    normalized_value = value.strip()
                    if normalized_value.lower() not in seen:
                        seen.add(normalized_value.lower())
                        found_values.append(normalized_value)
                        
            except Exception:
                continue
        
        # Check raw_response if available
        try:
            if hasattr(obj, 'raw_response') and hasattr(obj.raw_response, 'json'):
                json_data = obj.raw_response.json()
                for path in property_paths:
                    if path in json_data and json_data[path]:
                        value = json_data[path]
                        if isinstance(value, str) and value.strip():
                            normalized_value = value.strip()
                            if normalized_value.lower() not in seen:
                                seen.add(normalized_value.lower())
                                found_values.append(normalized_value)
        except Exception:
            pass
        
        return found_values

    def _get_all_track_artists(self,track) -> List[str]:
        """
        Extract ALL available artist names from track metadata.
        Returns all unique artist name values found (originalTitle, grandparentTitle, etc.).
        
        Args:
            track: The track metadata object from Plex API
            
        Returns:
            List[str]: List of all available artist names
        """
        try:
            return self._extract_all_properties(
                track,
                [
                    'original_title',
                    'originalTitle',  # Check originalTitle before grandparentTitle for accurate multi-artist data
                    'grandparent_title',
                    'Media.Artist.tag',
                    'raw_response.json.grandparentTitle',
                    'grandparentTitle',
                    'guid'
                ]
            )
        except Exception as e:
            self.logger.error(f"[ Error extracting track artists: {str(e)}")
            return []
        
    def _get_track_title(self, track) -> str:
        """
        Extract track title from Plex track metadata.
        Returns the first available title value.
        
        Args:
            track: The track metadata object from Plex API
            
        Returns:
            str: The track title or empty string if not found
        """
        try:
            titles = self._extract_all_properties(
                track,
                [
                    'title',
                    'raw_response.json.title'
                ]
            )
            return titles[0] if titles else ""
        except Exception as e:
            self.logger.error(f"Error extracting track title: {str(e)}")
            return ""

    def _get_all_track_albums(self,track) -> List[str]:
        """
        Extract ALL available album names from track metadata.
        Returns all unique album name values found.
        
        Args:
            track: The track metadata object from Plex API
            
        Returns:
            List[str]: List of all available album names
        """
        try:
            return self._extract_all_properties(
                track,
                [
                    'parent_title',
                    'Media.Album.title',
                    'raw_response.json.parentTitle',
                    'parentTitle',
                    'guid'
                ]
            )
        except Exception as e:
            self.logger.error(f"Error extracting album names: {str(e)}")
            return []
        
    def _get_track_media_info(self,track):
        """
        Extract media info (bitrate, codec) from track metadata
        
        Args:
            track: The track metadata object from Plex API
            
        Returns:
            dict: The media info including audioCodec, bitrate, etc.
        """
        try:
            media_info = {
                'audioCodec': self._extract_all_properties(track, [
                    'Media.audioCodec', 
                    'raw_response.json.Media.audioCodec',
                    'Media.0.audioCodec'  # Handle new XML format where Media is a list
                ]),
                'bitrate': self._extract_all_properties(track, [
                    'Media.bitrate', 
                    'raw_response.json.Media.bitrate',
                    'Media.0.bitrate'
                ]),
                'channels': self._extract_all_properties(track, [
                    'Media.audioChannels', 
                    'raw_response.json.Media.audioChannels',
                    'Media.0.audioChannels'
                ]),
                'duration': self._extract_all_properties(track, [
                    'Media.duration', 
                    'raw_response.json.Media.duration',
                    'Media.0.duration'
                ]),
                'container': self._extract_all_properties(track, [
                    'Media.container', 
                    'raw_response.json.Media.container',
                    'Media.0.container'
                ]),
                'ratingKey': self._extract_all_properties(track, [
                    'Track.ratingKey', 
                    'raw_response.json.Track.ratingKey',
                    'Track.0.ratingKey'
                ]),
                'year': self._extract_all_properties(track, [
                    'Track.parentYear', 
                    'raw_response.json.Track.parentYear',
                    'Track.0.parentYear'
                ])
            }
            return media_info
        except Exception as e:
            self.logger.error(f"Error extracting media info: {str(e)}")
            return {
                'audioCodec': None,
                'bitrate': None,
                'channels': None,
                'duration': None,
                'container': None,
                'ratingKey': None,
                'year': None
            }
    
    def _get_track_poster_info(self, track) -> dict:
        """
        Extract poster info from track metadata.
        
        Plex returns multiple Image elements per track (e.g., coverPoster, background).
        This extracts all images into a structured format.
        
        Args:
            track: The track metadata object from Plex API (dict or SDK object)
            
        Returns:
            dict: Contains 'images' list and convenience keys 'coverPoster'/'background'
                  Example: {
                      'images': [{'type': 'coverPoster', 'url': '...'}, {'type': 'background', 'url': '...'}],
                      'coverPoster': '/library/metadata/2054/thumb/1766870285',
                      'background': '/library/metadata/2054/art/1766870285'
                  }
        """
        result = {
            'images': [],
            'coverPoster': None,
            'background': None
        }
        
        try:
            # Extract Image list from track metadata
            images = None
            
            # Try dictionary access first (HTTP API response)
            if isinstance(track, dict):
                images = track.get('Image', [])
            # Try attribute access (SDK object)
            elif hasattr(track, 'Image'):
                images = getattr(track, 'Image', [])
            elif hasattr(track, 'image'):
                images = getattr(track, 'image', [])
            
            # Also check raw_response if available
            if not images:
                try:
                    if hasattr(track, 'raw_response') and hasattr(track.raw_response, 'json'):
                        json_data = track.raw_response.json()
                        images = json_data.get('Image', [])
                except Exception:
                    pass
            
            if not images:
                return result
            
            # Ensure images is a list
            if not isinstance(images, list):
                images = [images]
            
            # Parse each image entry
            for img in images:
                img_type = None
                img_url = None
                
                if isinstance(img, dict):
                    img_type = img.get('type') or img.get('@type')
                    img_url = img.get('url') or img.get('@url')
                elif hasattr(img, 'type') and hasattr(img, 'url'):
                    img_type = getattr(img, 'type', None)
                    img_url = getattr(img, 'url', None)
                
                if img_type and img_url:
                    result['images'].append({'type': img_type, 'url': img_url})
                    
                    # Set convenience keys for common types
                    if img_type == 'coverPoster':
                        result['coverPoster'] = img_url
                    elif img_type == 'background':
                        result['background'] = img_url
            
        except Exception as e:
            self.logger.error(f"Error extracting poster info: {str(e)}")
        
        return result

    def _parse_track_metadata(self, metadata_list: list) -> list:
        """Parse track metadata into a standardized format using helper functions

        :param list metadata_list: List of track metadata from Plex API
        :return: List of standardized track dictionaries
        :rtype: list
        """
        songs = []
        for m in metadata_list:
            # Use helper functions to extract metadata
            title = self._get_track_title(m)
            artists = self._get_all_track_artists(m)
            albums = self._get_all_track_albums(m)
            media_info = self._get_track_media_info(m)
            poster_info = self._get_track_poster_info(m)
            
            # Get primary values (first item from lists)
            artist = artists[0] if artists else ''
            album = albums[0] if albums else ''
            
            # Extract media info values (they come as lists from _extract_all_properties)
            bitrate = media_info.get('bitrate', [])
            bitrate = int(bitrate[0]) if bitrate else 0
            
            audio_codec = media_info.get('audioCodec', [])
            audio_codec = audio_codec[0] if audio_codec else ''
            
            channels = media_info.get('channels', [])
            channels = int(channels[0]) if channels else 0
            
            duration = media_info.get('duration', [])
            duration_ms = int(duration[0]) if duration else 0
            
            year = media_info.get('year', [])
            year = int(year[0]) if year else 0
            
            # Construct full poster URLs for Alexa display
            cover_poster_url = None
            background_url = None
            if poster_info.get('coverPoster'):
                cover_poster_url = f"{self.base_url}{poster_info['coverPoster']}?X-Plex-Token={self.token}"
            if poster_info.get('background'):
                background_url = f"{self.base_url}{poster_info['background']}?X-Plex-Token={self.token}"
            
            # Get ID from direct access (required for API calls)
            track_id = m.get('ratingKey') if isinstance(m, dict) else getattr(m, 'ratingKey', None) or getattr(m, 'rating_key', None)
            artist_id = m.get('grandparentRatingKey') if isinstance(m, dict) else getattr(m, 'grandparentRatingKey', None)
            album_id = m.get('parentRatingKey') if isinstance(m, dict) else getattr(m, 'parentRatingKey', None)
            track_index = m.get('index', 0) if isinstance(m, dict) else getattr(m, 'index', 0)
            
            songs.append({
                'id': track_id,
                'title': title,
                'artist': artist,
                'originalArtist': artists[1] if len(artists) > 1 else '',  # Secondary artist if available
                'artistId': artist_id,
                'album': album,
                'albumId': album_id,
                'duration': duration_ms // 1000 if duration_ms else 0,
                'bitRate': bitrate,
                'audioCodec': audio_codec,
                'audioChannels': channels,
                'track': track_index,
                'year': year,
                'coverPosterUrl': cover_poster_url,
                'backgroundUrl': background_url,
                'allArtists': artists,  # All extracted artists for reference
                'allAlbums': albums,    # All extracted albums for reference
            })
        return songs

    def _perform_hub_search(self, term: str, limit: int = 20) -> list:
        """Perform a hub search (global search across all content)

        :param str term: The search term
        :param int limit: Maximum number of results
        :return: List of track results
        :rtype: list
        """
        self.logger.debug(f'Performing hub search for: {term}')

        try:
            encoded_term = urllib.parse.quote(term)
            response = requests.get(
                f"{self.base_url}/hubs/search?query={encoded_term}&limit={limit}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                track_hub = self._extract_track_hub(data)
                if track_hub and 'Metadata' in track_hub:
                    return self._parse_track_metadata(track_hub['Metadata'])
        except requests.RequestException as e:
            self.logger.error(f'Error in hub search: {e}')

        return []

    def _perform_hub_search_with_section(self, term: str, section_id: str, limit: int = 20) -> list:
        """Perform a hub search scoped to a specific library section

        :param str term: The search term
        :param str section_id: The library section ID to search in
        :param int limit: Maximum number of results
        :return: List of track results
        :rtype: list
        """
        self.logger.debug(f'Performing hub search with section {section_id} for: {term}')

        try:
            encoded_term = urllib.parse.quote(term)
            response = requests.get(
                f"{self.base_url}/hubs/search?query={encoded_term}&sectionId={section_id}&limit={limit}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.debug(f'Hub search with section response data: {data}')
                track_hub = self._extract_track_hub(data)
                if track_hub and 'Metadata' in track_hub:
                    tracks = self._parse_track_metadata(track_hub['Metadata'])
                    self.logger.debug(f'Hub search found {(tracks)} tracks')
                    return tracks
        except requests.RequestException as e:
            self.logger.error(f'Error in hub search with section: {e}')

        return []

    def _perform_direct_library_search(self, term: str, section_id: str, limit: int = 20) -> list:
        """Perform a direct library search using /library/sections/{id}/all endpoint

        This search method queries the library directly with a title filter,
        which can find tracks that hub search might miss.

        :param str term: The search term (track title)
        :param str section_id: The library section ID to search in
        :param int limit: Maximum number of results
        :return: List of track results
        :rtype: list
        """
        self.logger.debug(f'Performing direct library search for: {term}')

        try:
            encoded_term = urllib.parse.quote(term)
            response = requests.get(
                f"{self.base_url}/library/sections/{section_id}/all?title={encoded_term}&type=10&limit={limit}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.debug(f'Direct library search response data: {data}')
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                if metadata:
                    tracks = self._parse_track_metadata(metadata)
                    self.logger.debug(f'Direct library search found {(tracks)} tracks')
                    return tracks
        except requests.RequestException as e:
            self.logger.error(f'Error in direct library search: {e}')

        return []

    def _parse_sdk_track(self, track: PlexTrack) -> dict:
        """Parse a plexapi Track object into our standardized dict format
        
        :param PlexTrack track: The plexapi Track object
        :return: Standardized track dictionary
        :rtype: dict
        """
        try:
            # Extract media info from the track
            bitrate = 0
            audio_codec = ''
            channels = 0
            duration_ms = track.duration or 0
            
            if track.media and len(track.media) > 0:
                media = track.media[0]
                bitrate = getattr(media, 'bitrate', 0) or 0
                audio_codec = getattr(media, 'audioCodec', '') or ''
                channels = getattr(media, 'audioChannels', 0) or 0
            
            # Get artist info - originalTitle is the track artist, grandparentTitle is album artist
            artist = getattr(track, 'originalTitle', None) or getattr(track, 'grandparentTitle', '') or ''
            original_artist = getattr(track, 'grandparentTitle', '') or ''
            
            # Get album info
            album = getattr(track, 'parentTitle', '') or ''
            
            # Build cover art URLs
            cover_poster_url = None
            background_url = None
            if hasattr(track, 'thumb') and track.thumb:
                cover_poster_url = f"{self.base_url}{track.thumb}?X-Plex-Token={self.token}"
            if hasattr(track, 'art') and track.art:
                background_url = f"{self.base_url}{track.art}?X-Plex-Token={self.token}"
            elif hasattr(track, 'grandparentArt') and track.grandparentArt:
                background_url = f"{self.base_url}{track.grandparentArt}?X-Plex-Token={self.token}"
            
            # Build the list of all artists
            all_artists = []
            if artist:
                all_artists.append(artist)
            if original_artist and original_artist != artist:
                all_artists.append(original_artist)
            
            return {
                'id': str(track.ratingKey),
                'title': track.title or '',
                'artist': artist,
                'originalArtist': original_artist if original_artist != artist else '',
                'artistId': str(getattr(track, 'grandparentRatingKey', '')) if hasattr(track, 'grandparentRatingKey') else '',
                'album': album,
                'albumId': str(getattr(track, 'parentRatingKey', '')) if hasattr(track, 'parentRatingKey') else '',
                'duration': duration_ms // 1000 if duration_ms else 0,
                'bitRate': bitrate,
                'audioCodec': audio_codec,
                'audioChannels': channels,
                'track': getattr(track, 'index', 0) or 0,
                'year': getattr(track, 'year', 0) or getattr(track, 'parentYear', 0) or 0,
                'coverPosterUrl': cover_poster_url,
                'backgroundUrl': background_url,
                'allArtists': all_artists,
                'allAlbums': [album] if album else [],
            }
        except Exception as e:
            self.logger.error(f'Error parsing SDK track: {e}')
            return {}

    def _perform_api_client_search(self, term: str, section_id: str, limit: int = 20) -> list:
        """Perform a search using the official plexapi SDK
        
        This search method uses the official plexapi library's MusicSection.searchTracks()
        method which provides more accurate and complete results.
        
        :param str term: The search term
        :param str section_id: The library section ID (used for consistency, but we use cached section)
        :param int limit: Maximum number of results
        :return: List of track results
        :rtype: list
        """
        if not self._plex_sdk:
            self.logger.debug('Plex SDK not available, skipping API client search')
            return []
        
        self.logger.debug(f'Performing SDK search for: {term}')
        
        try:
            # Get the music section using the SDK
            music_section = self._get_music_section()
            if not music_section:
                self.logger.debug('Music section not available, skipping SDK search')
                return []
            
            # Use the MusicSection.searchTracks() method for track-specific search
            # This returns a list of plexapi.audio.Track objects
            tracks = music_section.searchTracks(title=term, maxresults=limit)
            
            self.logger.debug(f'SDK searchTracks found {tracks} tracks')
            
            # Parse the Track objects into our standardized format
            parsed_tracks = []
            for track in tracks:
                parsed_track = self._parse_sdk_track(track)
                if parsed_track and parsed_track.get('id'):
                    parsed_tracks.append(parsed_track)
            
            self.logger.debug(f'SDK search parsed {len(parsed_tracks)} tracks successfully')
            return parsed_tracks
            
        except Exception as e:
            self.logger.error(f'Error in SDK search: {e}')
        
        return []

    def _calculate_match_score(self, track: dict, search_term: str, search_artist: str = None, log_details: bool = False) -> float:
        """Calculate a match score for a track based on title and artist similarity

        :param dict track: Track dictionary
        :param str search_term: The search term (title)
        :param str search_artist: Optional artist name to match
        :param bool log_details: Whether to log detailed scoring information
        :return: Match score (0.0 to 1.0, with bonuses up to ~1.5)
        :rtype: float
        """
        # Title matching
        track_title = self._normalize_string(track.get('title', ''))
        normalized_term = self._normalize_string(search_term)

        # Exact title match gets highest priority
        if track_title == normalized_term:
            score = 1.0
            if log_details:
                self.logger.debug(f'  └─ Title: EXACT MATCH (score: 1.0)')
        else:
            # Check if search term is contained in title (substring match)
            # This is more important than fuzzy similarity for short search terms
            if normalized_term in track_title:
                # Substring match - score based on how much of the title the term covers
                # Longer titles with the term get slightly lower scores than shorter ones
                coverage = len(normalized_term) / len(track_title) if track_title else 0
                score = 0.7 + (coverage * 0.25)  # Range: 0.7 to 0.95 based on coverage
                if log_details:
                    self.logger.debug(f'  └─ Title CONTAINS search term: {score:.3f} (coverage: {coverage:.2f}, "{track_title}" contains "{normalized_term}")')
            else:
                # Fallback to fuzzy match only when no substring match
                score = self._fuzzy_match(track_title, normalized_term)
                if log_details:
                    self.logger.debug(f'  └─ Title fuzzy match: {score:.3f} ("{track_title}" vs "{normalized_term}")')

        # Boost score for prefix matches
        prefix_bonus = 0.0
        if track_title.startswith(normalized_term) or normalized_term.startswith(track_title):
            prefix_bonus = 0.15  # Increased bonus for prefix matches
            score += prefix_bonus
            if log_details:
                self.logger.debug(f'  └─ Prefix match bonus: +{prefix_bonus}')

        # Artist matching bonus (if artist provided)
        artist_bonus = 0.0
        if search_artist:
            normalized_artist = self._normalize_string(search_artist)
            track_artist = self._normalize_string(track.get('artist', ''))
            original_artist = self._normalize_string(track.get('originalArtist', ''))

            # Check both artist and originalArtist fields
            artist_score = max(
                self._fuzzy_match(track_artist, normalized_artist),
                self._fuzzy_match(original_artist, normalized_artist) if original_artist else 0.0
            )

            # Add artist match as a bonus (up to 0.3)
            artist_bonus = artist_score * 0.3
            score += artist_bonus
            if log_details:
                self.logger.debug(f'  └─ Artist match: {artist_score:.3f}, bonus: +{artist_bonus:.3f} ("{track_artist}" vs "{normalized_artist}")')

        # Check if search term appears in artist name (even without explicit artist search)
        # This helps when someone searches for "ranu" and it's in the artist name "Ranu Mondal"
        track_artist = self._normalize_string(track.get('artist', ''))
        original_artist = self._normalize_string(track.get('originalArtist', ''))
        term_in_artist_bonus = 0.0
        if normalized_term in track_artist or normalized_term in original_artist:
            term_in_artist_bonus = 0.25  # Significant bonus for term appearing in artist
            score += term_in_artist_bonus
            if log_details:
                self.logger.debug(f'  └─ Search term found in artist: +{term_in_artist_bonus} ("{normalized_term}" in "{track_artist or original_artist}")')

        # Bitrate bonus when prefer_high_bitrate is enabled
        bitrate_bonus = 0.0
        if self.prefer_high_bitrate:
            bitrate = track.get('bitRate', 0) or 0
            # Normalize bitrate bonus (max ~0.1 bonus for very high bitrates like 1411 kbps)
            if bitrate > 0:
                bitrate_bonus = min(bitrate / 15000, 0.1)
                score += bitrate_bonus
                if log_details:
                    self.logger.debug(f'  └─ Bitrate bonus: +{bitrate_bonus:.3f} ({bitrate} kbps)')

        if log_details:
            self.logger.debug(f'  └─ TOTAL SCORE: {score:.3f}')

        return score

    def _select_best_tracks(self, tracks: list, search_term: str, search_artist: str = None) -> list:
        """Select and sort tracks by match score, handling duplicates based on bitrate preference

        :param list tracks: List of track dictionaries
        :param str search_term: The search term (title)
        :param str search_artist: Optional artist name
        :return: Sorted list of best matching tracks
        :rtype: list
        """
        if not tracks:
            return []

        self.logger.debug('=' * 80)
        self.logger.debug('SCORING ALL TRACKS:')
        self.logger.debug('=' * 80)

        # Calculate scores and attach to tracks
        scored_tracks = []
        for idx, track in enumerate(tracks, 1):
            search_method = track.get('_search_method', 'unknown')
            self.logger.debug(f'\nTrack #{idx} (from {search_method}):')
            self.logger.debug(f'  Title: "{track.get("title", "N/A")}"')
            self.logger.debug(f'  Artist: "{track.get("artist", "N/A")}"')
            self.logger.debug(f'  Album: "{track.get("album", "N/A")}"')
            self.logger.debug(f'  BitRate: {track.get("bitRate", 0)} kbps')
            
            score = self._calculate_match_score(track, search_term, search_artist, log_details=True)
            scored_tracks.append((score, track))

        # Sort by score descending
        scored_tracks.sort(key=lambda x: x[0], reverse=True)

        # If prefer_high_bitrate, deduplicate by title+artist, keeping highest bitrate
        if self.prefer_high_bitrate:
            track_map = {}
            for score, track in scored_tracks:
                key = (
                    self._normalize_string(track.get('title', '')),
                    self._normalize_string(track.get('artist', ''))
                )
                existing = track_map.get(key)
                if not existing:
                    track_map[key] = (score, track)
                else:
                    # Keep the one with higher bitrate (if scores are similar)
                    existing_bitrate = existing[1].get('bitRate', 0) or 0
                    new_bitrate = track.get('bitRate', 0) or 0
                    if new_bitrate > existing_bitrate:
                        self.logger.debug(f'\n  → Replaced duplicate with higher bitrate: {new_bitrate} > {existing_bitrate}')
                        track_map[key] = (score, track)

            scored_tracks = list(track_map.values())
            scored_tracks.sort(key=lambda x: x[0], reverse=True)

        self.logger.debug('\n' + '=' * 80)
        self.logger.debug('FINAL RANKING (top 5):')
        self.logger.debug('=' * 80)
        for idx, (score, track) in enumerate(scored_tracks[:5], 1):
            search_method = track.get('_search_method', 'unknown')
            self.logger.debug(f'#{idx} [Score: {score:.3f}] [{search_method}] "{track.get("title")}" by "{track.get("artist")}"')
        
        if scored_tracks:
            best_score, best_track = scored_tracks[0]
            best_method = best_track.get('_search_method', 'unknown')
            self.logger.debug('\n' + '=' * 80)
            self.logger.debug(f'✓ SELECTED: "{best_track.get("title")}" by "{best_track.get("artist")}"')
            self.logger.debug(f'  Score: {best_score:.3f}')
            self.logger.debug(f'  Method: {best_method}')
            self.logger.debug(f'  BitRate: {best_track.get("bitRate", 0)} kbps')
            self.logger.debug('=' * 80 + '\n')

        return [track for score, track in scored_tracks]

    def _aggregate_search_results(self, term: str, artist: str = None) -> list:
        """Aggregate results from multiple search methods and return best matches

        This method tries multiple search approaches and combines results:
        1. Hub search (global)
        2. Hub search with section ID (scoped to music library)
        3. Direct library search (title-based)
        4. API client search (SDK-based)

        :param str term: The search term
        :param str artist: Optional artist name for better matching
        :return: Aggregated and sorted list of tracks
        :rtype: list
        """
        all_results = []
        seen_ids = set()

        library_key = self._get_music_library_key()

        # Search method 1: Hub search (global)
        # self.logger.debug('Trying hub search...')
        # hub_results = self._perform_hub_search(term)
        # for track in hub_results:
        #     track_id = track.get('id')
        #     if track_id and track_id not in seen_ids:
        #         seen_ids.add(track_id)
        #         track['_search_method'] = 'hub'
        #         all_results.append(track)
        # self.logger.debug(f'Hub search found {len(hub_results)} tracks')

        # Search method 2: Hub search with section ID
        if library_key:
            self.logger.debug('Trying hub search with section ID...')
            hub_section_results = self._perform_hub_search_with_section(term, library_key)
            new_count = 0
            for track in hub_section_results:
                track_id = track.get('id')
                if track_id and track_id not in seen_ids:
                    seen_ids.add(track_id)
                    track['_search_method'] = 'hub_section'
                    all_results.append(track)
                    new_count += 1
            self.logger.debug(f'Hub search with section found {len(hub_section_results)} tracks ({new_count} new)')

        # Search method 3: Direct library search
        # if library_key:
        #     self.logger.debug('Trying direct library search...')
        #     direct_results = self._perform_direct_library_search(term, library_key)
        #     new_count = 0
        #     for track in direct_results:
        #         track_id = track.get('id')
        #         if track_id and track_id not in seen_ids:
        #             seen_ids.add(track_id)
        #             track['_search_method'] = 'direct'
        #             all_results.append(track)
        #             new_count += 1
        #     self.logger.debug(f'Direct library search found {len(direct_results)} tracks ({new_count} new)')

        # Search method 4: Official plexapi SDK-based search
        if library_key and self._plex_sdk:
            self.logger.debug('Trying official plexapi SDK search...')
            api_results = self._perform_api_client_search(term, library_key)
            new_count = 0
            for track in api_results:
                track_id = track.get('id')
                if track_id and track_id not in seen_ids:
                    seen_ids.add(track_id)
                    track['_search_method'] = 'sdk'
                    all_results.append(track)
                    new_count += 1
            self.logger.debug(f'SDK search found {len(api_results)} tracks ({new_count} new)')

        self.logger.debug(f'Total unique tracks from all search methods: {len(all_results)}')

        # Score and sort all results
        return self._select_best_tracks(all_results, term, artist)

    def search_artist(self, term: str) -> Union[list, None]:
        """Search for an artist in Plex

        :param str term: The name of the artist
        :return: A list of artists or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_artist()')

        try:
            encoded_term = urllib.parse.quote(term)
            response = requests.get(
                f"{self.base_url}/hubs/search?query={encoded_term}&limit=10",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                hubs = data.get('MediaContainer', {}).get('Hub', [])

                for hub in hubs:
                    if hub.get('type') == 'artist':
                        metadata = hub.get('Metadata', [])
                        if metadata:
                            artists = [{'id': m.get('ratingKey'), 'name': m.get('title')} for m in metadata]
                            self.logger.debug(f'Found {len(artists)} artists for term: {term}')
                            return artists
        except requests.RequestException as e:
            self.logger.error(f'Error searching artist: {e}')

        return None

    def search_album(self, term: str) -> Union[list, None]:
        """Search for an album in Plex

        :param str term: The name of the album
        :return: A list of albums or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_album()')

        try:
            encoded_term = urllib.parse.quote(term)
            response = requests.get(
                f"{self.base_url}/hubs/search?query={encoded_term}&limit=10",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                hubs = data.get('MediaContainer', {}).get('Hub', [])

                for hub in hubs:
                    if hub.get('type') == 'album':
                        metadata = hub.get('Metadata', [])
                        if metadata:
                            albums = [{
                                'id': m.get('ratingKey'),
                                'name': m.get('title'),
                                'artist': m.get('parentTitle'),
                                'artistId': m.get('parentRatingKey'),
                                'songCount': m.get('leafCount', 0)
                            } for m in metadata]
                            self.logger.debug(f'Found {len(albums)} albums for term: {term}')
                            return albums
        except requests.RequestException as e:
            self.logger.error(f'Error searching album: {e}')

        return None

    def search_song(self, term: str, artist: str = None) -> Union[list, None]:
        """Search for a song in Plex using multiple search methods

        This method aggregates results from:
        - Hub search (global)
        - Hub search with section ID (scoped to music library)
        - Direct library search (title-based)

        Results are scored based on title/artist match and optionally bitrate.

        :param str term: The name of the song
        :param str artist: Optional artist name for better matching
        :return: A list of songs sorted by relevance, or None if no results
        :rtype: list | None
        """

        self.logger.debug(f'In function search_song() - term: {term}, artist: {artist}')

        results = self._aggregate_search_results(term, artist)

        if results:
            self.logger.debug(f'Found {len(results)} songs for term: {term}')
            return results

        return None

    def search_song_simple(self, term: str) -> Union[list, None]:
        """Search for a song using only hub search (original simple method)

        :param str term: The name of the song
        :return: A list of songs or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_song_simple()')

        try:
            encoded_term = urllib.parse.quote(term)
            response = requests.get(
                f"{self.base_url}/hubs/search?query={encoded_term}&limit=20",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                hubs = data.get('MediaContainer', {}).get('Hub', [])

                for hub in hubs:
                    if hub.get('type') == 'track':
                        metadata = hub.get('Metadata', [])
                        if metadata:
                            songs = self._parse_track_metadata(metadata)
                            self.logger.debug(f'Found {len(songs)} songs for term: {term}')
                            return songs
        except requests.RequestException as e:
            self.logger.error(f'Error searching song: {e}')

        return None

    def albums_by_artist(self, artist_id: str) -> list:
        """Get albums for a given artist

        :param str artist_id: The artist rating key
        :return: A list of albums
        :rtype: list
        """

        self.logger.debug('In function albums_by_artist()')

        albums = []
        try:
            response = requests.get(
                f"{self.base_url}/library/metadata/{artist_id}/children",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                albums = [{
                    'id': m.get('ratingKey'),
                    'name': m.get('title'),
                    'songCount': m.get('leafCount', 0)
                } for m in metadata]
        except requests.RequestException as e:
            self.logger.error(f'Error getting albums by artist: {e}')

        return albums

    def get_song_details(self, song_id: str) -> dict:
        """Get details about a given song using helper functions

        :param str song_id: A song rating key
        :return: A dictionary of details about the given song
        :rtype: dict
        """

        self.logger.debug('In function get_song_details()')

        try:
            response = requests.get(
                f"{self.base_url}/library/metadata/{song_id}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [{}])[0]
                
                # Use helper functions to extract metadata
                title = self._get_track_title(metadata)
                artists = self._get_all_track_artists(metadata)
                albums = self._get_all_track_albums(metadata)
                media_info = self._get_track_media_info(metadata)
                poster_info = self._get_track_poster_info(metadata)
                
                # Get primary values
                artist = artists[0] if artists else metadata.get('grandparentTitle', '')
                album = albums[0] if albums else metadata.get('parentTitle', '')
                
                # Extract media info values
                bitrate = media_info.get('bitrate', [])
                bitrate = int(bitrate[0]) if bitrate else 0
                
                duration = media_info.get('duration', [])
                duration_ms = int(duration[0]) if duration else (metadata.get('duration') or 0)
                
                year = media_info.get('year', [])
                year = int(year[0]) if year else metadata.get('year', 0)
                
                # Construct full poster URLs
                cover_poster_url = None
                background_url = None
                if poster_info.get('coverPoster'):
                    cover_poster_url = f"{self.base_url}{poster_info['coverPoster']}?X-Plex-Token={self.token}"
                if poster_info.get('background'):
                    background_url = f"{self.base_url}{poster_info['background']}?X-Plex-Token={self.token}"

                return {
                    'song': {
                        'id': metadata.get('ratingKey'),
                        'title': title or metadata.get('title', ''),
                        'artist': artist,
                        'artistId': metadata.get('grandparentRatingKey'),
                        'album': album,
                        'albumId': metadata.get('parentRatingKey'),
                        'track': metadata.get('index', 0),
                        'year': year,
                        'genre': metadata.get('Genre', [{}])[0].get('tag', '') if metadata.get('Genre') else '',
                        'duration': duration_ms // 1000 if duration_ms else 0,
                        'bitRate': bitrate,
                        'coverPosterUrl': cover_poster_url,
                        'backgroundUrl': background_url,
                        'allArtists': artists,
                        'allAlbums': albums
                    }
                }
        except requests.RequestException as e:
            self.logger.error(f'Error getting song details: {e}')

        return {'song': {}}

    def get_song_uri(self, song_id: str) -> str:
        """Create a URI for a given song

        :param str song_id: A song rating key
        :return: A properly formatted URI
        :rtype: str
        """

        self.logger.debug('In function get_song_uri()')

        try:
            response = requests.get(
                f"{self.base_url}/library/metadata/{song_id}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [{}])[0]
                media = metadata.get('Media', [{}])[0] if metadata.get('Media') else {}
                parts = media.get('Part', [{}])[0] if media.get('Part') else {}
                key = parts.get('key', '')

                if key:
                    return f"{self.base_url}{key}?X-Plex-Token={self.token}"
        except requests.RequestException as e:
            self.logger.error(f'Error getting song URI: {e}')

        return ''

    def build_song_list_from_albums(self, albums: list, length: int) -> list:
        """Get a list of songs from given albums

        :param list albums: A list of albums
        :param int length: Minimum number of songs to return (-1 for no limit)
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function build_song_list_from_albums()')

        song_id_list = []
        song_count = 0

        for album in albums:
            if length != -1 and song_count >= int(length):
                break

            try:
                response = requests.get(
                    f"{self.base_url}/library/metadata/{album.get('id')}/children",
                    headers=self.headers,
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    metadata = data.get('MediaContainer', {}).get('Metadata', [])
                    for track in metadata:
                        song_id_list.append(track.get('ratingKey'))
                        song_count += 1
            except requests.RequestException as e:
                self.logger.error(f'Error getting album tracks: {e}')

        return song_id_list

    def build_song_list_from_playlist(self, playlist_id: str) -> list:
        """Build a list of songs from a playlist

        :param str playlist_id: The playlist rating key
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function build_song_list_from_playlist()')

        song_id_list = []
        try:
            response = requests.get(
                f"{self.base_url}/playlists/{playlist_id}/items",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                song_id_list = [m.get('ratingKey') for m in metadata if m.get('type') == 'track']
        except requests.RequestException as e:
            self.logger.error(f'Error getting playlist tracks: {e}')

        return song_id_list

    def search_playlist(self, term: str) -> Union[str, None]:
        """Search for a playlist by name

        :param str term: The name of the playlist
        :return: The playlist rating key or None
        :rtype: str | None
        """

        self.logger.debug('In function search_playlist()')

        try:
            response = requests.get(
                f"{self.base_url}/playlists",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                for playlist in metadata:
                    if playlist.get('title', '').lower() == term.lower():
                        return playlist.get('ratingKey')
        except requests.RequestException as e:
            self.logger.error(f'Error searching playlist: {e}')

        return None

    def build_random_song_list(self, count: int) -> Union[list, None]:
        """Build a list of random songs

        :param int count: Number of songs to return
        :return: A list of song IDs or None
        :rtype: list | None
        """

        self.logger.debug('In function build_random_song_list()')

        library_key = self._get_music_library_key()
        if not library_key:
            return None

        try:
            response = requests.get(
                f"{self.base_url}/library/sections/{library_key}/all?type=10&sort=random&limit={count}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                if metadata:
                    return [m.get('ratingKey') for m in metadata]
        except requests.RequestException as e:
            self.logger.error(f'Error getting random songs: {e}')

        return None

    def build_song_list_from_genre(self, genre: str, count: int) -> Union[list, None]:
        """Build a list of songs by genre

        :param str genre: The genre name
        :param int count: Number of songs to return
        :return: A list of song IDs or None
        :rtype: list | None
        """

        self.logger.debug('In function build_song_list_from_genre()')

        library_key = self._get_music_library_key()
        if not library_key:
            return None

        try:
            encoded_genre = urllib.parse.quote(genre)
            response = requests.get(
                f"{self.base_url}/library/sections/{library_key}/all?type=10&genre={encoded_genre}&limit={count}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                if metadata:
                    return [m.get('ratingKey') for m in metadata]
        except requests.RequestException as e:
            self.logger.error(f'Error getting songs by genre: {e}')

        return None

    def build_song_list_from_favourites(self) -> Union[list, None]:
        """Build a list of favorite/starred songs

        :return: A list of song IDs or None
        :rtype: list | None
        """

        self.logger.debug('In function build_song_list_from_favourites()')

        library_key = self._get_music_library_key()
        if not library_key:
            return None

        try:
            response = requests.get(
                f"{self.base_url}/library/sections/{library_key}/all?type=10&userRating>=1",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                if metadata:
                    return [m.get('ratingKey') for m in metadata]
        except requests.RequestException as e:
            self.logger.error(f'Error getting favorite songs: {e}')

        return None

    def star_entry(self, song_id: str, mode: str) -> None:
        """Rate/star a song (Plex uses ratings instead of stars)

        :param str song_id: The song rating key
        :param str mode: The type of entity (song, album, artist)
        :return: None
        """

        self.logger.debug('In function star_entry()')

        try:
            requests.put(
                f"{self.base_url}/library/metadata/{song_id}?userRating=10",
                headers=self.headers,
                timeout=10
            )
        except requests.RequestException as e:
            self.logger.error(f'Error starring entry: {e}')

    def unstar_entry(self, song_id: str, mode: str) -> None:
        """Remove rating from a song

        :param str song_id: The song rating key
        :param str mode: The type of entity
        :return: None
        """

        self.logger.debug('In function unstar_entry()')

        try:
            requests.put(
                f"{self.base_url}/library/metadata/{song_id}?userRating=-1",
                headers=self.headers,
                timeout=10
            )
        except requests.RequestException as e:
            self.logger.error(f'Error unstarring entry: {e}')

    def scrobble(self, track_id: str, time: int) -> None:
        """Scrobble/mark as played

        :param str track_id: The track rating key
        :param int time: UNIX timestamp
        :return: None
        """

        self.logger.debug('In function scrobble()')

        try:
            requests.get(
                f"{self.base_url}/:/scrobble?key={track_id}&identifier=com.plexapp.plugins.library",
                headers=self.headers,
                timeout=10
            )
        except requests.RequestException as e:
            self.logger.error(f'Error scrobbling: {e}')
