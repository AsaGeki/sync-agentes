"""Monta o pacote de sincronização para projetos que já existem no sistema de destino."""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from src.modules.projects.exportacao import COLECOES, STATUS, TIPOS
from src.shared.enums import EAgent, EKindEvent


def normalizar_url(valor):
    return (valor or "").strip().lower().rstrip("/")


def mesmo_repositorio(origem, destino):
    # URL igual, ou mesmo nome com o mesmo commit raiz (a URL pode variar entre origem e destino).
    git = destino.get("git") or {}
    url = normalizar_url(origem["remote"])
    if url and url in {normalizar_url(destino.get("url")), normalizar_url(git.get("canonicalRemoteUrl"))}:
        return True
    return (
        destino["name"].lower() == origem["name"].lower()
        and str(git.get("rootCommit") or "").lower() == origem["root_sha"].lower()
    )


def candidatas_por_tag(tags, repos):
    # Mesma regra da tela de exportação: tag igual ao nome do repositório, ou backend/frontend contra back/front.
    achadas = []
    for repo in repos:
        palavras = set(re.split(r"[^a-z0-9]+", repo["name"].lower()))
        motivos = [tag for tag in tags if tag.lower() == repo["name"].lower()]
        if not motivos:
            motivos = [
                tag
                for tag in tags
                if (tag.lower() == "backend" and palavras & {"back", "backend"})
                or (tag.lower() in ("frontend", "front") and palavras & {"front", "frontend"})
            ]
        if motivos:
            achadas.append(repo)
    return achadas


def resolver_repositorio(tags, repos, manual=None, padrao=None):
    """Repositório de origem de uma task e como foi escolhido: à mão, pela tag ou pelo padrão do projeto.

    `manual` e `padrao` são root_sha. Sem nenhuma pista devolve (None, None).
    """
    por_raiz = {r["root_sha"]: r for r in repos}
    if manual in por_raiz:
        return por_raiz[manual], "manual"
    achadas = candidatas_por_tag(tags, repos)
    if len(achadas) == 1:
        return achadas[0], "tag"
    if padrao in por_raiz:
        return por_raiz[padrao], "padrao"
    return None, None


def area_e_tipo(tags):
    areas = {"backend" for tag in tags if tag == "backend"} | {
        "frontend" for tag in tags if tag in ("frontend", "front")
    }
    tipos = TIPOS.intersection(tags)
    return (next(iter(areas)) if len(areas) == 1 else "outro"), (next(iter(tipos)) if len(tipos) == 1 else "feature")


def resumo_evento(e, task):
    if e["kind"] == EKindEvent.task_created:
        return f"Tarefa criada: {task['code']}"
    if e["kind"] == EKindEvent.task_field_changed:
        return f"Campo {e['campo']} alterado: {e['valor_de']} → {e['valor_para']}"
    if e["kind"] == EKindEvent.body_updated:
        return f"Corpo atualizado (versão {e['version']})"
    if e["kind"] == EKindEvent.message_created:
        return f"Mensagem ({e['type']})"
    return f"Evento da origem: {e['kind']}"


def vincular_respostas(mensagens):
    # Cada resposta aponta para a pergunta mais antiga ainda sem resposta na mesma task.
    abertas, vinculos = {}, {}
    for m in mensagens:
        if m["type"] == "pergunta":
            abertas.setdefault(m["task_id"], []).append(m["seq"])
        elif m["type"] == "resposta" and abertas.get(m["task_id"]):
            vinculos[m["seq"]] = abertas[m["task_id"]].pop(0)
    return vinculos


def _namespace(projeto):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"sync-agents:{projeto['id']}:{projeto['created_at']}")


def uuid_da_task(projeto, task_id):
    """O ID que a task tem no destino."""
    return str(uuid.uuid5(_namespace(projeto), f"task:{task_id}"))


def tasks_donas(conn, project_id, person_id):
    """Tasks que a pessoa pode alterar no destino: as dela e as que criou quando não têm dono."""
    linhas = conn.execute(
        """SELECT t.id FROM tasks t
            WHERE t.project_id = :projeto
              AND (t.owner_id = :pessoa
                   OR (t.owner_id IS NULL AND EXISTS (SELECT 1 FROM events e
                                                       WHERE e.task_id = t.id AND e.kind = 'task.created'
                                                         AND e.author_id = :pessoa)))""",
        {"projeto": project_id, "pessoa": person_id},
    )
    return {linha["id"] for linha in linhas}


