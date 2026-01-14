from datetime import datetime
from flask import Flask, render_template
import logging
from multiprocessing import Process
from multiprocessing.managers import BaseManager
import os
import random
import sys

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractRequestInterceptor, AbstractResponseInterceptor
from ask_sdk_core.utils import is_request_type, is_intent_name, get_slot_value_v2, get_intent_name, get_request_type
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from flask_ask_sdk.skill_adapter import SkillAdapter

import asknavidrome.subsonic_api as subsonic_api
import asknavidrome.media_queue as queue
import asknavidrome.controller as controller
from asknavidrome.media_service import MediaService

# Create web service
app = Flask(__name__)

# Create skill object
sb = SkillBuilder()

# Setup Logging
logger = logging.getLogger()  # Create logger
level = logging.getLevelName('DEBUG')
logger.setLevel(level)  # Set logger log level

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(level)
handler.setFormatter(log_formatter)

logger.addHandler(handler)

#
# Get service configuration
#

logger.info('AskNavidrome 1.0 - Multi-source media player!')
logger.debug('Getting configuration from the environment...')

try:
    if 'NAVI_SKILL_ID' in os.environ:
        # Set skill ID, this is available on the Alexa Developer Console
        # if this is not set the web service will respond to any skill.
        sb.skill_id = os.getenv('NAVI_SKILL_ID')

        logger.info(f'Skill ID set to: {sb.skill_id}')

    else:
        raise NameError
except NameError as err:
    logger.error(f'The Alexa skill ID was not found! {err}')
    raise

# Song count configuration (defaults to 50 if not specified)
min_song_count = os.getenv('NAVI_SONG_COUNT', '50')
logger.info(f'Minimum song count is set to: {min_song_count}')

# Feature flags
enable_navidrome = os.getenv('ENABLE_NAVIDROME', '1').lower() in ('1', 'true', 'yes')
enable_plex = os.getenv('ENABLE_PLEX', '0').lower() in ('1', 'true', 'yes')
prefer_high_bitrate = os.getenv('PREFER_HIGH_BITRATE', '0').lower() in ('1', 'true', 'yes')

logger.info(f'Navidrome enabled: {enable_navidrome}')
logger.info(f'Plex enabled: {enable_plex}')
logger.info(f'Prefer high bitrate: {prefer_high_bitrate}')

# At least one source must be enabled
if not enable_navidrome and not enable_plex:
    logger.error('At least one media source must be enabled (ENABLE_NAVIDROME or ENABLE_PLEX)')
    raise RuntimeError('No media source enabled')

# Navidrome configuration
navidrome_connection = None
if enable_navidrome:
    try:
        navidrome_url = os.getenv('NAVI_URL')
        navidrome_user = os.getenv('NAVI_USER')
        navidrome_passwd = os.getenv('NAVI_PASS')
        navidrome_port = os.getenv('NAVI_PORT', '443')
        navidrome_api_location = os.getenv('NAVI_API_PATH', '/rest')
        navidrome_api_version = os.getenv('NAVI_API_VER', '1.16.1')

        if not all([navidrome_url, navidrome_user, navidrome_passwd]):
            raise ValueError('Missing Navidrome configuration')

        logger.info(f'Navidrome URL: {navidrome_url}')
        logger.info(f'Navidrome user: {navidrome_user}')
        logger.info(f'Navidrome port: {navidrome_port}')

        navidrome_connection = subsonic_api.SubsonicConnection(
            navidrome_url,
            navidrome_user,
            navidrome_passwd,
            navidrome_port,
            navidrome_api_location,
            navidrome_api_version
        )
        navidrome_connection.ping()
        logger.info('Successfully connected to Navidrome')
    except Exception as e:
        logger.error(f'Failed to connect to Navidrome: {e}')
        if not enable_plex:
            raise RuntimeError('Could not connect to Navidrome and Plex is not enabled!')

# Plex configuration
plex_connection = None
if enable_plex:
    try:
        from asknavidrome.plex_api import PlexConnection

        plex_url = os.getenv('PLEX_URL')
        plex_token = os.getenv('PLEX_TOKEN')
        plex_port = int(os.getenv('PLEX_PORT', '32400'))

        if not all([plex_url, plex_token]):
            raise ValueError('Missing Plex configuration (PLEX_URL, PLEX_TOKEN)')

        logger.info(f'Plex URL: {plex_url}')
        logger.info(f'Plex port: {plex_port}')

        plex_connection = PlexConnection(plex_url, plex_token, plex_port)
        plex_connection.ping()
        logger.info('Successfully connected to Plex')
    except Exception as e:
        logger.error(f'Failed to connect to Plex: {e}')
        if not navidrome_connection:
            raise RuntimeError('Could not connect to Plex and Navidrome is not available!')

# Create unified media service
media_service = MediaService(
    navidrome_conn=navidrome_connection,
    plex_conn=plex_connection,
    prefer_high_bitrate=prefer_high_bitrate
)

