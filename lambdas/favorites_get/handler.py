"""
GET /favorites/get?year=YYYY - Return a user's favorites for a year.

Response:
    {
      "year": 2026,
      "overall": {"songs": [Item], "albums": [Item], "artists": [Item]},
      "lists":   [{listId, category, genreLabel, items: [Item]}]   # custom only
    }
Item = {rank, spotifyId, name, artist, imageUrl}
"""

from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.favorites_dynamo import get_lists_for_year
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    success_response,
)

log = get_logger(__file__)

HANDLER = "favorites_get"

_OVERALL_CATEGORIES = ("songs", "albums", "artists")


def _parse_year(params: dict) -> int:
    raw = params.get("year")
    if raw is None:
        raise ValidationError("Missing required field: year", handler=HANDLER, field="year")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError("year must be an integer", handler=HANDLER, field="year")


def _sorted_items(row: dict) -> list[dict]:
    items = row.get("items") or []
    return sorted(items, key=lambda i: i.get("rank", 0))


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    email = get_caller_email(event)
    year = _parse_year(params)

    log.info(f"favorites_get email={email} year={year}")

    rows = get_lists_for_year(email, year)

    overall: dict[str, list] = {c: [] for c in _OVERALL_CATEGORIES}
    lists: list[dict] = []

    for row in rows:
        list_id = row.get("listId", "")
        category = row.get("category", "")
        items = _sorted_items(row)
        if list_id.startswith("overall:"):
            if category in overall:
                overall[category] = items
        else:
            lists.append({
                "listId": list_id,
                "category": category,
                "genreLabel": row.get("genreLabel"),
                "items": items,
            })

    return success_response({"year": year, "overall": overall, "lists": lists})
