"""
PUT /favorites/list-set - Replace a list's items, recording rank-change history.

Body: {year:int, listId:str, items:[{rank, spotifyId, name, artist, imageUrl}]}
Response: {listId, year, category, genreLabel, items:[Item]}

Behaviour:
- Load LIST#{year}#{listId}.
- If missing and listId startswith "overall:" -> auto-create (category parsed
  from the suffix, genreLabel="Overall"); otherwise 404.
- For every changed rank, append a HIST event:
    new item -> fromRank=null; moved -> fromRank!=toRank; removed -> toRank=null.
"""

from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.favorites_dynamo import (
    append_history_events,
    get_list,
    put_list,
)
from lambdas.common.favorites_models import ListSetRequest
from lambdas.common.logger import get_logger
from lambdas.common.model_helpers import parse_model
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = "favorites_list_set"

_VALID_CATEGORIES = ("songs", "albums", "artists")


def _resolve_overall(list_id: str) -> str:
    """Parse the category from an `overall:{year}:{category}` listId."""
    parts = list_id.split(":")
    if len(parts) < 3 or parts[2] not in _VALID_CATEGORIES:
        raise ValidationError(
            f"Malformed overall listId: {list_id}", handler=HANDLER, field="listId"
        )
    return parts[2]


def _to_item(model) -> dict:
    return {
        "rank": model.rank,
        "spotifyId": model.spotifyId,
        "name": model.name,
        "artist": model.artist,
        "imageUrl": model.imageUrl,
    }


def _rank_map(items: list[dict]) -> dict[str, int]:
    """Map spotifyId -> rank. Later duplicates lose to the first seen."""
    ranks: dict[str, int] = {}
    for item in items:
        spotify_id = item.get("spotifyId")
        if spotify_id and spotify_id not in ranks:
            ranks[spotify_id] = int(item.get("rank"))
    return ranks


def _diff_events(old: dict[str, int], new: dict[str, int]) -> list[dict]:
    """Build one HIST event per changed rank between old and new item sets."""
    events: list[dict] = []
    for spotify_id, new_rank in new.items():
        old_rank = old.get(spotify_id)
        if old_rank is None:
            events.append({"spotifyId": spotify_id, "fromRank": None, "toRank": new_rank})
        elif old_rank != new_rank:
            events.append({"spotifyId": spotify_id, "fromRank": old_rank, "toRank": new_rank})
    for spotify_id, old_rank in old.items():
        if spotify_id not in new:
            events.append({"spotifyId": spotify_id, "fromRank": old_rank, "toRank": None})
    return events


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    email = get_caller_email(event)
    request = parse_model(ListSetRequest, body, HANDLER)

    existing = get_list(email, request.year, request.listId)

    if existing is None:
        if not request.listId.startswith("overall:"):
            raise NotFoundError(
                f"List not found: {request.listId}",
                handler=HANDLER,
                resource=request.listId,
            )
        category = _resolve_overall(request.listId)
        genre_label = "Overall"
        created_at = None
        old_ranks: dict[str, int] = {}
    else:
        category = existing.get("category", "")
        genre_label = existing.get("genreLabel")
        created_at = existing.get("createdAt")
        old_ranks = _rank_map(existing.get("items") or [])

    new_items = [_to_item(m) for m in request.items]
    new_ranks = _rank_map(new_items)

    events = _diff_events(old_ranks, new_ranks)
    if events:
        append_history_events(email, request.listId, events)

    log.info(
        f"favorites_list_set email={email} listId={request.listId} "
        f"items={len(new_items)} history_events={len(events)}"
    )

    put_list(
        email=email,
        year=request.year,
        list_id=request.listId,
        category=category,
        genre_label=genre_label,
        items=new_items,
        created_at=created_at,
    )

    return success_response({
        "listId": request.listId,
        "year": request.year,
        "category": category,
        "genreLabel": genre_label,
        "items": new_items,
    })
