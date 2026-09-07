from pydantic import BaseModel, Field, model_validator

from src.shared.enums import ETypeAuthor


class AutorIn(BaseModel):
    type: ETypeAuthor
    name: str = Field(min_length=1)
    responsible_id: int | None = None

    @model_validator(mode="after")
    def validate_responsavel(self) -> "AutorIn":
        if self.type is ETypeAuthor.ia and self.responsible_id is None:
            raise ValueError(f"autor do tipo '{ETypeAuthor.ia}' precisa de responsible_id")
        if self.type is ETypeAuthor.dev and self.responsible_id is not None:
            raise ValueError(f"autor do tipo '{ETypeAuthor.dev}' não tem responsible_id")
        return self