# For backward compatibility, use the connection variable
connection = media_service

logger.debug('Configuration has been successfully loaded')

# Set log level based on config value
navidrome_log_level = int(os.getenv('NAVI_DEBUG', '1'))

if navidrome_log_level == 0:
    logger.setLevel(logging.WARNING)
    logger.warning('Log level set to WARNING')
elif navidrome_log_level == 1:
    logger.setLevel(logging.INFO)
    logger.info('Log level set to INFO')
elif navidrome_log_level == 2:
    logger.setLevel(logging.DEBUG)
    logger.debug('Log level set to DEBUG')
elif navidrome_log_level == 3:
    logger.setLevel(logging.DEBUG)
    logger.debug('Log level set to DEBUG')
else:
    navidrome_log_level = 0
    logger.setLevel(logging.WARNING)
    logger.warning('Log level set to WARNING')

# Create a shareable queue than can be updated by multiple threads to enable larger playlists
# to be returned in the back ground avoiding the Amazon 8 second timeout
BaseManager.register('MediaQueue', queue.MediaQueue)
manager = BaseManager()
manager.start()
play_queue = manager.MediaQueue()
logger.debug('MediaQueue object created...')

# Variable to store the additional thread used to populate large playlists
# this is used to avoid concurrency issues if there is an attempt to load multiple playlists
# at the same time.
backgroundProcess = None

logger.info('AskNavidrome Web Service is ready to start!')


#
# Handler Classes
#

class LaunchRequestHandler(AbstractRequestHandler):
    """Handle LaunchRequest and NavigateHomeIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            is_request_type('LaunchRequest')(handler_input) or
            is_intent_name('AMAZON.NavigateHomeIntent')(handler_input)
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In LaunchRequestHandler')

        connection.ping()
        speech = sanitise_speech_output('Ready!')

        handler_input.response_builder.speak(speech).ask(speech)
        return handler_input.response_builder.response


class CheckAudioInterfaceHandler(AbstractRequestHandler):
    """Check if device supports audio play.

    This can be used as the first handler to be checked, before invoking
    other handlers, thus making the skill respond to unsupported devices
    without doing much processing.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if handler_input.request_envelope.context.system.device:
            # Since skill events won't have device information
            return handler_input.request_envelope.context.system.device.supported_interfaces.audio_player is None
        else:
            return False

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In CheckAudioInterfaceHandler')

        _ = handler_input.attributes_manager.request_attributes['_']
        handler_input.response_builder.speak('This device is not supported').set_should_end_session(True)

        return handler_input.response_builder.response


