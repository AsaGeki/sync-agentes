"""Leitura, plano e aplicação da sincronização no sistema de destino (HTTP admin, credencial humana)."""

import json
import re
import urllib.error
import urllib.request
import uuid

# Transições que a rota de status do destino aceita para uma credencial humana.
TRANSICOES = {
    "pendente": ["em_revisao", "concluida", "cancelada"],
    "bloqueada": ["pendente", "em_revisao", "concluida", "cancelada"],
    "em_revisao": ["pendente", "concluida", "cancelada"],
    "concluida": ["pendente"],
}
TERMINAIS = {"concluida", "cancelada"}
# Tamanho máximo que a rota de edição do destino aceita em nome e instruções (a importação não tem esse limite).
LIMITE_TEXTO = 20000
# O destino aplica a mesma remoção de segredos na importação; a edição precisa aplicá-la também.
PADROES_SEGREDO = [
    (re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"), "[REDACTED]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]+)\b"), "[REDACTED]"),
    (re.compile(r"([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", re.I), r"\1[REDACTED]@"),
    (
        re.compile(
            r"""((?:[\w-]*(?:token|password|secret|api[_-]?key)[\w-]*)["']?\s*[:=]\s*["']?)[^\s"'&,}\r\n]+""", re.I
        ),
        r"\1[REDACTED]",
    ),
]


class ErroDestino(Exception):
    def __init__(self, status, mensagem):
        super().__init__(f"{status}: {mensagem}")
        self.status = status


def redigir(texto):
    for padrao, troca in PADROES_SEGREDO:
        texto = padrao.sub(troca, texto)
    return texto


