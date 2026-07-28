"""
POST /favorites/list-create - Create a new custom favorites list.

Body: {year:int, category:"songs|albums|artists", genreLabel:str}
Response: {listId, year, category, genreLabel, items: []}
"""

import uuid

from lambdas.common.errors import handle_errors
from lambdas.common.favorites_dynamo import put_list
from lambdas.common.favorites_models import ListCreateRequest
from lambdas.common.logger import get_logger
from lambdas.common.model_helpers import parse_model
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = "favorites_list_create"


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    email = get_caller_email(event)
    request = parse_model(ListCreateRequest, body, HANDLER)

    list_id = str(uuid.uuid4())
    log.info(
        f"favorites_list_create email={email} year={request.year} "
        f"category={request.category} listId={list_id}"
    )

    put_list(
        email=email,
        year=request.year,
        list_id=list_id,
        category=request.category,
        genre_label=request.genreLabel,
        items=[],
    )

    return success_response({
        "listId": list_id,
        "year": request.year,
        "category": request.category,
        "genreLabel": request.genreLabel,
        "items": [],
    })