class SkillEventHandler(AbstractRequestHandler):
    """Close session for skill events or when session ends.

    Handler to handle session end or skill events (SkillEnabled,
    SkillDisabled etc.)
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (handler_input.request_envelope.request.object_type.startswith(
                'AlexaSkillEvent') or
                is_request_type('SessionEndedRequest')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In SkillEventHandler')

        return handler_input.response_builder.response


class HelpHandler(AbstractRequestHandler):
    """Handle HelpIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.HelpIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In HelpHandler')

        text = sanitise_speech_output('AskNavidrome lets you interact with media servers that offer a Subsonic compatible A.P.I.')
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicPlayMusicByArtist(AbstractRequestHandler):
    """Handle NaviSonicPlayMusicByArtist

    Play a selection of songs for the given artist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlayMusicByArtist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlayMusicByArtist')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        # Get the requested artist
        artist = get_slot_value_v2(handler_input, 'artist')

        # Search for an artist
        artist_lookup = connection.search_artist(artist.value)

        if artist_lookup is None:
            text = sanitise_speech_output(f"I couldn't find the artist {artist.value} in the collection.")
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            # Get source from search result
            source = artist_lookup[0].get('source', 'navidrome')

            # Get a list of albums by the artist
            artist_album_lookup = connection.albums_by_artist(artist_lookup[0].get('id'), source)

            # Build a list of songs to play
            song_id_list = connection.build_song_list_from_albums(artist_album_lookup, min_song_count, source)
            play_queue.clear()

            controller.enqueue_songs(connection, play_queue, [song_id_list[0], song_id_list[1]], source)  # When generating the playlist return the first two tracks.
            backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:], source))  # Create a thread to enqueue the remaining tracks
            backgroundProcess.start()  # Start the additional thread

            speech = sanitise_speech_output(f'Playing music by: {artist.value}')
            logger.info(speech)

            card = {'title': 'AskNavidrome',
                    'text': speech
                    }

            play_queue.shuffle()
            track_details = play_queue.get_next_track()
            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicPlayAlbumByArtist(AbstractRequestHandler):
    """Handle NaviSonicPlayAlbumByArtist

    Play a given album by a given artist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlayAlbumByArtist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlayAlbumByArtist')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        # Get variables from intent
        artist = get_slot_value_v2(handler_input, 'artist')
        album = get_slot_value_v2(handler_input, 'album')

        if artist is not None and album is not None:
            # Play album by artist method
            logger.debug(f'Searching for the album {album.value} by {artist.value}')

            # Search for an artist
            artist_lookup = connection.search_artist(artist.value)

            if artist_lookup is None:
                text = sanitise_speech_output(f"I couldn't find the artist {artist.value} in the collection.")
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            else:
                source = artist_lookup[0].get('source', 'navidrome')
                artist_album_lookup = connection.albums_by_artist(artist_lookup[0].get('id'), source)

                # Search the list of dictionaries for the requested album
                # Strings are all converted to lower case to minimise matching errors
                result = [album_result for album_result in artist_album_lookup if album_result.get('name', '').lower() == album.value.lower()]

                if not result:
                    text = sanitise_speech_output(f"I couldn't find an album called {album.value} by {artist.value} in the collection.")
                    handler_input.response_builder.speak(text).ask(text)

                    return handler_input.response_builder.response

                # At this point we have found an album that matches
                song_id_list = connection.build_song_list_from_albums(result, -1, source)
                play_queue.clear()

                # Work around the Amazon / Alexa 8 second timeout.
                controller.enqueue_songs(connection, play_queue, [song_id_list[0], song_id_list[1]], source)  # When generating the playlist return the first two tracks.
                backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:], source))  # Create a thread to enqueue the remaining tracks
                backgroundProcess.start()  # Start the additional thread

                speech = sanitise_speech_output(f'Playing {album.value} by: {artist.value}')
                logger.info(speech)
                card = {'title': 'AskNavidrome',
                        'text': speech
                        }
                track_details = play_queue.get_next_track()

                return controller.start_playback('play', speech, card, track_details, handler_input)

        elif artist is None and album:
            # Play album method
            logger.debug(f'Searching for the album {album.value}')

            result = connection.search_album(album.value)

            if result is None:
                text = sanitise_speech_output(f"I couldn't find the album {album.value} in the collection.")
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            else:
                source = result[0].get('source', 'navidrome')
                song_id_list = connection.build_song_list_from_albums(result, -1, source)
                play_queue.clear()

                # Work around the Amazon / Alexa 8 second timeout.
                controller.enqueue_songs(connection, play_queue, [song_id_list[0], song_id_list[1]], source)  # When generating the playlist return the first two tracks.
                backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:], source))  # Create a thread to enqueue the remaining tracks
                backgroundProcess.start()  # Start the additional thread

                speech = sanitise_speech_output(f'Playing {album.value}')
                logger.info(speech)
                card = {'title': 'AskNavidrome',
                        'text': speech
                        }
                track_details = play_queue.get_next_track()

                return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicPlaySongByArtist(AbstractRequestHandler):
    """Handle the NaviSonicPlaySongByArtist intent

    Play the given song by the given artist if it exists in the
    collection.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlaySongByArtist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicPlaySongByArtist')

        # Get variables from intent
        artist = get_slot_value_v2(handler_input, 'artist')
        song = get_slot_value_v2(handler_input, 'song')

        logger.debug(f'Searching for the song {song.value} by {artist.value}')

        # Search for the artist
        artist_lookup = connection.search_artist(artist.value)

        if artist_lookup is None:
            text = sanitise_speech_output(f"I couldn't find the artist {artist.value} in the collection.")
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            artist_id = artist_lookup[0].get('id')
            source = artist_lookup[0].get('source', 'navidrome')

            # Search for song
            song_list = connection.search_song(song.value)

            if song_list is None:
                text = sanitise_speech_output(f"I couldn't find a song called {song.value} in the collection.")
                handler_input.response_builder.speak(text).ask(text)
                return handler_input.response_builder.response

            # Search for song by given artist.
            matching_songs = [(item.get('id'), item.get('source', 'navidrome'))
                              for item in song_list
                              if item.get('artistId') == artist_id or
                              item.get('artist', '').lower() == artist.value.lower()]

            if not matching_songs:
                text = sanitise_speech_output(f"I couldn't find a song called {song.value} by {artist.value} in the collection.")
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            play_queue.clear()
            # Use the first match's source
            song_source = matching_songs[0][1] if matching_songs else source
            song_ids = [m[0] for m in matching_songs]
            controller.enqueue_songs(connection, play_queue, song_ids, song_source)

            speech = sanitise_speech_output(f'Playing {song.value} by {artist.value}')
            logger.info(speech)
            card = {'title': 'AskNavidrome',
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicPlayPlaylist(AbstractRequestHandler):
    """Handle NaviSonicPlayPlaylist

    Play the given playlist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlayPlaylist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlayPlaylist')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        # Get the requested playlist
        playlist = get_slot_value_v2(handler_input, 'playlist')

        # Search for a playlist (returns tuple of (id, source) or None)
        playlist_result = connection.search_playlist(playlist.value)

        if playlist_result is None:
            text = sanitise_speech_output("I couldn't find the playlist " + str(playlist.value) + ' in the collection.')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            playlist_id, source = playlist_result
            song_id_list = connection.build_song_list_from_playlist(playlist_id, source)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            controller.enqueue_songs(connection, play_queue, [song_id_list[0], song_id_list[1]], source)  # When generating the playlist return the first two tracks.
            backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:], source))  # Create a thread to enqueue the remaining tracks
            backgroundProcess.start()  # Start the additional thread

            speech = sanitise_speech_output('Playing playlist ' + str(playlist.value))
            logger.info(speech)
            card = {'title': 'AskNavidrome',
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicShufflePlaylist(AbstractRequestHandler):
    """Handle NaviSonicShufflePlaylist

    Shuffle and play the given playlist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicShufflePlaylist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicShufflePlaylist')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        # Get the requested playlist
        playlist = get_slot_value_v2(handler_input, 'playlist')

        # Search for a playlist (returns tuple of (id, source) or None)
        playlist_result = connection.search_playlist(playlist.value)

        if playlist_result is None:
            text = sanitise_speech_output("I couldn't find the playlist " + str(playlist.value) + ' in the collection.')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            playlist_id, source = playlist_result
            song_id_list = connection.build_song_list_from_playlist(playlist_id, source)

            if not song_id_list or len(song_id_list) == 0:
                text = sanitise_speech_output("The playlist " + str(playlist.value) + " appears to be empty.")
                handler_input.response_builder.speak(text).ask(text)
                return handler_input.response_builder.response

            # Shuffle the song list
            random.shuffle(song_id_list)

            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            # Handle playlists with fewer than 2 songs
            initial_songs = song_id_list[:2] if len(song_id_list) >= 2 else song_id_list
            remaining_songs = song_id_list[2:] if len(song_id_list) > 2 else []

            controller.enqueue_songs(connection, play_queue, initial_songs, source)
            if remaining_songs:
                backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, remaining_songs, source))
                backgroundProcess.start()

            speech = sanitise_speech_output('Shuffling and playing playlist ' + str(playlist.value))
            logger.info(speech)
            card = {'title': 'AskNavidrome',
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicPlayMusicByGenre(AbstractRequestHandler):
    """ Play songs from the given genre

    50 tracks from the given genre are shuffled and played
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlayMusicByGenre')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlayMusicByGenre')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        # Get the requested genre
        genre = get_slot_value_v2(handler_input, 'genre')

        song_id_list = connection.build_song_list_from_genre(genre.value, min_song_count)

        if song_id_list is None or len(song_id_list) == 0:
            text = sanitise_speech_output(f"I couldn't find any {genre.value} songs in the collection.")
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            random.shuffle(song_id_list)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            # song_id_list contains (id, source) tuples
            controller.enqueue_songs(connection, play_queue, song_id_list[:2])  # When generating the playlist return the first two tracks.
            backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:]))  # Create a thread to enqueue the remaining tracks
            backgroundProcess.start()  # Start the additional thread

            speech = sanitise_speech_output(f'Playing {genre.value} music')
            logger.info(speech)
            card = {'title': 'AskNavidrome',
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicPlayMusicRandom(AbstractRequestHandler):
    """Handle the NaviSonicPlayMusicRandom intent

    Play a random selection of music.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlayMusicRandom')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlayMusicRandom')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        song_id_list = connection.build_random_song_list(min_song_count)

        if song_id_list is None or len(song_id_list) == 0:
            text = sanitise_speech_output("I couldn't find any songs in the collection.")
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            random.shuffle(song_id_list)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            # song_id_list contains (id, source) tuples
            controller.enqueue_songs(connection, play_queue, song_id_list[:2])  # When generating the playlist return the first two tracks.
            backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:]))  # Create a thread to enqueue the remaining tracks
            backgroundProcess.start()  # Start the additional thread

            speech = sanitise_speech_output('Playing random music')
            logger.info(speech)
            card = {'title': 'AskNavidrome',
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicPlayFavouriteSongs(AbstractRequestHandler):
    """Handle the NaviSonicPlayFavouriteSongs intent

    Play all starred / liked songs, songs are automatically shuffled.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlayFavouriteSongs')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlayFavouriteSongs')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        song_id_list = connection.build_song_list_from_favourites()

        if song_id_list is None or len(song_id_list) == 0:
            text = sanitise_speech_output("You don't have any favourite songs in the collection.")
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            random.shuffle(song_id_list)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            # song_id_list contains (id, source) tuples
            controller.enqueue_songs(connection, play_queue, song_id_list[:2])  # When generating the playlist return the first two tracks.
            backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:]))  # Create a thread to enqueue the remaining tracks
            backgroundProcess.start()  # Start the additional thread

            speech = sanitise_speech_output('Playing your favourite tracks.')
            logger.info(speech)
            card = {'title': 'AskNavidrome',
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicRandomiseQueue(AbstractRequestHandler):
    """Handle NaviSonicRandomiseQueue Intent

    Shuffle the current play queue
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicRandomiseQueue')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicRandomiseQueue Handler')

        play_queue.shuffle()
        play_queue.sync()

        return handler_input.response_builder.response


class NaviSonicSongDetails(AbstractRequestHandler):
    """Handle NaviSonicSongDetails Intent

    Returns information on the track that is currently playing
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicSongDetails')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicSongDetails Handler')

        current_track = play_queue.get_current_track()

        title = sanitise_speech_output(current_track.title)
        artist = sanitise_speech_output(current_track.artist)
        album = sanitise_speech_output(current_track.album)

        text = f'This is {title} by {artist}, from the album {album}'
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicStarSong(AbstractRequestHandler):
    """Handle NaviSonicStarSong Intent

    Star / favourite the current song
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicStarSong')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicStarSong Handler')

        current_track = play_queue.get_current_track()

        song_id = current_track.id
        source = getattr(current_track, 'source', 'navidrome')
        connection.star_entry(song_id, 'song', source)

        return handler_input.response_builder.response


class NaviSonicUnstarSong(AbstractRequestHandler):
    """Handle NaviSonicUnstarSong Intent

    Unstar / remove from favourites the current song
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicUnstarSong')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicUnstarSong Handler')

        current_track = play_queue.get_current_track()

        song_id = current_track.id
        source = getattr(current_track, 'source', 'navidrome')
        connection.unstar_entry(song_id, 'song', source)

        return handler_input.response_builder.response


