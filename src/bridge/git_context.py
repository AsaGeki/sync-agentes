"""Lê o contexto git do diretório onde o chat foi aberto.

O bridge roda como processo local e herda o cwd do cliente MCP - é daqui que sai
o escopo do canal, sem ninguém digitar nada e sem o modelo poder escolher outro.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContextoRepo:
    raiz: Path
    root_sha: str
    name: str
    remote: str | None
    branch: str | None
    commit_sha: str | None
    email: str | None
    user_name: str | None


def _git(*args: str, cwd: Path | None = None) -> str | None:
    try:
        saida = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if saida.returncode != 0:
        return None
    valor = saida.stdout.strip()
    return valor or None


BRANCHES_PRINCIPAIS = ("origin/HEAD", "origin/main", "origin/master", "main", "master")


def base_padrao(raiz: Path) -> str | None:
    """De onde comparar quando ninguém disse: o ponto em que a branch atual saiu
    da principal. Sem isso, um diff publicado mostraria o repositório inteiro."""
    for referencia in BRANCHES_PRINCIPAIS:
        base = _git("merge-base", "HEAD", referencia, cwd=raiz)
        if base:
            return base
    return None


def arquivos_alterados(raiz: Path, base: str) -> list[str]:
    saida = _git("diff", "--name-only", f"{base}..HEAD", cwd=raiz)
    return saida.splitlines() if saida else []


def patch(raiz: Path, base: str) -> str | None:
    return _git("diff", f"{base}..HEAD", cwd=raiz)


def descobrir(cwd: Path | None = None) -> ContextoRepo | None:
    """Devolve o contexto do repositório em `cwd`, ou None se não houver um
    (nem `.git`, nem git instalado, nem commit nenhum ainda)."""
    cwd = cwd or Path.cwd()
    raiz_bruta = _git("rev-parse", "--show-toplevel", cwd=cwd)
    if raiz_bruta is None:
        return None

    # Histórico com merge de repos separados tem mais de um commit raiz - a ordem
    # que o git devolve depende do caminho percorrido, então ordena pra chave ser
    # sempre a mesma em qualquer clone.
    raizes = _git("rev-list", "--max-parents=0", "HEAD", cwd=cwd)
    if raizes is None:
        return None
    root_sha = sorted(raizes.split())[0]

    raiz = Path(raiz_bruta)
    return ContextoRepo(
        raiz=raiz,
        root_sha=root_sha,
        name=raiz.name,
        remote=_git("remote", "get-url", "origin", cwd=cwd),
        branch=_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd),
        commit_sha=_git("rev-parse", "HEAD", cwd=cwd),
        email=_git("config", "user.email", cwd=cwd),
        user_name=_git("config", "user.name", cwd=cwd),
    )
