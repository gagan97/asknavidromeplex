# AskNavidromePlex - AI Coding Instructions

## Project Overview
Alexa Skill streaming music from **Navidrome** (Subsonic API) and **Plex** to Echo devices. Flask + ASK SDK handles voice commands and AudioPlayer directives.

## Architecture & Data Flow
```
Alexa Intent → app.py handler → MediaService → [Navidrome|Plex] → MediaQueue → AudioPlayer Directive
```

**Key files in `skill/asknavidrome/`:**
- `app.py` - All intent handlers (~1700 lines), Flask entry point, global `connection` (MediaService), single-file monolith design
- `media_service.py` - Source abstraction layer, fuzzy matching via `_select_best_result()`, bitrate preferences
- `subsonic_api.py` - Navidrome client using `libsonic` library
- `plex_api.py` - Plex client with `_extract_all_properties()` for flexible metadata extraction
- `controller.py` - Builds Alexa `PlayDirective`/`StopDirective` responses, handles card/metadata display
- `media_queue.py` - Thread-safe `deque`-based queue with `BaseManager` for multiprocessing, playback modes (normal/repeat/loop)
- `track.py` - Track dataclass with `source` field (`'navidrome'` or `'plex'`), stores cover art URLs

**Auto-generated (DO NOT EDIT):**
- `plex_api_client/` - Plex SDK client, regenerate if API updates needed

## Critical Patterns

### Intent Handler Template (app.py)
Every handler follows this exact structure:
```python
class NaviSonicPlayMusicByArtist(AbstractRequestHandler):
    def can_handle(self, handler_input): 
        return is_intent_name('NaviSonicPlayMusicByArtist')(handler_input)
    
    def handle(self, handler_input):
        global backgroundProcess
        if backgroundProcess is not None:  # Always terminate existing background process
            backgroundProcess.terminate(); backgroundProcess.join()
        
        artist = get_slot_value_v2(handler_input, 'artist')
        artist_lookup = connection.search_artist(artist.value)
        source = artist_lookup[0].get('source', 'navidrome')  # Track source for multi-source
        
        # Enqueue first 2 tracks synchronously, spawn Process for rest (8-sec timeout)
        controller.enqueue_songs(connection, play_queue, [song_id_list[0], song_id_list[1]], source)
        backgroundProcess = Process(target=queue_worker_thread, args=(connection, play_queue, song_id_list[2:], source))
        backgroundProcess.start()
        
        speech = sanitise_speech_output(f'Playing music by: {truncate_for_speech(artist.value, max_length=50)}')
        track_details = play_queue.get_next_track()
        card = build_card_data(speech, track_details)
        
        return controller.start_playback('play', speech, card, track_details, handler_input)
```

**Key steps in every handler:**
1. Terminate existing `backgroundProcess` to avoid queue conflicts
2. Get slots via `get_slot_value_v2()`, access `.value` property
3. Extract `source` from search results (default `'navidrome'`)
4. Enqueue first 2 tracks synchronously, background process for rest
5. Build speech with `sanitise_speech_output()` + `truncate_for_speech()`
6. Build card with `build_card_data(speech, track_details)`
7. Return `controller.start_playback()` response

### 8-Second Timeout Workaround
Amazon enforces 8s response deadline. **Always** enqueue only first 2 tracks synchronously, spawn `Process` for remaining tracks via `queue_worker_thread()`. This pattern appears in all playlist-building handlers.

### Multi-Source Handling
- `MediaService` queries both enabled sources, merges results with fuzzy matching
- Track `source` field identifies origin - pass `source` to all queue/streaming methods
- `connection.get_stream_url(track_id, source)` routes to correct backend
- Search methods return `source` in result dicts: `{'id': '123', 'name': 'Artist', 'source': 'plex'}`

### Plex Property Extraction
Use `_extract_all_properties()` in `plex_api.py` for metadata with fallback paths (Plex SDK objects vary by version):
```python
titles = self._extract_all_properties(track, ['original_title', 'originalTitle', 'grandparentTitle'])
```
Returns list of all found values; use first non-empty for best match.

