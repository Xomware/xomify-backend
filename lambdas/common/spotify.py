import requests
import asyncio
import aiohttp
from datetime import datetime, timedelta
from lambdas.common.ssm_helpers import SPOTIFY_CLIENT_SECRET, SPOTIFY_CLIENT_ID
from lambdas.common.track_list import TrackList
from lambdas.common.artist_list import ArtistList
from lambdas.common.playlist import Playlist
from lambdas.common.logger import get_logger

log = get_logger(__file__)

class Spotify:
    """
    Spotify API client for a single user.
    Handles authentication and provides access to tracks, artists, and playlists.
    """

    BASE_URL = "https://api.spotify.com/v1"

    def __init__(self, user: dict, session: aiohttp.ClientSession = None):
        log.info(f"Initializing Spotify Client for User {user.get('email', 'unknown')}.")
        self.client_id: str = SPOTIFY_CLIENT_ID
        self.client_secret: str = SPOTIFY_CLIENT_SECRET
        self.aiohttp_session = session
        
        # User info
        self.user = user
        self.user_id: str = self.user.get('userId', '')
        self.email: str = self.user.get('email', '')
        self.refresh_token: str = self.user.get('refreshToken', '')
        
        # Auth - initialized later for async
        self.access_token: str = None
        self.headers: dict = {}
        
        # Initialize synchronously if no aiohttp session
        if not self.aiohttp_session:
            self.access_token = self.get_access_token()
            self.headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
        
    async def aiohttp_initialize_wrapped(self):
        """Initialize client for wrapped cron job (top tracks/artists + playlists)."""
        try:
            self.access_token = await self.aiohttp_get_access_token()
            self.headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            # Top tracks for each time range
            self.top_tracks_short = TrackList('short_term', self.headers, self.aiohttp_session)
            self.top_tracks_medium = TrackList('medium_term', self.headers, self.aiohttp_session)
            self.top_tracks_long = TrackList('long_term', self.headers, self.aiohttp_session)
            
            # Top artists for each time range
            self.top_artists_short = ArtistList('short_term', self.headers, self.aiohttp_session)
            self.top_artists_medium = ArtistList('medium_term', self.headers, self.aiohttp_session)
            self.top_artists_long = ArtistList('long_term', self.headers, self.aiohttp_session)
            
            # Get date info for playlist naming
            self.last_month, self.last_month_number, self.this_year = self.__get_last_month_data()
            
            # Monthly playlist
            self.monthly_spotify_playlist = Playlist(
                self.user_id,
                f"Xomify {self.last_month}'{self.this_year}", 
                f"Your Top 25 songs for {self.last_month} - Created by xomify.xomware.com", 
                self.headers,
                self.aiohttp_session
            )
            
            # First half of year playlist (June)
            self.first_half_of_year_spotify_playlist = Playlist(
                self.user_id,
                f"Xomify First Half '{self.this_year}",
                f"Your Top 25 songs for the First 6 months of '{self.this_year} - Created by xomify.xomware.com",
                self.headers,
                self.aiohttp_session
            )
            
            # Full year playlist (December)
            self.full_year_spotify_playlist = Playlist(
                self.user_id,
                f"Xomify 20{self.this_year}",
                f"Your Top 25 songs for 20{self.this_year} - Created by xomify.xomware.com",
                self.headers,
                self.aiohttp_session
            )
            
            log.info(f"Wrapped initialized for {self.email} (month: {self.last_month})")
            
        except Exception as err:
            log.error(f"AIOHTTP Initialize Wrapped: {err}")
            raise Exception(f"AIOHTTP Initialize Wrapped: {err}") from err
        
    async def aiohttp_initialize_top_items(self):
        """Initialize client for fetching top tracks, artists, and genres only (no playlists)."""
        try:
            self.access_token = await self.aiohttp_get_access_token()
            self.headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }

            # Top tracks for each time range
            self.top_tracks_short = TrackList('short_term', self.headers, self.aiohttp_session)
            self.top_tracks_medium = TrackList('medium_term', self.headers, self.aiohttp_session)
            self.top_tracks_long = TrackList('long_term', self.headers, self.aiohttp_session)

            # Top artists for each time range
            self.top_artists_short = ArtistList('short_term', self.headers, self.aiohttp_session)
            self.top_artists_medium = ArtistList('medium_term', self.headers, self.aiohttp_session)
            self.top_artists_long = ArtistList('long_term', self.headers, self.aiohttp_session)

            log.info(f"Top items client initialized for {self.email}")

        except Exception as err:
            log.error(f"AIOHTTP Initialize Top Items: {err}")
            raise Exception(f"AIOHTTP Initialize Top Items: {err}") from err

    async def aiohttp_initialize_release_radar(self):
        """Initialize client for release radar cron job (followed artists + playlist)."""
        try:
            self.access_token = await self.aiohttp_get_access_token()
            self.headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            # Release radar playlist
            self.release_radar_playlist = Playlist(
                self.user_id,
                "Xomify Weekly Release Radar",
                "All your followed artists newest songs - Created by xomify.xomware.com",
                self.headers,
                self.aiohttp_session
            )
            
            # Followed artists tracker
            self.followed_artists = ArtistList('Following', self.headers, self.aiohttp_session)
            
            # Set existing playlist ID if user already has one
            existing_playlist_id = self.user.get('releaseRadarId')
            if existing_playlist_id:
                self.release_radar_playlist.set_id(existing_playlist_id)
                
            log.info(f"Release radar initialized for {self.email}")
            
        except Exception as err:
            log.error(f"AIOHTTP Initialize Release Radar: {err}")
            raise Exception(f"AIOHTTP Initialize Release Radar: {err}") from err

    def get_access_token(self) -> str:
        """Get access token using refresh token (synchronous)."""
        try:
            log.info("Getting spotify access token...")
            url = "https://accounts.spotify.com/api/token"

            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            }

            response = requests.post(url, data=data)
            response_data = response.json()

            if response.status_code != 200:
                raise Exception(f"Error refreshing token: {response_data}")

            log.info("Successfully retrieved spotify access token!")
            return response_data['access_token']
            
        except Exception as err:
            log.error(f"Get Spotify Access Token: {err}")
            raise Exception(f"Get Spotify Access Token: {err}") from err
        
    async def aiohttp_get_access_token(self) -> str:
        """Get access token using refresh token (async).

        Persists a rotated refresh_token back to DynamoDB when Spotify
        returns one — prevents token-revocation drift.
        """
        try:
            log.info("Getting spotify access token (aiohttp)...")
            url = "https://accounts.spotify.com/api/token"

            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            }

            async with self.aiohttp_session.post(url, data=data) as response:
                response_data = await response.json()

                if response.status != 200:
                    raise Exception(f"Error refreshing token: {response_data}")

                new_refresh = response_data.get('refresh_token')
                if new_refresh and new_refresh != self.refresh_token:
                    log.info("Spotify rotated refresh token — persisting new token")
                    self.refresh_token = new_refresh
                    self._persist_rotated_refresh_token(new_refresh)

                log.info("Successfully retrieved spotify access token!")
                return response_data['access_token']

        except Exception as err:
            log.error(f"AIOHTTP Get Spotify Access Token: {err}")
            raise Exception(f"AIOHTTP Get Spotify Access Token: {err}") from err

    def _persist_rotated_refresh_token(self, new_token: str):
        """Save a rotated refresh token back to the users table."""
        try:
            from lambdas.common.dynamo_helpers import update_table_item_field
            from lambdas.common.constants import USERS_TABLE_NAME
            update_table_item_field(
                USERS_TABLE_NAME, 'email', self.email,
                'refreshToken', new_token
            )
        except Exception as err:
            log.warning(f"Failed to persist rotated refresh token: {err}")
        
    async def get_top_tracks(self):
        """Fetch top tracks for all time ranges (sync version)."""
        try:
            log.info(f"Getting Top tracks for User {self.email}...")
            tasks = [
                self.top_tracks_short.set_top_tracks(),
                self.top_tracks_medium.set_top_tracks(),
                self.top_tracks_long.set_top_tracks()
            ]
            await asyncio.gather(*tasks)
            log.info("Top Tracks Retrieved!")
        except Exception as err:
            log.error(f"Get Top Tracks: {err}")
            raise Exception(f"Get Top Tracks: {err}") from err
        
    async def get_top_artists(self):
        """Fetch top artists for all time ranges (sync version)."""
        try:
            log.info(f"Getting Top Artists for User {self.email}...")
            tasks = [
                self.top_artists_short.set_top_artists(),
                self.top_artists_medium.set_top_artists(),
                self.top_artists_long.set_top_artists()
            ]
            await asyncio.gather(*tasks)
            log.info("Top Artists Retrieved!")
        except Exception as err:
            log.error(f"Get Top Artists: {err}")
            raise Exception(f"Get Top Artists: {err}") from err
        
    def get_top_tracks_ids_last_month(self) -> dict:
        """Get track IDs for all time ranges."""
        return {
            "short_term": self.top_tracks_short.track_id_list,
            "medium_term": self.top_tracks_medium.track_id_list,
            "long_term": self.top_tracks_long.track_id_list
        }
    
    def get_top_artists_ids_last_month(self) -> dict:
        """Get artist IDs for all time ranges."""
        return {
            "short_term": self.top_artists_short.artist_id_list,
            "medium_term": self.top_artists_medium.artist_id_list,
            "long_term": self.top_artists_long.artist_id_list
        }
    
    def get_top_genres_last_month(self) -> dict:
        """Get genre counts for all time ranges."""
        return {
            "short_term": self.top_artists_short.top_genres,
            "medium_term": self.top_artists_medium.top_genres,
            "long_term": self.top_artists_long.top_genres
        }

    async def get_top_items_for_api(self) -> dict:
        """
        Fetch and return top tracks, artists, and genres for API response.
        Returns a structured dict with all time ranges.
        """
        try:
            log.info(f"Fetching top items for API for user {self.email}...")

            # Fetch tracks and artists in parallel
            await asyncio.gather(
                self.get_top_tracks(),
                self.get_top_artists()
            )

            return {
                "tracks": {
                    "short_term": self.top_tracks_short.track_list,
                    "medium_term": self.top_tracks_medium.track_list,
                    "long_term": self.top_tracks_long.track_list
                },
                "artists": {
                    "short_term": self.top_artists_short.artist_list,
                    "medium_term": self.top_artists_medium.artist_list,
                    "long_term": self.top_artists_long.artist_list
                },
                "genres": {
                    "short_term": self.top_artists_short.top_genres,
                    "medium_term": self.top_artists_medium.top_genres,
                    "long_term": self.top_artists_long.top_genres
                }
            }
        except Exception as err:
            log.error(f"Get Top Items For API: {err}")
            raise Exception(f"Get Top Items For API: {err}") from err

    # Spotify caps the batch endpoints at 50 tracks / 50 artists per request.
    _BATCH_LIMIT = 50

    def get_tracks_by_ids(self, track_ids: list) -> list:
        """
        Batch-hydrate full track objects from bare Spotify track IDs.

        Uses `GET /v1/tracks?ids=` (synchronous, via the sync `headers` set up in
        `__init__` when no aiohttp session is supplied). Spotify caps the call at
        50 ids, so we chunk transparently and concatenate. Missing/None entries
        in Spotify's response are dropped so callers always get real objects.

        Args:
            track_ids: List of Spotify track IDs (order preserved across chunks).

        Returns:
            List of full track objects (same shape as `/me/top/tracks` items).
        """
        return self.__batch_get_objects("tracks", track_ids)

    def get_artists_by_ids(self, artist_ids: list) -> list:
        """
        Batch-hydrate full artist objects from bare Spotify artist IDs.

        Uses `GET /v1/artists?ids=`. Same chunking/cleanup semantics as
        `get_tracks_by_ids`.

        Args:
            artist_ids: List of Spotify artist IDs (order preserved).

        Returns:
            List of full artist objects (same shape as `/me/top/artists` items).
        """
        return self.__batch_get_objects("artists", artist_ids)

    def __batch_get_objects(self, kind: str, ids: list) -> list:
        """
        Shared batch-get for `tracks`/`artists`.

        Spotify returns `{ "tracks": [...] }` or `{ "artists": [...] }`; the
        list is positionally aligned with the requested ids and may contain
        `null` for unresolved ids, which we filter out.
        """
        clean_ids = [i for i in (ids or []) if i]
        if not clean_ids:
            return []

        objects: list = []
        for start in range(0, len(clean_ids), self._BATCH_LIMIT):
            chunk = clean_ids[start:start + self._BATCH_LIMIT]
            url = f"{self.BASE_URL}/{kind}?ids={','.join(chunk)}"

            response = requests.get(url, headers=self.headers)
            if response.status_code != 200:
                raise Exception(
                    f"Batch get {kind} failed ({response.status_code}): {response.text}"
                )

            data = response.json()
            objects.extend([obj for obj in (data.get(kind) or []) if obj])

        return objects

    def __get_last_month_data(self) -> tuple:
        """
        Get information about last month for playlist naming.
        Returns: (month_name, month_number, two_digit_year)
        """
        try:
            current_date = datetime.now()
            
            # Get first day of current month
            first_of_current_month = current_date.replace(day=1)
            
            # Get last day of previous month
            last_day_of_previous_month = first_of_current_month - timedelta(days=1)
            
            # Extract data
            last_month_name = last_day_of_previous_month.strftime("%B")
            last_month_number = last_day_of_previous_month.month
            current_year = str(current_date.year)[2:]  # Two digit year

            return last_month_name, last_month_number, current_year
            
        except Exception as err:
            log.error(f"Get Last Month Data: {err}")
            raise Exception(f"Get Last Month Data: {err}") from err