

from typing import  List, Any


def extract_all_properties(self,obj: Any, property_paths: List[str]) -> List[str]:
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

def get_all_track_artists(self,track) -> List[str]:
    """
    Extract ALL available artist names from track metadata.
    Returns all unique artist name values found (originalTitle, grandparentTitle, etc.).
    
    Args:
        track: The track metadata object from Plex API
        
    Returns:
        List[str]: List of all available artist names
    """
    try:
        return extract_all_properties(
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
    
def get_track_title(self, track) -> str:
    """
    Extract track title from Plex track metadata.
    Returns the first available title value.
    
    Args:
        track: The track metadata object from Plex API
        
    Returns:
        str: The track title or empty string if not found
    """
    try:
        titles = extract_all_properties(
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

def get_all_track_albums(self,track) -> List[str]:
    """
    Extract ALL available album names from track metadata.
    Returns all unique album name values found.
    
    Args:
        track: The track metadata object from Plex API
        
    Returns:
        List[str]: List of all available album names
    """
    try:
        return extract_all_properties(
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
    
def get_track_media_info(self,track):
    """
    Extract media info (bitrate, codec) from track metadata
    
    Args:
        track: The track metadata object from Plex API
        
    Returns:
        dict: The media info including audioCodec, bitrate, etc.
    """
    try:
        media_info = {
            'audioCodec': extract_all_properties(track, [
                'Media.audioCodec', 
                'raw_response.json.Media.audioCodec',
                'Media.0.audioCodec'  # Handle new XML format where Media is a list
            ]),
            'bitrate': extract_all_properties(track, [
                'Media.bitrate', 
                'raw_response.json.Media.bitrate',
                'Media.0.bitrate'
            ]),
            'channels': extract_all_properties(track, [
                'Media.audioChannels', 
                'raw_response.json.Media.audioChannels',
                'Media.0.audioChannels'
            ]),
            'duration': extract_all_properties(track, [
                'Media.duration', 
                'raw_response.json.Media.duration',
                'Media.0.duration'
            ]),
            'container': extract_all_properties(track, [
                'Media.container', 
                'raw_response.json.Media.container',
                'Media.0.container'
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
            'container': None
        }
