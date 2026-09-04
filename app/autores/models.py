from pydantic import BaseModel, Field, model_validator

from app.enums import ETipoAutor


class AutorIn(BaseModel):
    tipo: ETipoAutor
    nome: str = Field(min_length=1)
    responsavel_id: int | None = None

    @model_validator(mode="after")
    def validar_responsavel(self) -> "AutorIn":
        if self.tipo is ETipoAutor.ia and self.responsavel_id is None:
            raise ValueError("autor do tipo 'ia' precisa de responsavel_id")
        if self.tipo is ETipoAutor.humano and self.responsavel_id is not None:
            raise ValueError("autor do tipo 'humano' nao tem responsavel_id")
        return self
