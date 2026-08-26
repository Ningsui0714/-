from typing import Literal

from pydantic import BaseModel, Field


class ReviewSubmitRequest(BaseModel):
    expected_version: int = Field(ge=1)
    client_submission_id: str = Field(min_length=1, max_length=160)
    response_status: Literal["answered", "unknown", "skipped"] = "answered"
    answer_indexes: list[int] = Field(default_factory=list)
    answer_text: str = ""
    code: str = ""
    files: list[dict] = Field(default_factory=list)
    assistance_level: Literal["none", "hint", "guided"] = "none"
    presentation_version: str = Field(min_length=1, max_length=160)


class ReviewActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    client_event_id: str = Field(min_length=1, max_length=160)
