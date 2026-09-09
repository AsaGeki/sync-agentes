from pydantic import BaseModel, Field


class PessoaIn(BaseModel):
    # Chave da pessoa, vinda do `git config user.email` de quem conecta.
    email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1)
