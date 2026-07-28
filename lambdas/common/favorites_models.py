"""
Pydantic request models for the Favorites service.

Category is constrained to the three Spotify item kinds. All request bodies are
validated at the handler boundary via `lambdas.common.model_helpers.parse_model`,
which converts validation failures into HTTP 400 `ValidationError`s.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["songs", "albums", "artists"]


class FavoriteItem(BaseModel):
    """A single ranked entry in a favorites list."""

    model_config = ConfigDict(extra="ignore")

    rank: int = Field(ge=1)
    spotifyId: str = Field(min_length=1)
    name: str = ""
    artist: str = ""
    imageUrl: str = ""


class ListCreateRequest(BaseModel):
    """Body for POST /favorites/list-create."""

    model_config = ConfigDict(extra="ignore")

    year: int
    category: Category
    genreLabel: str = Field(min_length=1)


class ListSetRequest(BaseModel):
    """Body for PUT /favorites/list-set."""

    model_config = ConfigDict(extra="ignore")

    year: int
    listId: str = Field(min_length=1)
    items: list[FavoriteItem] = Field(default_factory=list)
