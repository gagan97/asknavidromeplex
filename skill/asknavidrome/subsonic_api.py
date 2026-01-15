from hashlib import md5
from typing import Union
import logging
import os
import random
import secrets

import libsonic

# App name - configurable via environment variable, defaults to AskNavidromePlex
APP_NAME = os.getenv('SKILL_NAME', 'AskNavidromePlex')


class SubsonicConnection:
    """Class with methods to interact with Subsonic API compatible media servers
    """

    def __init__(self, server_url: str, user: str, passwd: str, port: int, api_location: str, api_version: str) -> None:
        """
        :param str server_url: The URL of the Subsonic API compatible media server
        :param str user: Username to authenticate against the API
        :param str passwd: Password to authenticate against the API
        :param int port: Port the Subsonic compatible server is listening on
        :param str api_location: Path to the API, this is appended to server_url
        :param str api_version: The version of the Subsonic API that is in use
        :return: None
        """

        self.logger = logging.getLogger(__name__)

        self.server_url = server_url
        self.user = user
        self.passwd = passwd
        self.port = port
        self.api_location = api_location
        self.api_version = api_version

        self.conn = libsonic.Connection(self.server_url,
                                        self.user,
                                        self.passwd,
                                        self.port,
                                        self.api_location,
                                        APP_NAME,
                                        self.api_version,
                                        False)

        self.logger.debug('Connected to Navidrome')

    def ping(self) -> bool:
        """Ping a Subsonic API server

        Verify the connection to a Subsonic compatible API server
        is working

        :return: True if the connection works, False if it does not
        :rtype: bool
        """

        self.logger.debug('In function ping()')
        status = self.conn.ping()

        if status:
            # Success
            self.logger.info('Successfully connected to Navidrome')
        else:
            # Fail
            self.logger.error('Failed to connect to Navidrome')

        return self.conn.ping()

    def scrobble(self, track_id: str, time: int) -> None:
        """Scrobble the given track

        :param str track_id: The ID of the track to scrobble
        :param int time: UNIX timestamp of track play time
        :return: None
        """
        self.logger.debug('In function scrobble()')

        self.conn.scrobble(track_id, True, time)

        return None

    def search_playlist(self, term: str) -> Union[str, None]:
        """Search the media server for the given playlist

        :param str term: The name of the playlist
        :return: The ID of the playlist or None if the playlist is not found
        :rtype: str | None
        """

        self.logger.debug('In function search_playlist()')

        playlist_dict = self.conn.getPlaylists()

        # Search the list of dictionaries for a playlist with a name that matches the search term
        playlist_id_list = [item.get('id') for item in playlist_dict['playlists']['playlist'] if item.get('name').lower() == term.lower()]

        if len(playlist_id_list) == 1:
            # We have matched the playlist return it
            self.logger.debug(f'Found playlist {playlist_id_list[0]}')

            return playlist_id_list[0]

        elif len(playlist_id_list) > 1:
            # More than one result was returned, this should not be possible
            self.logger.error(f'More than one playlist called {term} was found, multiple playlists with the same name are not supported')

            return None

        elif len(playlist_id_list) == 0:
            self.logger.error(f'No playlist matching the name {term} was found!')

            return None

    def search_artist(self, term: str) -> Union[dict, None]:
        """Search the media server for the given artist

        :param str term: The name of the artist
        :return: A dictionary of artists or None if no results are found
        :rtype: dict | None
        """

        self.logger.debug('In function search_artist()')

        result_dict = self.conn.search3(term)

        if len(result_dict['searchResult3']) > 0:
            # Results found
            result_count = len(result_dict['searchResult3']['artist'])

            self.logger.debug(f'Searching artists for term: {term} found {result_count} entries.')

            if result_count > 0:
                # Results were found
                return result_dict['searchResult3']['artist']

        # No results were found
        return None

    def search_album(self, term: str) -> Union[dict, None]:
        """Search the media server for the given album

        :param str term: The name of the album
        :return: A dictionary of albums or None if no results are found
        :rtype: dict | None
        """

        self.logger.debug('In function search_album()')

        result_dict = self.conn.search3(term)

        if len(result_dict['searchResult3']) > 0:
            # Results found
            result_count = len(result_dict['searchResult3']['album'])

            self.logger.debug(f'Searching albums for term: {term} found {result_count} entries.')

            if result_count > 0:
                # Results were found
                return result_dict['searchResult3']['album']

        # No results were found
        return None

    def search_song(self, term: str) -> Union[dict, None]:
        """Search the media server for the given song

        :param str term: The name of the song
        :return: A dictionary of songs or None if no results are found
        :rtype: dict | None
        """

        self.logger.debug('In function search_song()')

        result_dict = self.conn.search3(term)

        if len(result_dict['searchResult3']) > 0:
            # Results found
            result_count = len(result_dict['searchResult3']['song'])

            self.logger.debug(f'Searching songs for term: {term}, found {result_count} entries.')

            if result_count > 0:
                # Results were found
                return result_dict['searchResult3']['song']

        # No results were found
        return None

    def search_song_from_album(self, song_term: str, album_term: str) -> Union[list, None]:
        """Search for a song from a specific album

        This method searches for songs and filters/boosts results that match the album name.

        :param str song_term: The name of the song
        :param str album_term: The name of the album
        :return: A list of songs sorted by relevance (song + album match), or None if no results
        :rtype: list | None
        """

        self.logger.debug(f'In function search_song_from_album() - song: {song_term}, album: {album_term}')

        # First search for the song
        song_results = self.search_song(song_term)

        if not song_results:
            # Try searching for the album first
            album_results = self.search_album(album_term)
            if album_results:
                # Get the first matching album and search within it
                album_id = album_results[0].get('id')
                if album_id:
                    album_songs = self.conn.getAlbum(album_id)
                    if album_songs and 'album' in album_songs and 'song' in album_songs['album']:
                        songs = album_songs['album']['song']
                        # Filter by song name
                        normalized_song = song_term.lower()
                        matching = [s for s in songs if normalized_song in s.get('title', '').lower()]
                        if matching:
                            return matching
            return None

        # Score results with album matching bonus
        normalized_album = album_term.lower()
        scored_results = []

        for song in song_results:
            song_album = song.get('album', '').lower()
            
            # Check if album matches
            album_bonus = 0.0
            if normalized_album in song_album or song_album in normalized_album:
                album_bonus = 1.0  # High bonus for album match
            elif self._fuzzy_album_match(song_album, normalized_album):
                album_bonus = 0.5  # Partial bonus for fuzzy match
            
            scored_results.append((album_bonus, song))

        # Sort by album match score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)

        self.logger.debug(f'Found {len(scored_results)} songs for song: {song_term}, album: {album_term}')

        return [song for score, song in scored_results]

    def _fuzzy_album_match(self, album1: str, album2: str) -> bool:
        """Check if two album names are similar enough

        :param str album1: First album name
        :param str album2: Second album name
        :return: True if albums are similar
        :rtype: bool
        """
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, album1.lower(), album2.lower()).ratio()
        return ratio > 0.6

    def albums_by_artist(self, id: str) -> 'list[dict]':
        """Get the albums for a given artist

        :param str id: The artist ID
        :return: A list of albums
        :rtype: list of dict
        """

        self.logger.debug('In function albums_by_artist()')

        result_dict = self.conn.getArtist(id)
        album_list = result_dict['artist'].get('album')

        # Shuffle the album list to keep generic requests fresh
        random.shuffle(album_list)

        return album_list

    def build_song_list_from_albums(self, albums: 'list[dict]', length: int) -> list:
        """Get a list of songs from given albums

        Build a list of songs from the given albums, keep adding tracks
        until song_count is greater than of equal to length

        :param list[dict] albums: A list of dictionaries containing album information
        :param int length: The minimum number of songs that should be returned, if -1 there is no limit
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function build_song_list_from_albums()')

        song_id_list = []

        if length != -1:
            song_count = 0
            album_id_list = []

            # The list of songs should be limited by length
            for album in albums:
                if song_count < int(length):
                    # We need more songs
                    album_id_list.append(album.get('id'))
                    song_count = song_count + album.get('songCount')
                else:
                    # We have enough songs, stop iterating
                    break
        else:
            # The list of songs should not be limited
            album_id_list = [album.get('id') for album in albums]

        # Get a song listing for each album
        for album_id in album_id_list:
            album_details = self.conn.getAlbum(album_id)

            for song_detail in album_details['album']['song']:
                # Capture the song ID
                song_id_list.append(song_detail.get('id'))

        return song_id_list

    def build_song_list_from_playlist(self, id: str) -> list:
        """Build a list of songs from a given playlist

        :param str id: The playlist ID
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function build_song_list_from_playlist()')

        song_id_list = []
        playlist_details = self.conn.getPlaylist(id)

        song_id_list = [song_detail.get('id') for song_detail in playlist_details.get('playlist').get('entry')]

        return song_id_list

    def build_song_list_from_favourites(self) -> Union[list, None]:
        """Build a shuffled list favourite songs

        :return: A list of song IDs or None if no favourite tracks are found.
        :rtype: list | None
        """

        self.logger.debug('In function build_song_list_from_favourites()')

        favourite_songs = self.conn.getStarred2().get('starred2').get('song')

        if len(favourite_songs) > 0:
            song_id_list = [song.get('id') for song in favourite_songs]

            return song_id_list

        else:
            return None

    def build_song_list_from_genre(self, genre: str, count: int) -> Union[list, None]:
        """Build a shuffled list songs of songs from the given genre.

        :param str genre: The genre, acceptable values are with the getGenres Subsonic API call.
        :param int count: The number of songs to return
        :return: A list of song IDs or None if no tracks are found.
        :rtype: list | None
        """

        self.logger.debug('In function build_song_list_from_genre()')

        # Note the use of title() to capitalise the first letter of each word in the genre
        # without this the genres do not match the strings returned by the API.
        self.logger.debug(f'Searching for {genre.title()} music')
        songs_from_genre = self.conn.getSongsByGenre(genre.title(), count).get('songsByGenre').get('song')

        if len(songs_from_genre) > 0:
            song_id_list = [song.get('id') for song in songs_from_genre]

            return song_id_list

        else:
            return None

    def build_random_song_list(self, count: int) -> Union[list, None]:
        """Build a shuffled list of random songs

        :param int count: The number of songs to return
        :return: A list of song IDs or None if no tracks are found.
        :rtype: list | None
        """

        self.logger.debug('In function build_random_song_list()')
        random_songs = self.conn.getRandomSongs(count).get('randomSongs').get('song')

        if len(random_songs) > 0:
            song_id_list = [song.get('id') for song in random_songs]

            return song_id_list

        else:
            return None

    def get_song_details(self, id: str) -> dict:
        """Get details about a given song ID

        :param str id: A song ID
        :return: A dictionary of details about the given song.
        :rtype: dict
        """

        self.logger.debug('In function get_song_details()')

        song_details = self.conn.getSong(id)

        return song_details

    def get_song_uri(self, id: str) -> str:
        """Create a URI for a given song

        Creates a URI for the song represented by the given ID.  Authentication details are
        embedded in the URI

        :param str id: A song ID
        :return: A properly formatted URI
        :rtype: str
        """

        self.logger.debug('In function get_song_uri()')

        salt = secrets.token_hex(16)
        auth_token = md5(self.passwd.encode() + salt.encode())

        # This creates a multiline f string, uri contains a single line with both
        # f strings.
        uri = (
            f'{self.server_url}:{self.port}{self.api_location}/stream.view?f=json&v={self.api_version}&c={APP_NAME}&u='
            f'{self.user}&s={salt}&t={auth_token.hexdigest()}&id={id}'
        )

        return uri

    def get_transcoded_song_uri(self, id: str, format: str = 'mp3', max_bit_rate: int = 192) -> str:
        """Create a transcoded URI for a given song

        Creates a URI for the song represented by the given ID with transcoding parameters.
        This is useful when the original format (e.g., FLAC) is not playable on certain devices.

        :param str id: A song ID
        :param str format: Target format for transcoding (default: 'mp3')
        :param int max_bit_rate: Maximum bit rate in kbps (default: 192)
        :return: A properly formatted URI with transcoding parameters
        :rtype: str
        """

        self.logger.debug(f'In function get_transcoded_song_uri() - format: {format}, bitrate: {max_bit_rate}')

        salt = secrets.token_hex(16)
        auth_token = md5(self.passwd.encode() + salt.encode())

        uri = (
            f'{self.server_url}:{self.port}{self.api_location}/stream.view?f=json&v={self.api_version}&c={APP_NAME}&u='
            f'{self.user}&s={salt}&t={auth_token.hexdigest()}&id={id}&format={format}&maxBitRate={max_bit_rate}'
        )

        return uri

    def star_entry(self, id: str, mode: str) -> None:
        """Add a star to the given entity

        :param str id: The Navidrome ID of the entity.
        :param str mode: The type of entity, must be song, artist or album
        :return: None.
        """

        # Convert id to list
        id_list = [id]

        if mode == 'song':
            self.conn.star(id_list, None, None)

            return None
        elif mode == 'album':
            self.conn.star(None, id_list, None)

            return None
        elif mode == 'artist':
            self.conn.star(None, None, id_list)

            return None

    def unstar_entry(self, id: str, mode: str) -> None:
        """Remove a star from the given entity

        :param str id: The Navidrome ID of the entity.
        :param str mode: The type of entity, must be song, artist or album
        :return: None.
        """

        # Convert id to list
        id_list = [id]

        if mode == 'song':
            self.conn.unstar(id_list, None, None)

            return None
        elif mode == 'album':
            self.conn.unstar(None, id_list, None)

            return None
        elif mode == 'artist':
            self.conn.unstar(None, None, id_list)

            return None
