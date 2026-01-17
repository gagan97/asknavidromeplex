import logging
import os
from typing import Union

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.ui import StandardCard, Image
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective, PlayBehavior, AudioItem, Stream, AudioItemMetadata,
    StopDirective, CaptionData)
from ask_sdk_model.interfaces.audioplayer.caption_type import CaptionType
from ask_sdk_model.interfaces import display

from .track import Track
from .subsonic_api import SubsonicConnection
from .media_queue import MediaQueue

logger = logging.getLogger(__name__)

# App name - configurable via environment variable, defaults to AskNavidromePlex
APP_NAME = os.getenv('SKILL_NAME', 'AskNavidromePlex')

# Default fallback image URL
DEFAULT_ART_URL = 'https://github.com/navidrome/navidrome/raw/master/resources/logo-192x192.png'

#
# Helper Functions
#


def build_metadata_from_track(track_details: Track) -> Union[AudioItemMetadata, None]:
    """Build AudioItemMetadata directly from Track object.

    Used for PlaybackController handlers where we don't have card_data
    but still need to display track info on Echo Show devices.

    :param Track track_details: A Track object with cover art URLs
    :return: An Amazon AudioItemMetadata object or None
    :rtype: AudioItemMetadata | None
    """
    if not track_details:
        return None

    logger.debug('In build_metadata_from_track()')

    art_url = getattr(track_details, 'cover_art_url', None) or DEFAULT_ART_URL
    background_url = getattr(track_details, 'background_url', None) or DEFAULT_ART_URL
    title = getattr(track_details, 'title', '') or 'Unknown Track'
    artist = getattr(track_details, 'artist', '') or 'Unknown Artist'
    album = getattr(track_details, 'album', '') or ''

    # Build subtitle with artist and album info
    subtitle = artist
    if album:
        subtitle = f"{artist} • {album}"

    metadata = AudioItemMetadata(
        title=title,
        subtitle=subtitle,
        art=display.Image(
            content_description=title,
            sources=[
                display.ImageInstance(
                    url=art_url,
                    width_pixels=1024,
                    height_pixels=1024
                )
            ]
        ),
        background_image=display.Image(
            content_description=title,
            sources=[
                display.ImageInstance(
                    url=background_url,
                    width_pixels=1920,
                    height_pixels=1080
                )
            ]
        )
    )

    return metadata


def build_caption_from_track(track_details: Track) -> Union[CaptionData, None]:
    """Build minimal WEBVTT caption payload for automotive/infotainment displays.

    Alexa AudioPlayer supports a single CaptionData object; WEBVTT is the only
    allowed type. We emit a simple, non-timed caption line with Title and
    Artist/Album so head units have something to render even without lyrics.
    """
    if not track_details:
        return None

    title = getattr(track_details, 'title', '') or ''
    artist = getattr(track_details, 'artist', '') or ''
    album = getattr(track_details, 'album', '') or ''

    # If we have nothing meaningful, skip captions
    if not title and not artist:
        return None

    # Single cue covering first 10 minutes (long enough for typical tracks)
    # This is intentionally simple; head units usually just need one line to show.
    caption_line = f"{title}" if title else ''
    if artist:
        caption_line = f"{caption_line} — {artist}" if caption_line else artist
    if album:
        caption_line = f"{caption_line} • {album}" if caption_line else album

    content = (
        "WEBVTT\n\n"
        "00:00.000 --> 10:00.000\n"
        f"{caption_line}\n"
    )

    return CaptionData(content=content, object_type=CaptionType.WEBVTT)


#
# Main Functions
#


