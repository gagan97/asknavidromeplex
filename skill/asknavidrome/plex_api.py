import logging
import urllib.parse
from typing import Union
from difflib import SequenceMatcher
import requests

# Try to import PlexAPI library for SDK-based search
try:
    from plexapi.server import PlexServer
    import plexapi.exceptions
    PLEXAPI_AVAILABLE = True
except ImportError:
    PLEXAPI_AVAILABLE = False


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

        # Initialize PlexAPI SDK if available
        self._plex_server = None
        self._music_section = None
        if PLEXAPI_AVAILABLE:
            try:
                self._plex_server = PlexServer(
                    baseurl=self.base_url,
                    token=self.token
                )
                self.logger.debug('PlexAPI SDK initialized successfully')
            except Exception as e:
                self.logger.warning(f'Failed to initialize PlexAPI SDK: {e}')
                self._plex_server = None
        else:
            self.logger.debug('PlexAPI SDK not available, skipping SDK-based search')

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

        :return: The library key or None if not found
        :rtype: str | None
        """

        self.logger.debug('In function _get_music_library_key()')

        # Return cached value if available
        if self._music_library_key:
            return self._music_library_key

        try:
            response = requests.get(f"{self.base_url}/library/sections", headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for directory in data.get('MediaContainer', {}).get('Directory', []):
                    if directory.get('type') == 'artist':
                        self._music_library_key = directory.get('key')
                        return self._music_library_key
        except requests.RequestException as e:
            self.logger.error(f'Error getting music library: {e}')

        return None

    def _get_music_section_plexapi(self):
        """Get the music library section using PlexAPI
        
        This method uses the PlexAPI library to get the music section.
        It tries to find a section with type 'artist' (music library).
        
        :return: The music section object or None if not found
        """
        if not self._plex_server:
            return None
            
        # Return cached section if available
        if self._music_section:
            return self._music_section
            
        try:
            # Get all library sections
            sections = self._plex_server.library.sections()
            
            # Find the music section (type = 'artist')
            for section in sections:
                if section.type == 'artist':
                    self._music_section = section
                    self.logger.debug(f'Found music section: {section.title} (ID: {section.key})')
                    return self._music_section
                    
            self.logger.warning('No music library section found')
            return None
            
        except Exception as e:
            self.logger.error(f'Error getting music section via PlexAPI: {e}')
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

    def _parse_track_metadata(self, metadata_list: list) -> list:
        """Parse track metadata into a standardized format

        :param list metadata_list: List of track metadata from Plex API
        :return: List of standardized track dictionaries
        :rtype: list
        """
        songs = []
        for m in metadata_list:
            media = m.get('Media', [{}])[0] if m.get('Media') else {}
            duration_ms = m.get('duration') or 0
            songs.append({
                'id': m.get('ratingKey'),
                'title': m.get('title'),
                'artist': m.get('grandparentTitle'),
                'originalArtist': m.get('originalTitle'),  # Multi-artist info
                'artistId': m.get('grandparentRatingKey'),
                'album': m.get('parentTitle'),
                'albumId': m.get('parentRatingKey'),
                'duration': duration_ms // 1000 if duration_ms else 0,
                'bitRate': media.get('bitrate', 0),
                'audioCodec': media.get('audioCodec', ''),
                'audioChannels': media.get('audioChannels', 0),
                'track': m.get('index', 0),
                'year': m.get('year', 0),
                'genre': m.get('Genre', [{}])[0].get('tag', '') if m.get('Genre') else '',
                'guid': m.get('guid', ''),
                'Guid': m.get('Guid', [])  # Full GUID list for matching
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
                track_hub = self._extract_track_hub(data)
                if track_hub and 'Metadata' in track_hub:
                    return self._parse_track_metadata(track_hub['Metadata'])
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
                metadata = data.get('MediaContainer', {}).get('Metadata', [])
                if metadata:
                    return self._parse_track_metadata(metadata)
        except requests.RequestException as e:
            self.logger.error(f'Error in direct library search: {e}')

        return []

    def _perform_api_client_search(self, term: str, section_id: str, limit: int = 20) -> list:
        """Perform a search using the PlexAPI library
        
        This search method uses the official PlexAPI library which may return
        different results than the direct HTTP-based search methods.
        
        :param str term: The search term
        :param str section_id: The library section ID to search in (not used with PlexAPI approach)
        :param int limit: Maximum number of results
        :return: List of track results
        :rtype: list
        """
        if not self._plex_server:
            self.logger.debug('PlexAPI SDK not available, skipping API client search')
            return []
        
        self.logger.debug(f'Performing API client search for: {term}')
        
        try:
            # Get the music section
            music_section = self._get_music_section_plexapi()
            if not music_section:
                self.logger.debug('Music section not available for API client search')
                return []
            
            # Perform search using PlexAPI's search method
            # The section.search() method searches within that library section
            search_results = music_section.search(title=term, limit=limit)
            
            # Filter to only get track results
            tracks = []
            for result in search_results:
                # Check if this is a track (not an album or artist)
                if hasattr(result, 'type') and result.type == 'track':
                    tracks.append(result)
            
            self.logger.debug(f'API client search found {len(tracks)} raw track objects')
            
            # Convert PlexAPI track objects to our standardized format
            if tracks:
                # Get the raw response data to extract metadata
                # We'll make a direct HTTP call to get the hub search results
                # since PlexAPI's search doesn't give us the same format
                try:
                    encoded_term = urllib.parse.quote(term)
                    response = requests.get(
                        f"{self.base_url}/hubs/search?query={encoded_term}&sectionId={section_id}&limit={limit}",
                        headers=self.headers,
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        json_data = response.json()
                        track_hub = self._extract_track_hub(json_data)
                        
                        if track_hub and 'Metadata' in track_hub:
                            parsed_tracks = self._parse_track_metadata(track_hub['Metadata'])
                            self.logger.debug(f'API client search found {len(parsed_tracks)} tracks')
                            return parsed_tracks
                except Exception as e:
                    self.logger.error(f'Error getting hub search data for API client: {e}')
            
        except Exception as e:
            self.logger.error(f'Error in API client search: {e}')
        
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
            score = self._fuzzy_match(track_title, normalized_term)
            if log_details:
                self.logger.debug(f'  └─ Title fuzzy match: {score:.3f} ("{track_title}" vs "{normalized_term}")')

        # Boost score for prefix matches
        prefix_bonus = 0.0
        if track_title.startswith(normalized_term) or normalized_term.startswith(track_title):
            prefix_bonus = 0.1
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
        self.logger.debug('Trying hub search...')
        hub_results = self._perform_hub_search(term)
        for track in hub_results:
            track_id = track.get('id')
            if track_id and track_id not in seen_ids:
                seen_ids.add(track_id)
                track['_search_method'] = 'hub'
                all_results.append(track)
        self.logger.debug(f'Hub search found {len(hub_results)} tracks')

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
        if library_key:
            self.logger.debug('Trying direct library search...')
            direct_results = self._perform_direct_library_search(term, library_key)
            new_count = 0
            for track in direct_results:
                track_id = track.get('id')
                if track_id and track_id not in seen_ids:
                    seen_ids.add(track_id)
                    track['_search_method'] = 'direct'
                    all_results.append(track)
                    new_count += 1
            self.logger.debug(f'Direct library search found {len(direct_results)} tracks ({new_count} new)')

        # Search method 4: API client search (PlexAPI SDK-based)
        if library_key and PLEXAPI_AVAILABLE and self._plex_server:
            self.logger.debug('Trying API client search (PlexAPI SDK)...')
            api_results = self._perform_api_client_search(term, library_key)
            new_count = 0
            for track in api_results:
                track_id = track.get('id')
                if track_id and track_id not in seen_ids:
                    seen_ids.add(track_id)
                    track['_search_method'] = 'api_client'
                    all_results.append(track)
                    new_count += 1
            self.logger.debug(f'API client search found {len(api_results)} tracks ({new_count} new)')

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
        """Get details about a given song

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
                media = metadata.get('Media', [{}])[0] if metadata.get('Media') else {}
                duration_ms = metadata.get('duration') or 0

                return {
                    'song': {
                        'id': metadata.get('ratingKey'),
                        'title': metadata.get('title'),
                        'artist': metadata.get('grandparentTitle'),
                        'artistId': metadata.get('grandparentRatingKey'),
                        'album': metadata.get('parentTitle'),
                        'albumId': metadata.get('parentRatingKey'),
                        'track': metadata.get('index', 0),
                        'year': metadata.get('year', 0),
                        'genre': metadata.get('Genre', [{}])[0].get('tag', '') if metadata.get('Genre') else '',
                        'duration': duration_ms // 1000 if duration_ms else 0,
                        'bitRate': media.get('bitrate', 0)
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
