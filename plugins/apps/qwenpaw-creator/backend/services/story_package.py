# -*- coding: utf-8 -*-
"""Portable writing inputs, independent of Creator's production graph."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qwenpaw.pawapp.tasks.contracts import canonical_json, content_digest

StoryId = Annotated[
    str,
    Field(max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
Text = Annotated[str, Field(max_length=8000)]


class StoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StoryCharacter(StoryModel):
    id: StoryId
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Text
    continuity: Text = ""


class StoryReference(StoryModel):
    id: StoryId
    label: Annotated[str, Field(min_length=1, max_length=256)]
    uri: Annotated[str, Field(max_length=2048)] = ""
    notes: Text = ""


class StoryPackage(StoryModel):
    """An agreed writing revision, not permission to fetch or render media."""

    schema_version: Literal[1] = 1
    story_id: StoryId
    revision: int = Field(ge=1)
    title: Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
    logline: Annotated[str, Field(max_length=2000)] = ""
    synopsis: Text
    script_markdown: Annotated[
        str,
        Field(min_length=1, max_length=50000, pattern=r"\S"),
    ]
    audience: Annotated[str, Field(max_length=2000)] = ""
    tone: Annotated[str, Field(max_length=2000)] = ""
    characters: list[StoryCharacter] = Field(
        default_factory=list,
        max_length=64,
    )
    references: list[StoryReference] = Field(
        default_factory=list,
        max_length=64,
    )
    decisions: list[Text] = Field(default_factory=list, max_length=64)
    constraints: list[Text] = Field(default_factory=list, max_length=64)
    language: Annotated[
        str,
        Field(max_length=35, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$"),
    ] = "en"
    duration_seconds: int | None = Field(default=None, ge=1, le=3600)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] = "16:9"
    resolution: Literal["720P", "1080P"] = "720P"
    scenario: Literal["short_drama", "video_edit", "general"] = "general"

    @model_validator(mode="after")
    def validate_package(self):
        for items in (self.characters, self.references):
            if len({item.id for item in items}) != len(items):
                raise ValueError("story item IDs must be unique")
        if len(canonical_json(self.model_dump(mode="json")).encode()) > 131072:
            raise ValueError("story package exceeds 128 KiB")
        return self

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))

    def content(self) -> bytes:
        return canonical_json(self.model_dump(mode="json")).encode()


class PrepareStoryInput(StoryModel):
    story: StoryPackage


class ReviseStoryInput(PrepareStoryInput):
    project_id: StoryId
    expected_story_digest: Annotated[
        str,
        Field(pattern=r"^[a-f0-9]{64}$"),
    ]
    expected_project_etag: Annotated[str, Field(min_length=1, max_length=256)]


class ProduceStoryInput(StoryModel):
    project_id: StoryId
    story_revision: int = Field(ge=1)
    story_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    expected_project_etag: Annotated[str, Field(min_length=1, max_length=256)]


class StoryReceipt(StoryModel):
    project_id: StoryId
    story_revision: int = Field(ge=1)
    story_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    project_etag: Annotated[str, Field(min_length=1, max_length=256)]
    project_generation: int = Field(ge=0)