class NaviSonicPlaySong(AbstractRequestHandler):
    """Handle NaviSonicPlaySong Intent

    Play a song by name (without specifying artist)
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicPlaySong')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        global backgroundProcess
        logger.debug('In NaviSonicPlaySong')

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        if backgroundProcess is not None:
            backgroundProcess.terminate()
            backgroundProcess.join()

        # Get the requested song
        song = get_slot_value_v2(handler_input, 'song')

        logger.debug(f'Searching for song: {song.value}')

        # Search for the song
        song_list = connection.search_song(song.value)

        if song_list is None or len(song_list) == 0:
            text = sanitise_speech_output(f"I couldn't find the song {song.value} in the collection.")
            handler_input.response_builder.speak(text).ask(text)
            return handler_input.response_builder.response

        # Get the best match (first result after sorting)
        best_match = song_list[0]
        song_title = best_match.get('title', song.value)
        song_artist = best_match.get('artist', 'Unknown Artist')

        # Build list of song IDs with their sources from search results
        song_id_list = []
        search_song_ids = set()  # Track IDs to avoid duplicates
        for song_item in song_list[:int(min_song_count)]:
            song_id = song_item.get('id')
            source = song_item.get('source', 'navidrome')
            song_id_list.append((song_id, source))
            search_song_ids.add(song_id)

        # If we don't have enough songs, fill up with random songs
        target_count = int(min_song_count)
        if len(song_id_list) < target_count:
            remaining_count = target_count - len(song_id_list)
            logger.debug(f'Search returned {len(song_id_list)} songs, filling remaining {remaining_count} with random songs')

            random_songs = connection.build_random_song_list(remaining_count * 2)  # Request extra to account for duplicates
            if random_songs:
                for random_song in random_songs:
                    if len(song_id_list) >= target_count:
                        break
                    # Handle both tuple and non-tuple formats
                    if isinstance(random_song, tuple):
                        r_id, r_source = random_song
                    else:
                        r_id, r_source = random_song, 'navidrome'

                    # Avoid duplicates
                    if r_id not in search_song_ids:
                        song_id_list.append((r_id, r_source))
                        search_song_ids.add(r_id)

        play_queue.clear()

        # Work around the Amazon / Alexa 8 second timeout.
        # Enqueue first two tracks immediately
        initial_songs = song_id_list[:2] if len(song_id_list) >= 2 else song_id_list
        remaining_songs = song_id_list[2:] if len(song_id_list) > 2 else []

        controller.enqueue_songs(connection, play_queue, initial_songs)
        if remaining_songs:
            backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, remaining_songs))
            backgroundProcess.start()

        speech = sanitise_speech_output(f'Playing {song_title} by {song_artist}')
        logger.info(speech)
        card = {'title': 'AskNavidrome',
                'text': speech
                }
        track_details = play_queue.get_next_track()

        return controller.start_playback('play', speech, card, track_details, handler_input)


class NaviSonicLoopOn(AbstractRequestHandler):
    """Handle NaviSonicLoopOn Intent

    Enable loop mode for the playlist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('NaviSonicLoopOn')(handler_input) or
                is_intent_name('AMAZON.LoopOnIntent')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicLoopOn Handler')

        play_queue.set_playback_mode('loop')
        play_queue.save_original_queue()

        text = sanitise_speech_output('Loop mode enabled')
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicLoopOff(AbstractRequestHandler):
    """Handle NaviSonicLoopOff Intent

    Disable loop mode
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('NaviSonicLoopOff')(handler_input) or
                is_intent_name('AMAZON.LoopOffIntent')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicLoopOff Handler')

        play_queue.set_playback_mode('normal')

        text = sanitise_speech_output('Loop mode disabled')
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicRepeatOn(AbstractRequestHandler):
    """Handle NaviSonicRepeatOn Intent

    Enable repeat one mode (repeat current song)
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('NaviSonicRepeatOn')(handler_input) or
                is_intent_name('AMAZON.RepeatIntent')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicRepeatOn Handler')

        play_queue.set_playback_mode('repeat_one')

        text = sanitise_speech_output('Repeat mode enabled')
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicRepeatOff(AbstractRequestHandler):
    """Handle NaviSonicRepeatOff Intent

    Disable repeat mode
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('NaviSonicRepeatOff')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicRepeatOff Handler')

        play_queue.set_playback_mode('normal')

        text = sanitise_speech_output('Repeat mode disabled')
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicShuffleOn(AbstractRequestHandler):
    """Handle AMAZON.ShuffleOnIntent

    Shuffle the current queue
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.ShuffleOnIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicShuffleOn Handler')

        play_queue.shuffle()
        play_queue.sync()

        text = sanitise_speech_output('Queue shuffled')
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class NaviSonicShuffleOff(AbstractRequestHandler):
    """Handle AMAZON.ShuffleOffIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.ShuffleOffIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicShuffleOff Handler')
        # Shuffle off doesn't really do anything in this context
        return handler_input.response_builder.response


class NaviSonicStartOver(AbstractRequestHandler):
    """Handle AMAZON.StartOverIntent

    Restart the current track from the beginning
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.StartOverIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NaviSonicStartOver Handler')

        current_track = play_queue.get_current_track()
        current_track.offset = 0

        return controller.start_playback('play', None, None, current_track, handler_input)

