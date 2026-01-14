# AskNavidromePlex - AI Coding Instructions

## Project Overview
Alexa Skill streaming music from **Navidrome** (Subsonic API) and **Plex** to Echo devices. Flask + ASK SDK handles voice commands and AudioPlayer directives.

## Architecture & Data Flow
```
Alexa Intent → app.py handler → MediaService → [Navidrome|Plex] → MediaQueue → AudioPlayer Directive
```

**Key files in `skill/asknavidrome/`:**
- `app.py` - All intent handlers (~1500 lines), Flask entry point, global `connection` (MediaService)
- `media_service.py` - Aggregates results from enabled sources, uses fuzzy matching (`_select_best_result()`)
- `subsonic_api.py` - Navidrome client via `libsonic`
- `plex_api.py` - Plex client with optional SDK (`plex_api_client/` - auto-generated, do not edit)
- `controller.py` - Builds Alexa `PlayDirective`/`StopDirective` responses
- `media_queue.py` - Thread-safe `deque`-based queue with `BaseManager` for multiprocessing
- `track.py` - Track dataclass with `source` field (`'navidrome'` or `'plex'`)

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
        
        return controller.start_playback('play', speech, card, track_details, handler_input)
```

### 8-Second Timeout Workaround
Amazon enforces 8s response deadline. **Always** enqueue only first 2 tracks synchronously, spawn `Process` for remaining tracks via `queue_worker_thread()`.

### Multi-Source Handling
- `MediaService` queries both enabled sources, merges results with fuzzy matching
- Track `source` field identifies origin - pass `source` to all queue/streaming methods
- `connection.get_stream_url(track_id, source)` routes to correct backend

### Plex Property Extraction
Use `plex_support.py` helpers for metadata with fallback paths (Plex SDK objects vary):
```python
extract_all_properties(track, ['original_title', 'originalTitle', 'grandparentTitle'])
```

## Environment Variables (see `docker-compose.yml`)
```bash
NAVI_SKILL_ID=<required>           # Alexa skill ID
ENABLE_NAVIDROME=1 / ENABLE_PLEX=0 # Toggle sources
NAVI_URL, NAVI_USER, NAVI_PASS     # Navidrome credentials
PLEX_URL, PLEX_TOKEN, MUSIC_SECTION # Plex settings
PREFER_HIGH_BITRATE=0              # Quality preference
```

## Development Commands
```bash
cd skill && pip install -r requirements-full.txt
NAVI_SKILL_ID=test ENABLE_NAVIDROME=0 ENABLE_PLEX=1 PLEX_URL=... python app.py  # Local run (port 5000)
docker build -t asknavidromeplex . && docker-compose up  # Docker run
```

## Adding New Intents
1. Add intent + slots + samples to `alexa.json`
2. Create handler class in `app.py` following template above
3. Register: `sb.add_request_handler(YourHandler())` at bottom of `app.py`

## CI/CD & Deployment
- **Docker builds**: Tag push (`git tag v1.0.0 && git push --tags`) triggers multi-arch build to GHCR
- **HTTPS required**: Alexa needs valid SSL cert - use nginx/Caddy reverse proxy or ngrok
- **No tests**: Project has no test suite - validate manually with Alexa simulator

## Key Conventions
- Use `get_slot_value_v2()` for Alexa slot values (returns object with `.value`)
- Use `sanitise_speech_output()` before any speech text (removes special chars)
- Always pass `source` parameter when working with tracks/songs from multi-source searches
- `plex_api_client/` is auto-generated - make Plex changes in `plex_api.py` only
