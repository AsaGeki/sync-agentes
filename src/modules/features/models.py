from pydantic import BaseModel, Field


class FeatureIn(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None


class FeaturePatch(BaseModel):
    title: str | None = None
    description: str | None = None
