"""
POST /shares/create - Create a new share (track share with denormalized metadata)
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.shares_dynamo import create_share

log = get_logger(__file__)

HANDLER = 'shares_create'

ALLOWED_MOODS = {"hype", "chill", "sad", "party", "focus", "discovery"}
CAPTION_MAX_LEN = 140
GENRE_TAGS_MAX = 3


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(
        body,
        'email',
        'trackId',
        'trackUri',
        'trackName',
        'artistName',
        'albumName',
        'albumArtUrl',
    )

    email = body.get('email')
    track_id = body.get('trackId')
    track_uri = body.get('trackUri')
    track_name = body.get('trackName')
    artist_name = body.get('artistName')
    album_name = body.get('albumName')
    album_art_url = body.get('albumArtUrl')
    caption = body.get('caption')
    mood_tag = body.get('moodTag')
    genre_tags = body.get('genreTags')

    # Caption length
    if caption is not None and len(caption) > CAPTION_MAX_LEN:
        raise ValidationError(
            message=f"caption exceeds {CAPTION_MAX_LEN} characters",
            handler=HANDLER,
            function='handler',
            field='caption',
        )

    # Mood tag enum
    if mood_tag is not None and mood_tag not in ALLOWED_MOODS:
        raise ValidationError(
            message=f"Invalid moodTag '{mood_tag}'. Must be one of: {sorted(ALLOWED_MOODS)}",
            handler=HANDLER,
            function='handler',
            field='moodTag',
        )

    # Genre tags cap
    if genre_tags is not None:
        if not isinstance(genre_tags, list):
            raise ValidationError(
                message="genreTags must be a list",
                handler=HANDLER,
                function='handler',
                field='genreTags',
            )
        if len(genre_tags) > GENRE_TAGS_MAX:
            raise ValidationError(
                message=f"genreTags exceeds {GENRE_TAGS_MAX} entries",
                handler=HANDLER,
                function='handler',
                field='genreTags',
            )

    log.info(f"User {email} creating share for track {track_id}")
    result = create_share(
        email=email,
        track_id=track_id,
        track_uri=track_uri,
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        album_art_url=album_art_url,
        caption=caption,
        mood_tag=mood_tag,
        genre_tags=genre_tags,
    )

    log.info(f"Share {result['shareId']} created successfully")
    return success_response(result)
