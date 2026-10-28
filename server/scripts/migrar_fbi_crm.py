"""Junta os projetos do FBI num projeto só, FBI-CRM, com cada módulo virando feature.

O projeto `gases` vira o `fbi-crm` (tasks e eventos dele não se movem) e
`emails`, `matriz-recorrencia` e `portal-institucional` entram nele como
features. As tasks movidas ganham número novo em sequência depois das do
gases; o slug no fim do code não muda. Citações de code antigas escritas em
corpo e mensagem ficam como estão: a descrição de cada feature traz a
conversão. Membros são somados (owner continua owner) e os projetos
esvaziados são apagados.

Uso:
    python scripts/migrar_fbi_crm.py           # lista o que mudaria
    python scripts/migrar_fbi_crm.py --apply   # grava (faz backup antes)

O banco é o mesmo da aplicação: `SYNC_AGENTS_DB` se definida, senão `sync.db`
na raiz do projeto. Rodar com o servidor parado e religar depois.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

from src.shared.codes import montar_code, numero_do_code
from src.shared.db import DB_PATH, now

ALVO = "gases"
NOVO_SLUG = "fbi-crm"
NOVO_NOME = "FBI-CRM"
NOVA_DESCRICAO = (
    "Sistema FBI (`fbi_back` + `fbi_front`). Cada módulo é uma feature deste projeto: "
    "venda e carregamento de gases industriais, templates e envio de email, matriz de "
    "recorrência de compras e portal institucional (área do cliente e do representante)."
)
# Ordem das features e da renumeração das tasks movidas.
MODULOS = ["gases", "emails", "matriz-recorrencia", "portal-institucional"]


def backup() -> str:
    destino = DB_PATH.with_name(f"{DB_PATH.name}.bak-fbi-crm-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(DB_PATH, destino)
    return str(destino)


def planejar(conn: sqlite3.Connection) -> dict:
    marcas = ",".join("?" * len(MODULOS))
    projetos = {p["slug"]: p for p in conn.execute(f"SELECT * FROM projects WHERE slug IN ({marcas})", MODULOS)}
    faltando = [slug for slug in MODULOS if slug not in projetos]
    if faltando:
        raise SystemExit(f"Projeto(s) não encontrado(s): {', '.join(faltando)}")
    ids = [p["id"] for p in projetos.values()]
    if conn.execute(f"SELECT COUNT(*) FROM features WHERE project_id IN ({marcas})", ids).fetchone()[0]:
        raise SystemExit("Algum dos projetos já tem feature; a migração supõe que nenhum tem.")

    alvo = projetos[ALVO]
    proximo = conn.execute(
        "SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) FROM tasks WHERE project_id = ?", (alvo["id"],)
    ).fetchone()[0] + 1

    features, tasks = [], []
    for posicao, slug in enumerate(MODULOS, start=1):
        projeto = projetos[slug]
        codigo_feature = montar_code(f"F-{posicao:03d}", projeto["name"])
        linhas = conn.execute(
            "SELECT id, code FROM tasks WHERE project_id = ? ORDER BY CAST(SUBSTR(code, 3) AS INTEGER)",
            (projeto["id"],),
        ).fetchall()
        conversao = []
        for linha in linhas:
            if slug == ALVO:
                novo = linha["code"]
            else:
                resto = linha["code"][len(numero_do_code(linha["code"], "T")):]
                novo = f"T-{proximo:03d}{resto}"
                proximo += 1
                conversao.append((numero_do_code(linha["code"], "T"), novo[:5]))
            tasks.append({"id": linha["id"], "de": f"{slug}/{linha['code']}", "code": novo, "feature": codigo_feature})
        descricao = projeto["description"] or ""
        if conversao:
            descricao += (
                f"\n\nTasks vindas do antigo projeto `{slug}`: {conversao[0][0]}..{conversao[-1][0]} "
                f"viraram {conversao[0][1]}..{conversao[-1][1]}, na mesma ordem. Citações de code "
                "no corpo e nas mensagens anteriores à junção usam a numeração antiga."
            )
        features.append({"code": codigo_feature, "title": projeto["name"], "description": descricao, "origem": slug})
    return {"projetos": projetos, "alvo": alvo, "features": features, "tasks": tasks}


def aplicar(conn: sqlite3.Connection, plano: dict) -> None:
    alvo = plano["alvo"]
    movidos = [plano["projetos"][slug] for slug in MODULOS if slug != ALVO]
    agora = now()
    with conn:
        conn.execute(
            "UPDATE projects SET slug = ?, name = ?, description = ?, updated_at = ? WHERE id = ?",
            (NOVO_SLUG, NOVO_NOME, NOVA_DESCRICAO, agora, alvo["id"]),
        )
        ids_feature = {}
        for f in plano["features"]:
            cursor = conn.execute(
                """INSERT INTO features (project_id, code, title, description, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (alvo["id"], f["code"], f["title"], f["description"], alvo["created_by"], agora, agora),
            )
            ids_feature[f["code"]] = cursor.lastrowid
        for t in plano["tasks"]:
            conn.execute(
                "UPDATE tasks SET project_id = ?, code = ?, feature_id = ? WHERE id = ?",
                (alvo["id"], t["code"], ids_feature[t["feature"]], t["id"]),
            )
        for projeto in movidos:
            conn.execute("UPDATE events SET project_id = ? WHERE project_id = ?", (alvo["id"], projeto["id"]))
            membros = conn.execute(
                "SELECT person_id, role, created_at FROM memberships WHERE project_id = ?", (projeto["id"],)
            ).fetchall()
            for m in membros:
                conn.execute(
                    "INSERT OR IGNORE INTO memberships (project_id, person_id, role, created_at) VALUES (?,?,?,?)",
                    (alvo["id"], m["person_id"], m["role"], m["created_at"]),
                )
                if m["role"] == "owner":
                    conn.execute(
                        "UPDATE memberships SET role = 'owner' WHERE project_id = ? AND person_id = ?",
                        (alvo["id"], m["person_id"]),
                    )
            repos = conn.execute(
                "SELECT root_sha, name, remote, created_at FROM project_repos WHERE project_id = ?", (projeto["id"],)
            ).fetchall()
            for r in repos:
                conn.execute(
                    "INSERT OR IGNORE INTO project_repos (root_sha, project_id, name, remote, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (r["root_sha"], alvo["id"], r["name"], r["remote"], r["created_at"]),
                )
            restantes = conn.execute(
                "SELECT (SELECT COUNT(*) FROM tasks WHERE project_id = ?)"
                " + (SELECT COUNT(*) FROM events WHERE project_id = ?)",
                (projeto["id"], projeto["id"]),
            ).fetchone()[0]
            if restantes:
                raise RuntimeError(f"{projeto['slug']} ainda tem {restantes} task/evento; nada foi gravado")
            conn.execute("DELETE FROM projects WHERE id = ?", (projeto["id"],))


