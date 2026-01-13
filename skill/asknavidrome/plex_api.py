import logging
import urllib.parse
from typing import Union
import requests


class PlexConnection:
    """Class with methods to interact with Plex Media Server"""

    def __init__(self, server_url: str, token: str, port: int = 32400) -> None:
        """
        :param str server_url: The URL of the Plex Media Server
        :param str token: Plex authentication token (X-Plex-Token)
        :param int port: Port the Plex server is listening on (default 32400)
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

        try:
            response = requests.get(f"{self.base_url}/library/sections", headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for directory in data.get('MediaContainer', {}).get('Directory', []):
                    if directory.get('type') == 'artist':
                        return directory.get('key')
        except requests.RequestException as e:
            self.logger.error(f'Error getting music library: {e}')

        return None

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

    def search_song(self, term: str) -> Union[list, None]:
        """Search for a song in Plex

        :param str term: The name of the song
        :return: A list of songs or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_song()')

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
                            songs = []
                            for m in metadata:
                                media = m.get('Media', [{}])[0] if m.get('Media') else {}
                                songs.append({
                                    'id': m.get('ratingKey'),
                                    'title': m.get('title'),
                                    'artist': m.get('grandparentTitle'),
                                    'artistId': m.get('grandparentRatingKey'),
                                    'album': m.get('parentTitle'),
                                    'albumId': m.get('parentRatingKey'),
                                    'duration': m.get('duration', 0) // 1000,
                                    'bitRate': media.get('bitrate', 0),
                                    'track': m.get('index', 0),
                                    'year': m.get('year', 0),
                                    'genre': m.get('Genre', [{}])[0].get('tag', '') if m.get('Genre') else ''
                                })
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
                        'duration': metadata.get('duration', 0) // 1000,
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
