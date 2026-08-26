from typing import Literal

from pydantic import BaseModel, Field, field_validator


EducationStage = Literal[
    "middle_school", "high_school", "undergraduate", "graduate", "working", "other",
]
CareerGoalStatus = Literal["exploring", "confirmed"]


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=40)
    education_stage: EducationStage
    background: str = Field(min_length=1, max_length=500)
    focus_areas: list[str] = Field(min_length=1, max_length=5)
    weekly_hours: int = Field(ge=1, le=80)
    preferred_modes: list[str] = Field(min_length=1, max_length=6)
    career_goal: str = Field(default="", max_length=200)
    career_goal_status: CareerGoalStatus = "exploring"

    @field_validator("focus_areas", "preferred_modes")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip()[:50] for value in values if str(value).strip()]
        return list(dict.fromkeys(cleaned))

    @field_validator("career_goal_status")
    @classmethod
    def valid_career_status(cls, value: str, info):
        career_goal = str(info.data.get("career_goal") or "").strip()
        if value == "confirmed" and not career_goal:
            raise ValueError("确认职业理想前需要填写目标")
        return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    education_stage: EducationStage | None = None
    background: str | None = Field(default=None, min_length=1, max_length=500)
    focus_areas: list[str] | None = Field(default=None, min_length=1, max_length=5)
    weekly_hours: int | None = Field(default=None, ge=1, le=80)
    preferred_modes: list[str] | None = Field(default=None, min_length=1, max_length=6)
    career_goal: str | None = Field(default=None, max_length=200)
    career_goal_status: CareerGoalStatus | None = None


class MemoryArchiveRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