#
# AudioPlayer Handlers
#


class PlaybackStartedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackStarted Directive received.

    Confirming that the requested audio file began playing.
    Do not send any specific response.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackStarted')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackStartedHandler')
        logger.info('Playback started')

        return handler_input.response_builder.response


class PlaybackStoppedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackStopped Directive received.

    Confirming that the requested audio file stopped playing.
    Do not send any specific response.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackStopped')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackStoppedHandler')

        # store the current offset for later resumption
        play_queue.set_current_track_offset(handler_input.request_envelope.request.offset_in_milliseconds)

        current_track = play_queue.get_current_track()
        logger.debug(f'Stored track offset of: {current_track.offset} ms for {current_track.title}')
        logger.info('Playback stopped')

        return handler_input.response_builder.response


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackNearlyFinished Directive received.

    Replacing queue with the URL again. This should not happen on live streams.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackNearlyFinished')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackNearlyFinishedHandler')
        logger.info('Queuing next track...')
        track_details = play_queue.enqueue_next_track()

        return controller.start_playback('continue', None, None, track_details, handler_input)


class PlaybackFinishedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackFinished Directive received.

    Confirming that the requested audio file completed playing.
    Do not send any specific response.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackFinished')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackFinishedHandler')

        # Generate a timestamp in milliseconds for scrobbling
        timestamp_ms = datetime.now().timestamp()
        current_track = play_queue.get_current_track()
        source = getattr(current_track, 'source', 'navidrome')
        connection.scrobble(current_track.id, timestamp_ms, source)
        play_queue.get_next_track()

        return handler_input.response_builder.response