def resumo(conn: sqlite3.Connection, rotulo: str) -> None:
    print(f"\n{rotulo}:")
    for p in conn.execute(
        """SELECT p.slug,
                  (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) AS tasks,
                  (SELECT COUNT(*) FROM features f WHERE f.project_id = p.id) AS features,
                  (SELECT COUNT(*) FROM events e WHERE e.project_id = p.id) AS eventos,
                  (SELECT COUNT(*) FROM memberships m WHERE m.project_id = p.id) AS membros,
                  (SELECT group_concat(name, ', ') FROM project_repos r WHERE r.project_id = p.id) AS repos
             FROM projects p ORDER BY p.id"""
    ):
        print(
            f"  {p['slug']:22s} tasks={p['tasks']:3d} features={p['features']} eventos={p['eventos']:4d}"
            f" membros={p['membros']} repos={p['repos']}"
        )


def main() -> int:
    if not DB_PATH.exists():
        print(f"Banco não encontrado: {DB_PATH}")
        return 1
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    print(f"Banco: {DB_PATH}")

    if conn.execute("SELECT 1 FROM projects WHERE slug = ?", (NOVO_SLUG,)).fetchone():
        print(f"Projeto '{NOVO_SLUG}' já existe: migração já aplicada, nada a fazer.")
        return 0

    plano = planejar(conn)
    resumo(conn, "Antes")
    print(f"\nProjeto '{ALVO}' vira '{NOVO_SLUG}' ({NOVO_NOME}). Features:")
    for f in plano["features"]:
        print(f"  {f['code']}  ({f['origem']})")
    print("\nTasks:")
    for t in plano["tasks"]:
        marca = "" if t["de"].split("/", 1)[1] == t["code"] else "  <- renumerada"
        print(f"  {t['de']:60s} -> {t['code'][:5]}  [{t['feature'][:5]}]{marca}")

    if "--apply" not in sys.argv[1:]:
        print("\nNada gravado. Rode com --apply pra aplicar.")
        return 0

    print(f"\nBackup: {backup()}")
    aplicar(conn, plano)
    resumo(conn, "Depois")
    return 0


if __name__ == "__main__":
    sys.exit(main())
