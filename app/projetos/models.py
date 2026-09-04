from pydantic import BaseModel, Field

from app.enums import EStatusProjeto


class ProjetoIn(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    nome: str = Field(min_length=1)
    descricao: str | None = None
    status: EStatusProjeto = EStatusProjeto.ativo


class ProjetoPatch(BaseModel):
    nome: str | None = None
    descricao: str | None = None
    status: EStatusProjeto | None = None