def tasks_da_pessoa(conn, project_id, person_id):
    """Tasks do projeto em que a pessoa participa e o conjunto fechado pelas dependências.

    Participar é ser dono, ter criado a task ou ter escrito alguma mensagem nela. Devolve
    (proprias, escopo): `escopo` acrescenta as tasks de que as próprias dependem, direta ou indiretamente.
    """
    proprias = {
        linha["id"]
        for linha in conn.execute(
            """SELECT t.id FROM tasks t
                WHERE t.project_id = :projeto
                  AND (t.owner_id = :pessoa
                       OR EXISTS (SELECT 1 FROM events e
                                   WHERE e.task_id = t.id AND e.author_id = :pessoa
                                     AND e.kind IN ('task.created', 'message.created')))""",
            {"projeto": project_id, "pessoa": person_id},
        )
    }
    dependencias = {}
    for linha in conn.execute(
        "SELECT d.task_id, d.depends_on_id FROM task_dependencies d JOIN tasks t ON t.id = d.task_id "
        "WHERE t.project_id = ?",
        (project_id,),
    ):
        dependencias.setdefault(linha["task_id"], []).append(linha["depends_on_id"])
    escopo, fila = set(proprias), list(proprias)
    while fila:
        for dependencia in dependencias.get(fila.pop(), []):
            if dependencia not in escopo:
                escopo.add(dependencia)
                fila.append(dependencia)
    return proprias, escopo


