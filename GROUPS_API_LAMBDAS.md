# Groups API Lambda Functions

## Overview

All group endpoints now have dedicated single-purpose Lambda functions following the 1:1 route-to-lambda architecture.

## Lambda Functions Created

### ✅ Already Existed
1. [groups_list](lambdas/groups_list/handler.py) - `GET /groups/list`
2. [groups_info](lambdas/groups_info/handler.py) - `GET /groups/info` (with parallel queries)

### ✅ Newly Created

#### Group Management (5 lambdas)
3. [groups_create](lambdas/groups_create/handler.py) - `POST /groups/create`
   - Creates group with UUID
   - Adds creator as owner
   - Adds initial members

4. [groups_update](lambdas/groups_update/handler.py) - `PUT /groups/update`
   - Updates name/description
   - Owner-only permission check

5. [groups_remove](lambdas/groups_remove/handler.py) - `DELETE /groups/remove`
   - Deletes group
   - Owner-only permission check
   - Returns 204 No Content

#### Member Management (4 lambdas)
6. [groups_add_member](lambdas/groups_add_member/handler.py) - `POST /groups/add-member`
   - Adds member to group
   - Returns member details from user table

7. [groups_remove_member](lambdas/groups_remove_member/handler.py) - `DELETE /groups/remove-member`
   - Removes member from group
   - Returns 204 No Content

8. [groups_leave](lambdas/groups_leave/handler.py) - `POST /groups/leave`
   - User leaves group
   - Returns 204 No Content

#### Song/Track Management (5 lambdas)
9. [groups_add_song](lambdas/groups_add_song/handler.py) - `POST /groups/add-song`
   - Adds track with full track data
   - Extracts track name, artist, album art

10. [groups_add_song_url](lambdas/groups_add_song_url/handler.py) - `POST /groups/add-song-url`
    - Adds track by Spotify URL
    - Extracts track ID from URL
    - Fetches track details from Spotify API
    - Supports both URL formats:
      - `https://open.spotify.com/track/ID`
      - `spotify:track:ID`

11. [groups_remove_song](lambdas/groups_remove_song/handler.py) - `DELETE /groups/remove-song`
    - Removes song from group
    - Returns 204 No Content

12. [groups_song_status](lambdas/groups_song_status/handler.py) - `PUT /groups/song-status`
    - Updates user's listen status
    - Tracks addedToQueue and listened flags

13. [groups_mark_all_listened](lambdas/groups_mark_all_listened/handler.py) - `POST /groups/mark-all-listened`
    - Marks all songs as listened for user
    - Returns count of marked songs

## DynamoDB Helpers Used

### groups_dynamo.py
- `create_group()`
- `get_group()`
- `update_group()` (via direct table access)
- `delete_group()` (via direct table access)

### group_members_dynamo.py
- `add_group_member()`
- `remove_group_member()`
- `list_groups_for_user()`
- `list_members_of_group()`

### group_tracks_dynamo.py
- `add_track_to_group()`
- `list_tracks_for_group()`
- `mark_track_as_listened()`
- `list_unheard_tracks_for_user()`

## Key Features

### Permission Checks
- **Owner-only actions:** update, delete (checked in handlers)
- **Member actions:** add songs, update status (no special check)

### Parallel Processing
- `groups_info` uses `asyncio.gather()` to fetch group, members, and tracks in parallel
- Reduces response time by ~3x

### Spotify Integration
- `groups_add_song_url` fetches track details from Spotify API
- Uses user's access token
- Handles URL parsing for track ID extraction

### Transaction Support
- Member add/remove operations update group memberCount atomically
- Uses DynamoDB transactions

## API Gateway Routes Needed

Update your API Gateway with these routes:

```yaml
# Group Management
POST   /groups/create              → xomify-groups-create
PUT    /groups/update              → xomify-groups-update
DELETE /groups/remove              → xomify-groups-remove

# Member Management
POST   /groups/add-member          → xomify-groups-add-member
DELETE /groups/remove-member       → xomify-groups-remove-member
POST   /groups/leave               → xomify-groups-leave

# Song Management
POST   /groups/add-song            → xomify-groups-add-song
POST   /groups/add-song-url        → xomify-groups-add-song-url
DELETE /groups/remove-song         → xomify-groups-remove-song
PUT    /groups/song-status         → xomify-groups-song-status
POST   /groups/mark-all-listened   → xomify-groups-mark-all-listened

# Info/List (already existed)
GET    /groups/list                → xomify-groups-list
GET    /groups/info                → xomify-groups-info
```

## Response Formats

### 200 Success with Body
Most endpoints return structured JSON:
```json
{
  "groupId": "uuid",
  "name": "My Group",
  ...
}
```

### 204 No Content
Delete/remove endpoints return empty body:
- `groups_remove`
- `groups_remove_member`
- `groups_leave`
- `groups_remove_song`

## Testing

Run tests for all handlers:

```bash
# Create tests
pytest tests/test_groups_create.py -v
pytest tests/test_groups_add_song.py -v

# Run all group tests
pytest tests/test_groups_* -v
```

## Deployment

All handlers will be automatically deployed when you push to master:

1. GitHub Actions detects changed files
2. Runs tests for changed lambdas
3. Deploys only changed lambdas
4. Updates layer if common code changed

## Notes

### Song Status Tracking
The `groups_song_status` endpoint currently only tracks `listened` status in DynamoDB. The `addedToQueue` flag is returned but not persisted. To fully implement queue tracking, add a `queuedBy` DynamoDB attribute similar to `listenedBy`.

### URL Parsing
The `groups_add_song_url` endpoint handles both Spotify URL formats:
- Web URL: `https://open.spotify.com/track/7qiZfU4dY1lWllzX7mPBI`
- URI: `spotify:track:7qiZfU4dY1lWllzX7mPBI`

### Member Count
Group `memberCount` is automatically maintained via DynamoDB transactions when members are added/removed.
