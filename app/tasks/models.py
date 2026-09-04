from pydantic import BaseModel, Field

from app.enums import EStatusTask, ETipoMensagem


class TaskIn(BaseModel):
    titulo: str = Field(min_length=1)
    codigo: str | None = None
    status: EStatusTask = EStatusTask.ideia
    etiquetas: list[str] = Field(default_factory=list)
    dono_id: int | None = None
    corpo: str | None = None


class TaskPatch(BaseModel):
    titulo: str | None = None
    status: EStatusTask | None = None
    etiquetas: list[str] | None = None
    dono_id: int | None = None


class MensagemIn(BaseModel):
    tipo: ETipoMensagem
    texto: str = Field(min_length=1)


class CorpoIn(BaseModel):
    texto: str


class DependenciaIn(BaseModel):
    depende_de: str = Field(min_length=1, description="codigo da task da qual esta depende")