def montar_pacote(conn, projeto, destino, vinculos, padrao=None, manuais=None, escopo=None):
    """`vinculos` é root_sha -> id do repositório no destino; `padrao` é um root_sha; `manuais`, task id -> root_sha.

    `escopo` limita o pacote a um conjunto de tasks (já fechado pelas dependências), com suas features, mensagens,
    corpos e eventos; sem ele o pacote leva o projeto inteiro.
    """
    manuais = manuais or {}
    namespace = _namespace(projeto)

    def id_de(tipo, valor):
        return str(uuid.uuid5(namespace, f"{tipo}:{valor}"))

    projeto_id = destino["_id"]
    repos = conn.execute("SELECT * FROM project_repos WHERE project_id = ? ORDER BY name", (projeto["id"],)).fetchall()
    destino_por_id = {x["id"]: x for x in destino["repositories"]}
    destino_por_raiz = {raiz: destino_por_id[id_] for raiz, id_ in vinculos.items() if id_ in destino_por_id}
    features = conn.execute(
        "SELECT f.*, p.email AS creator_email FROM features f JOIN people p ON p.id = f.created_by "
        "WHERE f.project_id = ? ORDER BY f.id",
        (projeto["id"],),
    ).fetchall()
    tasks = conn.execute(
        "SELECT t.*, p.email AS owner_email FROM tasks t LEFT JOIN people p ON p.id = t.owner_id "
        "WHERE t.project_id = ? ORDER BY t.id",
        (projeto["id"],),
    ).fetchall()
    eventos = conn.execute(
        "SELECT e.*, p.email AS author_email FROM events e JOIN people p ON p.id = e.author_id "
        "WHERE e.project_id = ? ORDER BY e.seq",
        (projeto["id"],),
    ).fetchall()
    dependencias = conn.execute(
        "SELECT d.* FROM task_dependencies d JOIN tasks t ON t.id = d.task_id WHERE t.project_id = ? "
        "ORDER BY d.task_id, d.depends_on_id",
        (projeto["id"],),
    ).fetchall()
    if escopo is not None:
        tasks = [t for t in tasks if t["id"] in escopo]
        dependencias = [d for d in dependencias if d["task_id"] in escopo]
        das_features = {t["feature_id"] for t in tasks if t["feature_id"] is not None}
        features = [f for f in features if f["id"] in das_features]
        eventos = [
            e for e in eventos if e["task_id"] in escopo or (e["task_id"] is None and e["feature_id"] in das_features)
        ]
    tarefa_por_id = {t["id"]: t for t in tasks}
    deps = {
        t["id"]: [id_de("task", d["depends_on_id"]) for d in dependencias if d["task_id"] == t["id"]] for t in tasks
    }

    sem_repositorio, resolucao = [], {"tag": 0, "manual": 0, "padrao": 0}
    repositorio_da_task = {}
    for t in tasks:
        escolhido, via = resolver_repositorio(json.loads(t["tags"]), repos, manuais.get(t["id"]), padrao)
        if escolhido is None or escolhido["root_sha"] not in destino_por_raiz:
            sem_repositorio.append(t["code"])
            continue
        resolucao[via] += 1
        repositorio_da_task[t["id"]] = destino_por_raiz[escolhido["root_sha"]]["id"]
    if sem_repositorio:
        raise ValueError(
            f"{len(sem_repositorio)} tasks sem repositório vinculado no destino "
            f"(ex.: {', '.join(sem_repositorio[:3])})."
        )

    dados = {nome: [] for nome in COLECOES}
    for f in features:
        dados["features"].append(
            {
                "_id": id_de("feature", f["id"]),
                "projectId": projeto_id,
                "name": f["title"],
                "objective": f["description"] or "",
                "context": f"Código na origem: {f['code']}\nCriado por: {f['creator_email']}",
                "acceptance": [],
                "version": 0,
                "archived": False,
                "createdAt": f["created_at"],
                "updatedAt": f["updated_at"],
            }
        )
    corpos = {}
    for e in eventos:
        if e["kind"] == EKindEvent.body_updated:
            corpos.setdefault(e["task_id"], []).append(e)
    areas_usadas = set()
    for t in tasks:
        tags = json.loads(t["tags"])
        area, tipo = area_e_tipo(tags)
        areas_usadas.add(area)
        instrucoes = f"Código na origem: {t['code']}\nStatus na origem: {t['status']}\nTags: {', '.join(tags)}"
        if corpos.get(t["id"]):
            instrucoes += f"\n\n{corpos[t['id']][-1]['texto']}"
        registro = {
            "_id": id_de("task", t["id"]),
            "projectId": projeto_id,
            "name": t["title"],
            "instructions": instrucoes,
            "acceptance": [],
            "acceptanceProgress": [],
            "priority": 0,
            "area": area,
            "type": tipo,
            "repositoryId": repositorio_da_task[t["id"]],
            "dependencies": deps[t["id"]],
            "status": STATUS[t["status"]],
            "checked": False,
            "version": 0,
            "archived": False,
            "createdAt": t["created_at"],
            "updatedAt": t["updated_at"],
        }
        if t["feature_id"] is not None:
            registro["featureId"] = id_de("feature", t["feature_id"])
        if t["owner_email"]:
            registro["responsible"] = t["owner_email"]
        dados["tasks"].append(registro)
    for d in dependencias:
        dados["taskDependencies"].append(
            {
                "_id": id_de("dependency", f"{d['task_id']}:{d['depends_on_id']}"),
                "projectId": projeto_id,
                "taskId": id_de("task", d["task_id"]),
                "dependencyId": id_de("task", d["depends_on_id"]),
            }
        )

    mensagens = [e for e in eventos if e["kind"] == EKindEvent.message_created and e["task_id"] is not None]
    respostas = vincular_respostas(mensagens)
    for e in eventos:
        detalhe = {k: e[k] for k in e.keys() if k not in {"project_id", "author_id", "author_name", "author_email"}}
        if e["task_id"] is not None:
            entidade, task = id_de("task", e["task_id"]), tarefa_por_id[e["task_id"]]
        else:
            entidade, task = (id_de("feature", e["feature_id"]) if e["feature_id"] else projeto_id), None
        dados["events"].append(
            {
                "_id": id_de("event", e["seq"]),
                "projectId": projeto_id,
                "entityId": entidade,
                "action": e["kind"],
                "kind": e["kind"],
                "summary": resumo_evento(e, task) if task else f"Evento da origem: {e['kind']}",
                "author": e["author_email"],
                "origin": "sync-agents",
                "at": e["created_at"],
                "data": detalhe,
            }
        )
    for e in mensagens:
        mensagem = {
            "_id": id_de("message", e["seq"]),
            "projectId": projeto_id,
            "taskId": id_de("task", e["task_id"]),
            "author": e["author_email"],
            "clientName": e["agent"],
            "type": e["type"],
            "message": e["texto"],
            "references": [],
            "createdAt": e["created_at"],
        }
        if e["seq"] in respostas:
            mensagem["replyTo"] = id_de("message", respostas[e["seq"]])
        if e["agent"] in (EAgent.human, EAgent.codex, EAgent.claude):
            mensagem["authorType"] = "human" if e["agent"] == EAgent.human else "agent"
        dados["taskMessages"].append(mensagem)

    for task_id, versoes in corpos.items():
        documento = id_de("document", task_id)
        dados["markdownDocuments"].append(
            {
                "_id": documento,
                "projectId": projeto_id,
                "targetKind": "task",
                "targetId": id_de("task", task_id),
                "name": "Corpo (sync-agents).md",
                "summary": "Histórico do corpo da task no sync-agents",
                "revision": len(versoes),
                "author": versoes[-1]["author_email"],
                "version": 0,
                "archived": False,
                "createdAt": versoes[0]["created_at"],
                "updatedAt": versoes[-1]["created_at"],
            }
        )
        for numero, v in enumerate(versoes, 1):
            dados["markdownRevisions"].append(
                {
                    "_id": id_de("revision", v["seq"]),
                    "projectId": projeto_id,
                    "documentId": documento,
                    "revision": numero,
                    "summary": f"Versão {v['version']} no sync-agents",
                    "content": v["texto"],
                    "author": v["author_email"],
                    "createdAt": v["created_at"],
                }
            )

    # O destino só aceita áreas já cadastradas; o importador acrescenta as que faltarem.
    existentes = {a.lower() for a in destino["areas"]}
    areas = list(destino["areas"]) + sorted(a for a in areas_usadas if a.lower() not in existentes)
    dados["project"] = {
        "_id": projeto_id,
        "name": destino["name"],
        "description": destino.get("description") or "",
        "instructions": destino.get("instructions") or "",
        "visibility": destino["visibility"],
        "archived": False,
        "version": 0,
        "eventSequence": 0,
        "repositories": destino["repositories"],
        "areas": areas,
        "createdAt": destino["createdAt"],
        "updatedAt": destino["updatedAt"],
    }
    contagens = {"project": 1, "repositories": len(destino["repositories"])}
    contagens.update({nome: len(dados[nome]) for nome in COLECOES})
    pacote = {
        "format": "project-tasks-export",
        "schemaVersion": 1,
        "exportedAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "source": {"projectId": projeto_id},
        "counts": contagens,
        "data": dados,
        "migrationInstructions": "Pacote de sincronização do sync-agents para um projeto já existente.",
        "exclusions": ["Credenciais, tokens, permissões, pedidos de acesso e cursores de leitura"],
    }
    relatorio = {
        "projeto_sync": projeto["slug"],
        "projeto_destino": f"{destino['name']} ({projeto_id})",
        "repositorios": {
            r["name"]: destino_por_raiz[r["root_sha"]]["name"] if r["root_sha"] in destino_por_raiz else None
            for r in repos
        },
        "repositorio_das_tasks": resolucao,
        "perguntas": sum(1 for m in mensagens if m["type"] == "pergunta"),
        "respostas_vinculadas": len(respostas),
        "areas_acrescentadas": areas[len(destino["areas"]) :],
        "digest_origem": hashlib.sha256(json.dumps(dados, sort_keys=True).encode("utf-8")).hexdigest()[:12],
        "contagens": {k: v for k, v in contagens.items() if v},
    }
    return pacote, relatorio


