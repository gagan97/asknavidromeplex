import logging
from typing import Union
from difflib import SequenceMatcher


class MediaService:
    """Unified media service that can search across multiple sources"""

    def __init__(self, navidrome_conn=None, plex_conn=None, prefer_high_bitrate: bool = False) -> None:
        """
        :param navidrome_conn: SubsonicConnection instance or None
        :param plex_conn: PlexConnection instance or None
        :param bool prefer_high_bitrate: Whether to prefer higher bitrate tracks
        """

        self.logger = logging.getLogger(__name__)
        self.navidrome = navidrome_conn
        self.plex = plex_conn
        self.prefer_high_bitrate = prefer_high_bitrate

        self.logger.debug('MediaService initialized')

    def ping(self) -> bool:
        """Ping all configured servers"""

        success = True
        if self.navidrome:
            success = success and self.navidrome.ping()
        if self.plex:
            success = success and self.plex.ping()
        return success

    def _fuzzy_match(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings with substring awareness

        Prioritizes substring matches (when s2 is contained in s1) over
        character-level similarity, which works better for short search terms.

        :param str s1: First string (typically the title)
        :param str s2: Second string (typically the search term)
        :return: Similarity ratio (0.0 to 1.0+)
        :rtype: float
        """
        s1_lower = s1.lower().strip()
        s2_lower = s2.lower().strip()
        
        # Exact match
        if s1_lower == s2_lower:
            return 1.0
        
        # Substring match: search term is contained in title
        if s2_lower in s1_lower:
            # Score based on coverage - shorter titles with the term score higher
            coverage = len(s2_lower) / len(s1_lower) if s1_lower else 0
            return 0.7 + (coverage * 0.25)  # Range: 0.7 to 0.95
        
        # Prefix match bonus
        if s1_lower.startswith(s2_lower) or s2_lower.startswith(s1_lower):
            return 0.65
        
        # Fallback to sequence matching for other cases
        return SequenceMatcher(None, s1_lower, s2_lower).ratio()

    def _normalize_string(self, s: str) -> str:
        """Normalize string for better matching

        :param str s: Input string
        :return: Normalized string
        :rtype: str
        """
        # Remove common words and punctuation for better matching
        s = s.lower().strip()
        # Remove 'the' at the start
        if s.startswith('the '):
            s = s[4:]
        return s

    def _select_best_result(self, results: list, term: str, key: str = 'name') -> Union[dict, None]:
        """Select the best matching result using fuzzy matching

        :param list results: List of result dictionaries
        :param str term: Search term
        :param str key: Key to compare against (name, title, etc.)
        :return: Best matching result or None
        :rtype: dict | None
        """
        if not results:
            return None

        normalized_term = self._normalize_string(term)
        best_match = None
        best_score = 0.0

        for result in results:
            value = result.get(key, '') or result.get('title', '') or ''
            normalized_value = self._normalize_string(value)

            # Exact match gets highest priority
            if normalized_value == normalized_term:
                return result

            score = self._fuzzy_match(normalized_value, normalized_term)

            # Boost score for prefix matches
            if normalized_value.startswith(normalized_term) or normalized_term.startswith(normalized_value):
                score += 0.2

            if score > best_score:
                best_score = score
                best_match = result

        # Only return if we have a reasonable match (> 60% similarity)
        if best_score > 0.6:
            return best_match

        return results[0] if results else None

    def _select_highest_bitrate(self, songs: list) -> list:
        """Sort songs by bitrate (highest first) and remove duplicates

        :param list songs: List of song dictionaries
        :return: Sorted list with best quality versions
        :rtype: list
        """
        if not songs or not self.prefer_high_bitrate:
            return songs

        # Group by title + artist to find duplicates
        song_map = {}
        for song in songs:
            key = (self._normalize_string(song.get('title', '')),
                   self._normalize_string(song.get('artist', '')))
            existing = song_map.get(key)
            song_bitrate = song.get('bitRate') or 0
            existing_bitrate = existing.get('bitRate', 0) if existing else 0
            if not existing or song_bitrate > existing_bitrate:
                song_map[key] = song

        return list(song_map.values())

    def search_artist(self, term: str) -> Union[list, None]:
        """Search for an artist across all enabled sources

        :param str term: The name of the artist
        :return: A list of artists or None
        :rtype: list | None
        """

        self.logger.debug(f'Searching for artist: {term}')

        all_results = []

        if self.navidrome:
            result = self.navidrome.search_artist(term)
            if result:
                for r in result:
                    r['source'] = 'navidrome'
                all_results.extend(result)

        if self.plex:
            result = self.plex.search_artist(term)
            if result:
                for r in result:
                    r['source'] = 'plex'
                all_results.extend(result)

        if all_results:
            best = self._select_best_result(all_results, term)
            return [best] if best else all_results[:1]

        return None

    def search_album(self, term: str) -> Union[list, None]:
        """Search for an album across all enabled sources

        :param str term: The name of the album
        :return: A list of albums or None
        :rtype: list | None
        """

        self.logger.debug(f'Searching for album: {term}')

        all_results = []

        if self.navidrome:
            result = self.navidrome.search_album(term)
            if result:
                for r in result:
                    r['source'] = 'navidrome'
                all_results.extend(result)

        if self.plex:
            result = self.plex.search_album(term)
            if result:
                for r in result:
                    r['source'] = 'plex'
                all_results.extend(result)

        if all_results:
            best = self._select_best_result(all_results, term)
            return [best] if best else all_results[:1]

        return None

    def search_song(self, term: str) -> Union[list, None]:
        """Search for a song across all enabled sources

        :param str term: The name of the song
        :return: A list of songs or None
        :rtype: list | None
        """

        self.logger.debug(f'Searching for song: {term}')

        all_results = []

        if self.navidrome:
            result = self.navidrome.search_song(term)
            if result:
                for r in result:
                    r['source'] = 'navidrome'
                all_results.extend(result)

        if self.plex:
            result = self.plex.search_song(term)
            if result:
                for r in result:
                    r['source'] = 'plex'
                all_results.extend(result)

        if all_results:
            # Apply bitrate preference if enabled
            all_results = self._select_highest_bitrate(all_results)

            # Sort by fuzzy match score
            normalized_term = self._normalize_string(term)
            all_results.sort(
                key=lambda x: self._fuzzy_match(
                    self._normalize_string(x.get('title', '')),
                    normalized_term
                ),
                reverse=True
            )

            return all_results

        return None

    def search_song_from_album(self, song_term: str, album_term: str) -> Union[list, None]:
        """Search for a song from a specific album across all enabled sources

        :param str song_term: The name of the song
        :param str album_term: The name of the album
        :return: A list of songs sorted by relevance, or None
        :rtype: list | None
        """

        self.logger.debug(f'Searching for song: {song_term} from album: {album_term}')

        all_results = []

        if self.navidrome and hasattr(self.navidrome, 'search_song_from_album'):
            result = self.navidrome.search_song_from_album(song_term, album_term)
            if result:
                for r in result:
                    r['source'] = 'navidrome'
                all_results.extend(result)

        if self.plex and hasattr(self.plex, 'search_song_from_album'):
            result = self.plex.search_song_from_album(song_term, album_term)
            if result:
                for r in result:
                    r['source'] = 'plex'
                all_results.extend(result)

        if all_results:
            # Apply bitrate preference if enabled
            all_results = self._select_highest_bitrate(all_results)

            # Sort by combined song + album match score
            normalized_song = self._normalize_string(song_term)
            normalized_album = self._normalize_string(album_term)
            
            def combined_score(x):
                title_score = self._fuzzy_match(self._normalize_string(x.get('title', '')), normalized_song)
                album_score = self._fuzzy_match(self._normalize_string(x.get('album', '')), normalized_album)
                # Weight title match more heavily, but album match adds significant bonus
                return title_score + (album_score * 0.5)
            
            all_results.sort(key=combined_score, reverse=True)

            return all_results

        # Fallback: try regular song search if album-specific search failed
        return self.search_song(song_term)

    def search_playlist(self, term: str) -> Union[tuple, None]:
        """Search for a playlist across all enabled sources

        :param str term: The name of the playlist
        :return: Tuple of (playlist_id, source) or None
        :rtype: tuple | None
        """

        self.logger.debug(f'Searching for playlist: {term}')

        if self.navidrome:
            result = self.navidrome.search_playlist(term)
            if result:
                return (result, 'navidrome')

        if self.plex:
            result = self.plex.search_playlist(term)
            if result:
                return (result, 'plex')

        return None

    def get_connection_for_source(self, source: str):
        """Get the appropriate connection for a given source

        :param str source: 'navidrome' or 'plex'
        :return: Connection object
        """
        if source == 'plex':
            return self.plex
        return self.navidrome

    def get_default_connection(self):
        """Get the default/first available connection"""
        return self.navidrome or self.plex

    def albums_by_artist(self, artist_id: str, source: str = 'navidrome') -> list:
        """Get albums for a given artist from the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            return conn.albums_by_artist(artist_id)
        return []

    def build_song_list_from_albums(self, albums: list, length: int, source: str = 'navidrome') -> list:
        """Build song list from albums using the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            return conn.build_song_list_from_albums(albums, length)
        return []

    def build_song_list_from_playlist(self, playlist_id: str, source: str = 'navidrome') -> list:
        """Build song list from playlist using the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            return conn.build_song_list_from_playlist(playlist_id)
        return []

    def build_song_list_from_genre(self, genre: str, count: int) -> Union[list, None]:
        """Build song list from genre across sources"""
        all_songs = []

        if self.navidrome:
            result = self.navidrome.build_song_list_from_genre(genre, count)
            if result:
                all_songs.extend([(sid, 'navidrome') for sid in result])

        if self.plex:
            result = self.plex.build_song_list_from_genre(genre, count)
            if result:
                all_songs.extend([(sid, 'plex') for sid in result])

        return all_songs if all_songs else None

    def build_random_song_list(self, count: int) -> Union[list, None]:
        """Build random song list across sources"""
        all_songs = []

        if self.navidrome:
            result = self.navidrome.build_random_song_list(count)
            if result:
                all_songs.extend([(sid, 'navidrome') for sid in result])

        if self.plex:
            result = self.plex.build_random_song_list(count)
            if result:
                all_songs.extend([(sid, 'plex') for sid in result])

        return all_songs if all_songs else None

    def build_song_list_from_favourites(self) -> Union[list, None]:
        """Build favorite songs list across sources"""
        all_songs = []

        if self.navidrome:
            result = self.navidrome.build_song_list_from_favourites()
            if result:
                all_songs.extend([(sid, 'navidrome') for sid in result])

        if self.plex:
            result = self.plex.build_song_list_from_favourites()
            if result:
                all_songs.extend([(sid, 'plex') for sid in result])

        return all_songs if all_songs else None

    def get_song_details(self, song_id: str, source: str = 'navidrome') -> dict:
        """Get song details from the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            return conn.get_song_details(song_id)
        return {'song': {}}

    def get_song_uri(self, song_id: str, source: str = 'navidrome') -> str:
        """Get song URI from the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            return conn.get_song_uri(song_id)
        return ''

    def get_transcoded_song_uri(self, song_id: str, source: str = 'navidrome', format: str = 'mp3', max_bit_rate: int = 192) -> str:
        """Get transcoded song URI from the specified source

        :param str song_id: Song ID
        :param str source: Media source ('navidrome' or 'plex')
        :param str format: Target format for transcoding (default: 'mp3')
        :param int max_bit_rate: Maximum bit rate in kbps (default: 192)
        :return: Transcoded URI or empty string if not supported
        :rtype: str
        """
        conn = self.get_connection_for_source(source)
        if conn and hasattr(conn, 'get_transcoded_song_uri'):
            return conn.get_transcoded_song_uri(song_id, format, max_bit_rate)
        return ''

    def star_entry(self, song_id: str, mode: str, source: str = 'navidrome') -> None:
        """Star an entry in the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            conn.star_entry(song_id, mode)

    def unstar_entry(self, song_id: str, mode: str, source: str = 'navidrome') -> None:
        """Unstar an entry in the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            conn.unstar_entry(song_id, mode)

    def scrobble(self, track_id: str, time: int, source: str = 'navidrome') -> None:
        """Scrobble a track in the specified source"""
        conn = self.get_connection_for_source(source)
        if conn:
            conn.scrobble(track_id, time)