def start_playback(mode: str, text: str, card_data: dict, track_details: Track, handler_input: HandlerInput) -> Response:
    """Function to play audio.

    Begin playing audio when:

        - Play Audio Intent is invoked.
        - Resuming audio when stopped / paused.
        - Next / Previous commands issues.

    .. note ::
       - https://developer.amazon.com/docs/custom-skills/audioplayer-interface-reference.html#play
           - REPLACE_ALL: Immediately begin playback of the specified stream,
             and replace current and enqueued streams.

    :param str mode: play | continue - Play immediately or enqueue a track
    :param str text: Text which should be spoken before playback starts (None for PlaybackController)
    :param dict card_data: Data to display on a card (can be None, will build from track_details)
    :param Track track_details: A Track object containing details of the track to use
    :param HandlerInput handler_input: The Amazon Alexa HandlerInput object
    :return: Amazon Alexa Response class
    :rtype: Response
    """

    if mode == 'play':
        # Starting playback
        logger.debug('In start_playback() - play mode')

        # Always build metadata from track details for accurate NowPlaying display
        # This ensures Alexa Auto and other devices show correct track info (title, artist, album art)
        metadata = build_metadata_from_track(track_details)

        # Only set Card when we have speech (text) - PlaybackController cannot have Cards
        if card_data and text:
            # Get art URL from card_data with fallback to default
            art_url = card_data.get('art_url') or DEFAULT_ART_URL
            
            handler_input.response_builder.set_card(
                StandardCard(
                    title=card_data.get('title', APP_NAME),
                    text=card_data.get('text', ''),
                    image=Image(
                        small_image_url=art_url,
                        large_image_url=art_url
                    )
                )
            )

        caption_data = build_caption_from_track(track_details)

        handler_input.response_builder.add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.REPLACE_ALL,
                audio_item=AudioItem(
                    stream=Stream(
                        token=track_details.id,
                        url=track_details.uri,
                        offset_in_milliseconds=track_details.offset,
                        expected_previous_token=None,
                        caption_data=caption_data
                    ),
                    metadata=metadata
                )
            )
        ).set_should_end_session(True)

        if text:
            # Text is not supported if we are continuing an existing play list
            handler_input.response_builder.speak(text)

        logger.debug(f'Track ID: {track_details.id}')
        logger.debug(f'Track Previous ID: {track_details.previous_id}')
        logger.info(f'Playing track: {track_details.title} by: {track_details.artist}')

    elif mode == 'continue':
        # Continuing Playback (ENQUEUE mode)
        logger.debug('In start_playback() - continue mode')

        # Build metadata for enqueued tracks (important for Alexa Auto and NowPlaying cards)
        # This ensures track info is displayed when tracks are queued, not just on first play
        enqueue_metadata = build_metadata_from_track(track_details)

        enqueue_caption = build_caption_from_track(track_details)

        handler_input.response_builder.add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.ENQUEUE,
                audio_item=AudioItem(
                    stream=Stream(
                        token=track_details.id,
                        url=track_details.uri,
                        # Offset is 0 to allow playing of the next track from the beginning
                        # if the Previous intent is used
                        offset_in_milliseconds=0,
                        expected_previous_token=track_details.previous_id,
                        caption_data=enqueue_caption
                    ),
                    metadata=enqueue_metadata
                )
            )
        ).set_should_end_session(True)

        logger.debug(f'Track ID: {track_details.id}')
        logger.debug(f'Track Previous ID: {track_details.previous_id}')
        logger.info(f'Enqueuing track: {track_details.title} by: {track_details.artist}')

    return handler_input.response_builder.response


def stop(handler_input: HandlerInput) -> Response:
    """Stop playback

    :param HandlerInput handler_input: The Amazon Alexa HandlerInput object
    :return: Amazon Alexa Response class
    :rtype: Response
    """
    logger.debug('In stop()')

    handler_input.response_builder.add_directive(StopDirective())

    return handler_input.response_builder.response


def enqueue_songs(api, queue: MediaQueue, song_id_list: list, source: str = 'navidrome') -> None:
    """Enqueue songs

    Add Track objects to the queue deque

    :param api: A SubsonicConnection or PlexConnection object to allow access to the API
    :param MediaQueue queue: A MediaQueue object
    :param list song_id_list: A list of song IDs to enqueue (can be IDs or (id, source) tuples)
    :param str source: Default source if song_id_list contains plain IDs
    :return: None
    """

    for item in song_id_list:
        # Handle both plain IDs and (id, source) tuples
        if isinstance(item, tuple):
            song_id, song_source = item
        else:
            song_id = item
            song_source = source

        song_details = api.get_song_details(song_id, song_source) if hasattr(api, 'get_song_details') else api.get_song_details(song_id)
        song_uri = api.get_song_uri(song_id, song_source) if hasattr(api, 'get_song_uri') else api.get_song_uri(song_id)

        song_data = song_details.get('song', {})

        # Create track object from song details with poster URLs
        new_track = Track(
            id=song_data.get('id'),
            title=song_data.get('title'),
            artist=song_data.get('artist'),
            artist_id=song_data.get('artistId'),
            album=song_data.get('album'),
            album_id=song_data.get('albumId'),
            track_no=song_data.get('track'),
            year=song_data.get('year'),
            genre=song_data.get('genre', ''),
            duration=song_data.get('duration'),
            bitrate=song_data.get('bitRate'),
            uri=song_uri,
            offset=0,
            previous_id=None,
            source=song_source,
            cover_art_url=song_data.get('coverPosterUrl', ''),
            background_url=song_data.get('backgroundUrl', '')
        )

        # Add track object to queue
        queue.add_track(new_track)