class ClienteDestino:
    def __init__(self, url, token):
        self.base = url.rstrip("/")
        self.token = token

    def post(self, caminho, corpo, timeout=120):
        pedido = urllib.request.Request(
            f"{self.base}{caminho}",
            data=json.dumps(corpo).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
                return json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            try:
                mensagem = json.loads(erro.read()).get("error", "")
            except ValueError:
                mensagem = ""
            raise ErroDestino(erro.code, mensagem or str(erro.reason)) from erro

    def get(self, caminho, timeout=60):
        pedido = urllib.request.Request(
            f"{self.base}{caminho}", method="GET", headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
                return json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            try:
                mensagem = json.loads(erro.read()).get("error", "")
            except ValueError:
                mensagem = ""
            raise ErroDestino(erro.code, mensagem or str(erro.reason)) from erro

    def listar(self, kind, **filtros):
        itens, depois = [], None
        while True:
            argumentos = {"kind": kind, "limit": 100, **filtros}
            if depois:
                argumentos["after"] = depois
            pagina = self.post("/admin/query", {"tool": "list_records", "arguments": argumentos})
            itens += pagina["items"]
            depois = pagina.get("next")
            if not depois:
                return itens


def caminho_status(origem, alvo):
    # Menor sequência de transições permitidas (no máximo duas) entre dois status.
    if alvo in TRANSICOES.get(origem, []):
        return [alvo]
    for meio in TRANSICOES.get(origem, []):
        if alvo in TRANSICOES.get(meio, []):
            return [meio, alvo]
    return None


def planejar(pacote, tasks_destino, editaveis=None):
    """O que mudaria no destino. `editaveis` são os IDs das tasks que quem sincroniza pode alterar; as outras
    tasks que já existem no destino ficam como estão (sem ele, todas são editáveis)."""
    por_id = {t["_id"]: t for t in tasks_destino}
    ids_sync = {t["_id"] for t in pacote["data"]["tasks"]}
    plano = {"novas": 0, "iguais": 0, "de_outros": 0, "edicoes": [], "status": [], "ignoradas": []}
    for desejada in pacote["data"]["tasks"]:
        atual = por_id.get(desejada["_id"])
        codigo = desejada["instructions"].split("\n", 1)[0].removeprefix("Código na origem: ")
        if atual is None:
            plano["novas"] += 1
            continue
        if editaveis is not None and desejada["_id"] not in editaveis:
            plano["de_outros"] += 1
            continue
        if atual["status"] == "em_execucao":
            plano["ignoradas"].append({"task": codigo, "motivo": "em execução no destino"})
            continue
        campos, texto_grande = {}, False
        for campo in ("name", "instructions"):
            valor = redigir(desejada[campo])
            if valor == atual.get(campo):
                continue
            if len(valor) > LIMITE_TEXTO:
                texto_grande = True
                plano["ignoradas"].append(
                    {
                        "task": codigo,
                        "motivo": f"{campo} passa de {LIMITE_TEXTO:,} caracteres: texto não atualizado".replace(
                            ",", "."
                        ),
                    }
                )
                continue
            campos[campo] = valor
        if desejada.get("responsible") and desejada["responsible"] != atual.get("responsible"):
            campos["responsible"] = desejada["responsible"]
        # Dependências que apontam para fora do sync foram criadas no destino e são preservadas.
        nativas = [d for d in atual.get("dependencies", []) if d not in ids_sync]
        dependencias = desejada["dependencies"] + nativas
        if set(dependencias) != set(atual.get("dependencies", [])):
            campos["dependencies"] = dependencias
        if desejada.get("featureId") != atual.get("featureId"):
            campos["featureId"] = desejada.get("featureId")
        if campos:
            plano["edicoes"].append({"task": codigo, "id": atual["_id"], "campos": campos})
        alvo = desejada["status"]
        if alvo == atual["status"]:
            if not campos and not texto_grande:
                plano["iguais"] += 1
            continue
        if atual["status"] == "em_revisao":
            plano["ignoradas"].append({"task": codigo, "motivo": "em revisão no destino; status não alterado"})
        elif atual["status"] in TERMINAIS and alvo not in TERMINAIS:
            plano["ignoradas"].append({"task": codigo, "motivo": f"{atual['status']} no destino; não reaberta"})
        elif (caminho := caminho_status(atual["status"], alvo)) is None:
            plano["ignoradas"].append({"task": codigo, "motivo": f"{atual['status']} → {alvo} não é permitido"})
        else:
            plano["status"].append({"task": codigo, "id": atual["_id"], "de": atual["status"], "caminho": caminho})
    return plano


def resumo_plano(plano):
    return {
        "tasks_novas": plano["novas"],
        "tasks_iguais": plano["iguais"],
        "tasks_de_outros": plano["de_outros"],
        "edicoes": len(plano["edicoes"]),
        "campos_editados": sorted({c for e in plano["edicoes"] for c in e["campos"]}),
        "mudancas_de_status": len(plano["status"]),
        "ignoradas": plano["ignoradas"][:20],
        "ignoradas_total": len(plano["ignoradas"]),
    }


def aplicar_plano(cliente, projeto_id, plano, tasks_destino):
    inicial = {t["_id"]: t["version"] for t in tasks_destino}
    versoes = dict(inicial)
    falhas, editadas, trocadas = [], 0, 0
    com_falha = set()
    for edicao in plano["edicoes"]:
        corpo = {
            "operationId": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{edicao['id']}:{versoes[edicao['id']]}:{edicao['campos']}")
            ),
            "projectId": projeto_id,
            "kind": "task",
            "id": edicao["id"],
            "version": versoes[edicao["id"]],
            "data": edicao["campos"],
        }
        try:
            versoes[edicao["id"]] = cliente.post("/admin/records/edit", corpo)["version"]
            editadas += 1
        except ErroDestino as erro:
            com_falha.add(edicao["id"])
            falhas.append({"task": edicao["task"], "etapa": "edição", "erro": str(erro)})
    for mudanca in plano["status"]:
        if mudanca["id"] in com_falha:
            continue
        origem = mudanca["de"]
        for passo in mudanca["caminho"]:
            corpo = {
                "operationId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mudanca['id']}:{versoes[mudanca['id']]}:{passo}")),
                "projectId": projeto_id,
                "taskId": mudanca["id"],
                "version": versoes[mudanca["id"]],
                "status": passo,
                "reason": f"Sincronização com o sync-agents: {origem} → {passo}",
            }
            try:
                versoes[mudanca["id"]] = cliente.post("/admin/tasks/status", corpo)["task"]["version"]
            except ErroDestino as erro:
                falhas.append({"task": mudanca["task"], "etapa": "status", "erro": str(erro)})
                break
            origem = passo
        else:
            trocadas += 1
    alteradas = {id_: (inicial[id_], versao) for id_, versao in versoes.items() if versao != inicial[id_]}
    return {"editadas": editadas, "status_alterados": trocadas, "falhas": falhas, "alteradas": alteradas}


def _historico_da_task(cliente, projeto_id, task_id, paginas=10):
    depois = None
    for _ in range(paginas):
        argumentos = {"projectId": projeto_id, "entityId": task_id, "limit": 100}
        if depois:
            argumentos["after"] = depois
        pagina = cliente.post("/admin/query", {"tool": "get_history", "arguments": argumentos})
        yield from pagina["items"]
        depois = pagina.get("next")
        if not depois:
            return


def conferir_autoria(cliente, projeto_id, alteradas, limite=60):
    """Quem o destino registrou como autor das mudanças que acabamos de fazer.

    `alteradas` é task id -> (versão antes, versão depois). Cada evento de edição ou de status guarda a versão
    que a task passou a ter, o que liga o evento à nossa chamada. Confere até `limite` tasks.
    """
    autores, conferidas = {}, 0
    for task_id, (antes, depois) in list(alteradas.items())[:limite]:
        for evento in _historico_da_task(cliente, projeto_id, task_id):
            if evento.get("action") not in ("edit_record", "manual_status_change"):
                continue
            dados = evento.get("data") or {}
            versao = (
                (dados.get("task") or {}).get("version")
                if evento["action"] == "manual_status_change"
                else dados.get("version")
            )
            if versao is not None and antes < versao <= depois:
                autor = evento.get("author") or "desconhecido"
                autores[autor] = autores.get(autor, 0) + 1
        conferidas += 1
    return {"autores": autores, "conferidas": conferidas, "total": len(alteradas)}