class PausePlaybackHandler(AbstractRequestHandler):
    """Handler for stopping audio.

    Handles Stop, Cancel and Pause Intents and PauseCommandIssued event.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('AMAZON.StopIntent')(handler_input) or
                is_intent_name('AMAZON.CancelIntent')(handler_input) or
                is_intent_name('AMAZON.PauseIntent')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PausePlaybackHandler')
        play_queue.sync()

        return controller.stop(handler_input)


class ResumePlaybackHandler(AbstractRequestHandler):
    """Handler for resuming audio on different events.

    Handles PlayAudio Intent, Resume Intent.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('AMAZON.ResumeIntent')(handler_input) or
                is_intent_name('PlayAudio')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In ResumePlaybackHandler')

        current_track = play_queue.get_current_track()

        if current_track.offset > 0:
            # There is a paused track, continue
            logger.info('Resuming ' + str(current_track.title))
            logger.info('Offset ' + str(current_track.offset))

            return controller.start_playback('play', None, None, current_track, handler_input)

        elif play_queue.get_queue_count() > 0 and current_track.offset == 0:
            # No paused tracks but tracks in queue
            logger.info('Resuming - There was no paused track, getting next track from queue')
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', None, None, track_details, handler_input)


class NextPlaybackHandler(AbstractRequestHandler):
    """Handle NextIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.NextIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NextPlaybackHandler')

        track_details = play_queue.get_next_track()

        # Set the offset to 0 as we are skipping we want to start at the beginning
        track_details.offset = 0

        return controller.start_playback('play', None, None, track_details, handler_input)


class PreviousPlaybackHandler(AbstractRequestHandler):
    """Handle PreviousIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.PreviousIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PreviousPlaybackHandler')
        track_details = play_queue.get_previous_track()

        # Set the offset to 0 as we are skipping we want to start at the beginning
        track_details.offset = 0

        return controller.start_playback('play', None, None, track_details, handler_input)


class PlaybackFailedEventHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackFailed Directive received.

    Handles playback failures by:
    1. For Navidrome tracks that haven't been transcoded: Try transcoded MP3 stream
    2. For already transcoded tracks or Plex tracks: Skip to the next track
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackFailed')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackFailedHandler')

        current_track = play_queue.get_current_track()
        song_id = current_track.id
        source = getattr(current_track, 'source', 'navidrome')
        transcoded = getattr(current_track, 'transcoded', False)

        # Log failure and track ID
        logger.error(f'Playback Failed: {handler_input.request_envelope.request.error}')
        logger.error(f'Failed playing track with ID: {song_id}')

        # Check if we can try transcoding (only for Navidrome and not already transcoded)
        if source == 'navidrome' and not transcoded:
            logger.info(f'Attempting to play transcoded stream for track: {song_id}')

            # Get transcoded URI
            transcoded_uri = connection.get_transcoded_song_uri(song_id, source)

            if transcoded_uri:
                # Update the current track with transcoded URI
                play_queue.mark_current_track_transcoded(transcoded_uri)
                track_details = play_queue.get_current_track()

                logger.info(f'Playing transcoded track: {track_details.title} by: {track_details.artist}')
                return controller.start_playback('play', None, None, track_details, handler_input)

        # Either not Navidrome, already transcoded, or transcoding failed
        # Skip to the next track
        logger.info('Skipping to next track after playback failure')
        track_details = play_queue.skip_current_track()

        # Check if we have a valid track
        if not track_details.id:
            logger.warning('No more tracks available after playback failure')
            return handler_input.response_builder.response

        return controller.start_playback('play', None, None, track_details, handler_input)


#
# Exception Handers
#


class SystemExceptionHandler(AbstractExceptionHandler):
    """Handle System.ExceptionEncountered

    Handles exceptions and prints error information
    in the log
    """

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return is_request_type('System.ExceptionEncountered')(handler_input)

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        logger.debug('In SystemExceptionHandler')

        # Log the exception
        logger.error(f'System Exception: {exception}')
        logger.error(f'Request Type Was: {get_request_type(handler_input)}')
        error = handler_input.request_envelope.request.to_dict()
        logger.error(f"Details: {error.get('error').get('message')}")

        if get_request_type(handler_input) == 'IntentRequest':
            logger.error(f'Intent Name Was: {get_intent_name(handler_input)}')

        speech = sanitise_speech_output("Sorry, I didn't get that. Can you please say it again!!")
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response


class GeneralExceptionHandler(AbstractExceptionHandler):
    """Handle general exceptions

    Handles exceptions and prints error information
    in the log
    """

    def can_handle(self, handler_input: HandlerInput, exception: Exception) -> bool:
        return True

    def handle(self, handler_input: HandlerInput, exception: Exception) -> Response:
        logger.debug('In GeneralExceptionHandler')

        # Log the exception
        logger.error(f'General Exception: {exception}')
        logger.error(f'Request Type Was: {get_request_type(handler_input)}')

        if get_request_type(handler_input) == 'IntentRequest':
            logger.error(f'Intent Name Was: {get_intent_name(handler_input)}')

        speech = sanitise_speech_output("Sorry, I didn't get that. Can you please say it again!!")
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response


#
# Request Interceptors
#


class LoggingRequestInterceptor(AbstractRequestInterceptor):
    """Intercept all requests

    Intercepts all requests sent to the skill and prints them in the log
    """

    def process(self, handler_input: HandlerInput):
        logger.debug(f'Request received: {handler_input.request_envelope.request}')


class LoggingResponseInterceptor(AbstractResponseInterceptor):
    """Intercept all responses

    Intercepts all responses sent from the skill and prints them in the log
    """

    def process(self, handler_input: HandlerInput, response: Response):
        logger.debug(f'Response sent: {response}')

#
# Functions
#


def sanitise_speech_output(speech_string: str) -> str:
    """Sanitise speech output inline with the SSML standard

    Speech Synthesis Markup Language (SSML) has certain ASCII characters that are
    reserved.  This function replaces them with alternatives.

    :param speech_string: The string to process
    :type speech_string: str
    :return: The processed SSML compliant string
    :rtype: str
    """

    logger.debug('In sanitise_speech_output()')

    if '&' in speech_string:
        speech_string = speech_string.replace('&', 'and')
    if '/' in speech_string:
        speech_string = speech_string.replace('/', 'and')
    if '\\' in speech_string:
        speech_string = speech_string.replace('\\', 'and')
    if '"' in speech_string:
        speech_string = speech_string.replace('"', '')
    if "'" in speech_string:
        speech_string = speech_string.replace("'", "")
    if "<" in speech_string:
        speech_string = speech_string.replace('<', '')
    if ">" in speech_string:
        speech_string = speech_string.replace('>', '')

    return speech_string