### Speech & Card Processing
- `sanitise_speech_output(text)` - Removes SSML-reserved chars (`&`, `/`, `<`, `>`, quotes) before speech
- `truncate_for_speech(text, max_length=50)` - Shortens long titles, splits on separators (`|`, `-`, `:`)
- `build_card_data(speech, track_details)` - Builds card dict with cover art URLs from Track object

### PlaybackController Handlers (Physical Buttons)
Device button presses (Next/Previous/Play/Pause) send `PlaybackController.*` requests which **cannot contain speech, reprompt, or shouldEndSession=false** - only AudioPlayer directives are allowed:
```python
class PlaybackControllerNextHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type('PlaybackController.NextCommandIssued')(handler_input)
    
    def handle(self, handler_input):
        track_details = play_queue.get_next_track()
        track_details.offset = 0
        return controller.start_playback('play', None, None, track_details, handler_input)  # No speech!
```
Use `is_request_type()` (not `is_intent_name()`) for these handlers.

### Cover Art URLs
- **Navidrome**: `subsonic_api.get_cover_art_url(cover_art_id, size)` generates authenticated URLs via `/getCoverArt.view`
- **Plex**: Full URLs built with `{base_url}{thumb_path}?X-Plex-Token={token}`
- Both sources set `coverPosterUrl` and `backgroundUrl` in song details dict

## Environment Variables (see `docker-compose.yml`)
```bash
NAVI_SKILL_ID=<required>           # Alexa skill ID
SKILL_NAME=AskNavidromePlex        # Displayed in responses
ENABLE_NAVIDROME=1 / ENABLE_PLEX=0 # Toggle sources (at least one required)
NAVI_URL, NAVI_USER, NAVI_PASS     # Navidrome credentials
PLEX_URL, PLEX_TOKEN, PLEX_PORT    # Plex settings
MUSIC_SECTION=Music                # Plex library name
NAVI_SONG_COUNT=50                 # Min songs for artist/genre playlists
PREFER_HIGH_BITRATE=0              # Quality preference (1=highest)
NAVI_DEBUG=1                       # Logging level
```

## Development Commands
```bash
# Local development (choose source)
cd skill && pip install -r requirements-full.txt
NAVI_SKILL_ID=test ENABLE_NAVIDROME=1 NAVI_URL=... python app.py  # Port 5000

# Docker build & run
docker build -t asknavidromeplex . && docker-compose up

# Multi-arch Docker (manual)
docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/user/asknavidromeplex:latest .
```

**Debug endpoints** (running on port 5000):
- `/queue` - View queued tracks
- `/history` - View play history
- `/buffer` - View buffer contents

## Adding New Intents
1. Add intent + slots + samples to `alexa.json` (use existing as template)
2. Create handler class in `app.py` following template above
3. Register: `sb.add_request_handler(YourHandler())` at bottom of `app.py` (line ~1620)
4. Test with Alexa Developer Console simulator

## CI/CD & Deployment
- **Docker builds**: Tag push (`git tag v1.0.0 && git push --tags`) triggers `.github/workflows/build_image.yml`
- **Multi-arch**: Builds `linux/amd64` + `linux/arm64` to `ghcr.io/gagan97/asknavidromeplex`
- **HTTPS required**: Alexa requires valid SSL cert - use nginx/Caddy reverse proxy or ngrok
- **No tests**: Project has no test suite - validate manually with Alexa Developer Console simulator
- **Docs**: Sphinx docs auto-build on push to `main` (see `.github/workflows/build_sphinx_docs.yml`)

## Key Conventions & Gotchas
- Use `get_slot_value_v2()` for slot values (returns object with `.value` property, not string)
- Always call `sanitise_speech_output()` before speech text to avoid SSML errors
- Always call `truncate_for_speech()` for user-provided content (titles, artists) to avoid overly long speech
- Pass `source` parameter when working with tracks from multi-source searches
- `plex_api_client/` is auto-generated - make Plex changes in `plex_api.py` only
- Global variables: `connection` (MediaService), `play_queue` (MediaQueue), `backgroundProcess` (Process)
- Handler registration order matters for `can_handle()` precedence
- Fuzzy matching threshold: 0.6 (60% similarity) in `MediaService._select_best_result()`
