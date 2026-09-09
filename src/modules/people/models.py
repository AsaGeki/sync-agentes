from pydantic import BaseModel, Field


class PessoaIn(BaseModel):
    # Email vem do `git config user.email` da máquina de quem conecta - é a
    # chave da pessoa, e é por ela que o cadastro é reaproveitado no lugar de
    # duplicar quem já existe.
    email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1)
