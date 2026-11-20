import sqlite3
from contextlib import closing
from typing import Any

from fastapi import APIRouter, Depends

from src.modules.features import service
from src.modules.features.models import FeatureIn, FeaturePatch
from src.shared.auth import ContextoGit, contexto_git, pessoa_atual
from src.shared.db import conectar

router = APIRouter()


@router.post("/projetos/{slug}/features", status_code=201)
def create_feature(
    slug: str,
    dados: FeatureIn,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    with closing(conectar()) as conn:
        return service.create_feature(conn, slug, pessoa["id"], ctx, dados)


@router.get("/projetos/{slug}/features")
def list_features(
    slug: str, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> list[dict[str, Any]]:
    with closing(conectar()) as conn:
        return service.list_features(conn, slug, pessoa["id"])


@router.get("/projetos/{slug}/features/{code}")
def read_feature(
    slug: str, code: str, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    with closing(conectar()) as conn:
        return service.read_feature(conn, slug, pessoa["id"], code)


@router.patch("/projetos/{slug}/features/{code}")
def update_feature(
    slug: str,
    code: str,
    dados: FeaturePatch,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    with closing(conectar()) as conn:
        return service.update_feature(conn, slug, code, pessoa["id"], ctx, dados)


@router.delete("/projetos/{slug}/features/{code}")
def delete_feature(
    slug: str,
    code: str,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    with closing(conectar()) as conn:
        return service.delete_feature(conn, slug, code, pessoa["id"], ctx)