def queue_worker_thread(connection: object, play_queue: object, song_id_list: list, source: str = 'navidrome') -> None:
    """Media queue worker

    This function allows media queues to be populated in the background enabling multithreading
    and increasing skill response times.

    :param connection: A MediaService or API connection object
    :type connection: object
    :param play_queue: A MediaQueue object
    :type play_queue: object
    :param song_id_list: A list containing song IDs (or (id, source) tuples)
    :type song_id_list: list
    :param source: Default source for the songs
    :type source: str
    """

    logger.debug('In playlist processing thread!')
    controller.enqueue_songs(connection, play_queue, song_id_list, source)
    play_queue.sync()
    logger.debug('Finished playlist processing!')


# Register Intent Handlers
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(CheckAudioInterfaceHandler())
sb.add_request_handler(SkillEventHandler())
sb.add_request_handler(HelpHandler())
sb.add_request_handler(NaviSonicPlayMusicByArtist())
sb.add_request_handler(NaviSonicPlayAlbumByArtist())
sb.add_request_handler(NaviSonicPlaySongByArtist())
sb.add_request_handler(NaviSonicPlaySong())
sb.add_request_handler(NaviSonicPlayPlaylist())
sb.add_request_handler(NaviSonicShufflePlaylist())
sb.add_request_handler(NaviSonicPlayFavouriteSongs())
sb.add_request_handler(NaviSonicPlayMusicByGenre())
sb.add_request_handler(NaviSonicPlayMusicRandom())
sb.add_request_handler(NaviSonicRandomiseQueue())
sb.add_request_handler(NaviSonicSongDetails())
sb.add_request_handler(NaviSonicStarSong())
sb.add_request_handler(NaviSonicUnstarSong())
sb.add_request_handler(NaviSonicLoopOn())
sb.add_request_handler(NaviSonicLoopOff())
sb.add_request_handler(NaviSonicRepeatOn())
sb.add_request_handler(NaviSonicRepeatOff())
sb.add_request_handler(NaviSonicShuffleOn())
sb.add_request_handler(NaviSonicShuffleOff())
sb.add_request_handler(NaviSonicStartOver())

# Register AutoPlayer Handlers
sb.add_request_handler(PlaybackStartedHandler())
sb.add_request_handler(PlaybackStoppedHandler())
sb.add_request_handler(PlaybackNearlyFinishedHandler())
sb.add_request_handler(PlaybackFinishedHandler())
sb.add_request_handler(PausePlaybackHandler())
sb.add_request_handler(NextPlaybackHandler())
sb.add_request_handler(PreviousPlaybackHandler())
sb.add_request_handler(ResumePlaybackHandler())
sb.add_request_handler(PlaybackFailedEventHandler())


# Register Exception Handlers
sb.add_exception_handler(SystemExceptionHandler())
sb.add_exception_handler(GeneralExceptionHandler())

if navidrome_log_level >= 2:
    # Register Interceptors (log all requests)
    sb.add_global_request_interceptor(LoggingRequestInterceptor())
    sb.add_global_response_interceptor(LoggingResponseInterceptor())

sa = SkillAdapter(skill=sb.create(), skill_id='test', app=app)
sa.register(app=app, route='/')

# Enable queue and history diagnostics
if navidrome_log_level == 3:
    logger.warning('AskNavidrome debugging has been enabled, this should only be used when testing!')
    logger.warning('The /buffer, /queue and /history http endpoints are available publicly!')

    @app.route('/queue')
    def view_queue():
        """View the contents of play_queue.queue

        Creates a tabulated page containing the contents of the play_queue.queue deque.
        """

        current_track = play_queue.get_current_track()

        return render_template('table.html', title='AskNavidrome - Queued Tracks',
                               tracks=play_queue.get_current_queue(), current=current_track)

    @app.route('/history')
    def view_history():
        """View the contents of play_queue.history

        Creates a tabulated page containing the contents of the play_queue.history deque.
        """

        current_track = play_queue.get_current_track()

        return render_template('table.html', title='AskNavidrome - Track History',
                               tracks=play_queue.get_history(), current=current_track)

    @app.route('/buffer')
    def view_buffer():
        """View the contents of play_queue.buffer

        Creates a tabulated page containing the contents of the play_queue.buffer deque.
        """

        current_track = play_queue.get_current_track()

        return render_template('table.html', title='AskNavidrome - Buffered Tracks',
                               tracks=play_queue.get_buffer(), current=current_track)


# Run web app by default when file is executed.
if __name__ == '__main__':
    # Start the web service
    app.run(host='0.0.0.0')
