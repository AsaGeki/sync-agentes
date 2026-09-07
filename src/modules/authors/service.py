import sqlite3
from typing import Any

from src.modules.authors import repositorio
from src.modules.authors.models import AutorIn
from src.shared.enums import ETypeAuthor
from src.shared.erros import AlreadyExists, Invalid, NotFound


def create_author(conn: sqlite3.Connection, dados: AutorIn) -> dict[str, Any]:
    if dados.responsible_id is not None:
        resp = repositorio.find_by_id(conn, dados.responsible_id)
        if resp is None:
            raise NotFound(f"Responsável {dados.responsible_id} não cadastrado")
        if resp["type"] != ETypeAuthor.dev.value:
            raise Invalid(f"Responsável de uma IA tem que ser autor do tipo '{ETypeAuthor.dev}'")
    try:
        with conn:
            autor_id = repositorio.insert(conn, dados)
    except sqlite3.IntegrityError:
        raise AlreadyExists(f"Já existe autor com o nome '{dados.name}'") from None
    return {"id": autor_id, **dados.model_dump(mode="json")}


def list_authors(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(linha) for linha in repositorio.find_all(conn)]
