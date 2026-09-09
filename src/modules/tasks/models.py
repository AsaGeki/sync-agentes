from pydantic import BaseModel, Field

from src.shared.enums import EStatusTask, ETypeMessage


class TaskIn(BaseModel):
    title: str = Field(min_length=1)
    code: str | None = None
    status: EStatusTask = EStatusTask.ideia
    tags: list[str] = Field(default_factory=list)
    owner_id: int | None = None
    corpo: str | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    status: EStatusTask | None = None
    tags: list[str] | None = None
    owner_id: int | None = None


class MensagemIn(BaseModel):
    type: ETypeMessage
    texto: str = Field(min_length=1)


class CorpoIn(BaseModel):
    texto: str


class DiffIn(BaseModel):
    """Diff de código publicado numa task. O head é o commit do contexto git de
    quem publica (header `X-Git-Commit`), não vem no corpo."""

    base_sha: str = Field(min_length=7, max_length=40, pattern=r"^[0-9a-f]+$")
    arquivos: list[str] = Field(default_factory=list)
    patch: str | None = None
    resumo: str | None = None
    pedir_revisao: bool = False
