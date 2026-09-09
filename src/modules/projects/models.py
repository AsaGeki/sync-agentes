from pydantic import BaseModel, Field

from src.shared.enums import EStatusProject, EVisibility


class RepoIn(BaseModel):
    """Identificação de um repositório git. `root_sha` é o sha do commit raiz -
    igual em todo clone, não muda com rename de pasta nem troca de remote."""

    root_sha: str = Field(min_length=7, max_length=40, pattern=r"^[0-9a-f]+$")
    name: str = Field(min_length=1)
    remote: str | None = None


class ProjetoPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: EStatusProject | None = None
    visibility: EVisibility | None = None


class ConviteIn(BaseModel):
    email: str = Field(min_length=3)
