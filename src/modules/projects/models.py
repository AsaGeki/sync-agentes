from pydantic import BaseModel, Field

from src.shared.enums import EStatusProject


class ProjetoIn(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    description: str | None = None
    git_repositories: list[str] = Field(default_factory=list)
    status: EStatusProject = EStatusProject.ativo


class ProjetoPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    git_repositories: list[str] | None = None
    status: EStatusProject | None = None