PATCH_REPLYTO = """// Preenche replyTo em mensagens de task já importadas. Gerado pela tela de sincronização.
// Uso: mongosh "<MONGODB_URI>" --file <este arquivo>. Sem APLICAR=1 só conta; faça mongodump antes de gravar.
const pares = __PARES__;
const colecao = db.getCollection("taskmessages");
const gravar = process.env.APLICAR === "1";
const ids = pares.flatMap((p) => [p._id, p.replyTo]);
const existentes = new Map(
  colecao.find({ _id: { $in: ids } }, { projectId: 1, replyTo: 1 }).toArray().map((d) => [d._id, d])
);
const operacoes = [];
const resumo = { pares: pares.length, ausentes: 0, ja_tem_replyTo: 0, alvo_ausente: 0, a_gravar: 0 };
for (const p of pares) {
  const atual = existentes.get(p._id);
  if (!atual || atual.projectId !== p.projectId) { resumo.ausentes++; continue; }
  if (atual.replyTo) { resumo.ja_tem_replyTo++; continue; }
  if (!existentes.has(p.replyTo)) { resumo.alvo_ausente++; continue; }
  resumo.a_gravar++;
  operacoes.push({ updateOne: {
    filter: { _id: p._id, projectId: p.projectId, replyTo: null },
    update: { $set: { replyTo: p.replyTo } },
  } });
}
if (gravar && operacoes.length) resumo.gravadas = colecao.bulkWrite(operacoes, { ordered: false }).modifiedCount;
console.log(JSON.stringify(resumo));
if (!gravar) console.log("Prévia: nada foi gravado. Use APLICAR=1 para gravar.");
"""


def gerar_patch_replyto(pacotes):
    pares = [
        {"_id": m["_id"], "projectId": m["projectId"], "replyTo": m["replyTo"]}
        for pacote in pacotes
        for m in pacote["data"]["taskMessages"]
        if "replyTo" in m
    ]
    return PATCH_REPLYTO.replace("__PARES__", json.dumps(pares, ensure_ascii=False)), len(pares)
