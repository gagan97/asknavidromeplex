from collections import deque
from copy import deepcopy
import logging
import random

from .track import Track


class MediaQueue:
    """ The MediaQueue class

    This class provides a queue based on a Python deque.  This is used to store
    the tracks in the current play queue
    """

    # Playback mode constants
    MODE_NORMAL = 'normal'
    MODE_REPEAT_ONE = 'repeat_one'
    MODE_LOOP = 'loop'

    def __init__(self) -> None:
        """
        :return: None
        """

        self.logger = logging.getLogger(__name__)
        """Logger"""

        self.queue: deque = deque()
        """Deque containing tracks still to be played"""

        self.history: deque = deque()
        """Deque to hold tracks that have already been played"""

        self.buffer: deque = deque()
        """Deque to contain the list of tracks to be enqueued

        This deque is created from self.queue when actions such as next or
        previous are performed.  This is because Amazon can send the
        PlaybackNearlyFinished request early.  Without self.buffer, this would
        change self.current_track causing us to lose the real position of the
        queue.
        """

        self.current_track: Track = Track()
        """Property to hold the current track object"""

        self.playback_mode: str = self.MODE_NORMAL
        """Playback mode: normal, repeat_one, or loop"""

        self.original_queue: deque = deque()
        """Original queue for loop mode"""

    def get_current_track(self) -> Track:
        """Method to return current_track attribute

        Added to allow access to the current_track object while using BaseManager
        for multi threading, as BaseManager does not allow access to class
        attributes / properties

        :return: A Track object representing the current playing audio track
        :rtype: Track
        """
        return self.current_track

    def set_current_track_offset(self, offset: int) -> None:
        """Method to set the offset of the current track in milliseconds

        Set the offset for the current track in milliseconds.  This is used
        when resuming a paused track to ensure the track isn't played from
        the beginning again.

        :param offset: The track offset in milliseconds
        :type offset: int
        """

        self.current_track.offset = offset

    def get_current_queue(self) -> deque:
        """Get the current queue

        Returns a deque containing the current queue of music to be played

        :return: The current queue
        :rtype: deque
        """

        return self.queue

    def get_buffer(self) -> deque:
        """Get the buffer

        Returns a deque containing the current buffer

        :return: The current buffer
        :rtype: deque
        """

        return self.buffer

    def get_history(self) -> deque:
        """Get history

        Returns a deque of tracks that have already been played

        :return: A deque container tracks that have already been played
        :rtype: deque
        """

        return self.history

    def add_track(self, track: Track) -> None:
        """Add tracks to the queue

        Adds a track to the queue if it is not a duplicate.
        A track is considered a duplicate if another track with the same
        title, artist, and album already exists in the queue.

        :param Track track: A Track object containing details of the track to be played
        :return: None
        """

        self.logger.debug('In add_track()')

        # Check for duplicates by comparing title, artist, and album
        if self._is_duplicate(track):
            self.logger.debug(f'Skipping duplicate track: {track.title} by {track.artist}')
            return

        if not self.queue:
            # This is the first track in the queue
            self.queue.append(track)
        else:
            # There are already tracks in the queue, ensure previous_id is set

            # Get the last track from the deque
            prev_track = self.queue.pop()

            # Set the previous_id attribute
            track.previous_id = prev_track.id

            # Return the previous track to the deque
            self.queue.append(prev_track)

            # Add the new track to the deque
            self.queue.append(track)

        self.logger.debug(f'In add_track() - there are {len(self.queue)} tracks in the queue')

    def _is_duplicate(self, track: Track) -> bool:
        """Check if a track is a duplicate of any track in the queue

        A track is considered a duplicate if another track with the same
        title, artist, and album already exists in the queue.

        :param Track track: The track to check for duplicates
        :return: True if the track is a duplicate, False otherwise
        :rtype: bool
        """
        # Normalize strings for comparison (case-insensitive, stripped)
        track_title = (track.title or '').lower().strip()
        track_artist = (track.artist or '').lower().strip()
        track_album = (track.album or '').lower().strip()

        for existing_track in self.queue:
            existing_title = (existing_track.title or '').lower().strip()
            existing_artist = (existing_track.artist or '').lower().strip()
            existing_album = (existing_track.album or '').lower().strip()

            if (track_title == existing_title and
                track_artist == existing_artist and
                track_album == existing_album):
                return True

        return False

    def shuffle(self) -> None:
        """Shuffle the queue

        Shuffles the queue and resets the previous track IDs required for the ENQUEUE PlayBehaviour

        :return: None
        """

        self.logger.debug('In shuffle()')

        # Copy the original queue
        orig = self.queue
        new_queue = deque()

        # Randomise the queue
        random.shuffle(orig)

        track_id = None

        for t in orig:
            if not new_queue:
                # This is the first track, get the ID and add it
                track_id = t.id
                new_queue.append(t)
            else:
                # Set the tracks previous_id
                t.previous_id = track_id

                # Get the track ID to use as the next previous_id
                track_id = t.id

                # Add the track to the queue
                new_queue.append(t)

        # Replace the original queue with the new shuffled one
        self.queue = new_queue

    def get_next_track(self) -> Track:
        """Get the next track

        Get the next track from self.queue and add it to the history deque.
        Handles repeat_one and loop playback modes.

        :return: The next track object
        :rtype: Track
        """

        self.logger.debug('In get_next_track()')

        # Handle repeat_one mode - return the same track
        if self.playback_mode == self.MODE_REPEAT_ONE and self.current_track.id:
            self.current_track.offset = 0
            return self.current_track

        # Check if queue is empty
        if len(self.queue) == 0:
            # Handle loop mode - restore original queue
            if self.playback_mode == self.MODE_LOOP and len(self.original_queue) > 0:
                self.logger.debug('Loop mode: restoring original queue')
                # Filter out tracks that have previously failed, then deep-copy
                self.queue = deque(
                    deepcopy(track) for track in self.original_queue
                    if not getattr(track, "playback_failed", False)
                )
                self.history.clear()
            else:
                # No more tracks
                return self.current_track

        if self.current_track.id == '' or self.current_track.id is None:
            # This is the first track
            self.current_track = self.queue.popleft()
        else:
            # This is not the first track
            self.history.append(self.current_track)
            self.current_track = self.queue.popleft()

        # Set the buffer to match the queue
        self.sync()

        return self.current_track

    def get_previous_track(self) -> Track:
        """Get the previous track

        Get the last track added to the history deque and
        add it to the front of the play queue

        :return: The previous track object
        :rtype: Track
        """

        self.logger.debug('In get_previous_track()')

        # Return the current track to the queue
        self.queue.appendleft(self.current_track)

        # Set the new current track
        self.current_track = self.history.pop()

        # Set the buffer to match the queue
        self.sync()

        return self.current_track

    def enqueue_next_track(self) -> Track:
        """Get the next buffered track

        Get the next track from the buffer without updating the current track
        attribute.  This allows Amazon to send the PlaybackNearlyFinished
        request early to queue the next track while maintaining the playlist

        :return: The next track to be played
        :rtype: Track
        """

        self.logger.debug('In enqueue_next_track()')

        return self.buffer.popleft()

    def clear(self) -> None:
        """Clear queue, history and buffer deques

        :return: None
        """

        self.logger.debug('In clear()')
        self.queue.clear()
        self.history.clear()
        self.buffer.clear()
        self.original_queue.clear()
        self.playback_mode = self.MODE_NORMAL
        self.current_track = Track()

    def get_queue_count(self) -> int:
        """Get the number of tracks in the queue

        :return: The number of tracks in the queue deque
        :rtype: int
        """

        self.logger.debug('In get_queue_count()')
        return len(self.queue)

    def get_history_count(self) -> int:
        """Get the number of tracks in the history deque

        :return: The number of tracks in the history deque
        :rtype: int
        """

        self.logger.debug('In get_history_count()')
        return len(self.history)

    def sync(self) -> None:
        """Synchronise the buffer with the queue

        Overwrite the buffer with the current queue.
        This is useful when pausing or stopping to ensure
        the resulting PlaybackNearlyFinished request gets
        the correct.  In practice this will have already
        queued and there for missing from the current buffer

        :return: None
        """

        self.buffer = deepcopy(self.queue)

    def set_playback_mode(self, mode: str) -> None:
        """Set the playback mode

        :param str mode: 'normal', 'repeat_one', or 'loop'
        :return: None
        """
        self.logger.debug(f'Setting playback mode to: {mode}')
        if mode in [self.MODE_NORMAL, self.MODE_REPEAT_ONE, self.MODE_LOOP]:
            self.playback_mode = mode
            if mode == self.MODE_LOOP and len(self.original_queue) == 0:
                # Store original queue for loop mode
                self.original_queue = deepcopy(self.queue)
                if self.current_track.id:
                    self.original_queue.appendleft(self.current_track)

    def get_playback_mode(self) -> str:
        """Get the current playback mode

        :return: Current playback mode
        :rtype: str
        """
        return self.playback_mode

    def save_original_queue(self) -> None:
        """Save the current queue as the original for loop mode

        :return: None
        """
        self.logger.debug('Saving original queue for loop mode')
        self.original_queue = deepcopy(self.queue)
        if self.current_track.id:
            self.original_queue.appendleft(deepcopy(self.current_track))

    def skip_current_track(self) -> Track:
        """Force skip to the next track

        This method is used when playback fails and we need to skip to the next track,
        ignoring repeat_one mode. If the queue is empty, returns a new empty Track.

        :return: The next track object, or empty Track if queue is exhausted
        :rtype: Track
        """

        self.logger.debug('In skip_current_track()')

        # Mark current track as failed
        if self.current_track.id:
            self.current_track.playback_failed = True
            self.history.append(self.current_track)

        # Check if queue is empty
        if len(self.queue) == 0:
            # Handle loop mode - restore original queue
            if self.playback_mode == self.MODE_LOOP and len(self.original_queue) > 0:
                self.logger.debug('Loop mode: restoring original queue')
                self.queue = deepcopy(self.original_queue)
                self.history.clear()
            else:
                # No more tracks - return empty track
                self.logger.debug('No more tracks in queue')
                self.current_track = Track()
                return self.current_track

        # Get next track from queue
        self.current_track = self.queue.popleft()
        self.current_track.offset = 0

        # Set the buffer to match the queue
        self.sync()

        return self.current_track

    def mark_current_track_transcoded(self, new_uri: str) -> None:
        """Mark current track as using transcoded stream and update URI

        :param str new_uri: The new transcoded URI
        :return: None
        """
        self.logger.debug('Marking current track as transcoded')
        self.current_track.transcoded = True
        self.current_track.uri = new_uri
        self.current_track.offset = 0
