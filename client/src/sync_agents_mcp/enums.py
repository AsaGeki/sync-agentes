from enum import StrEnum


class EVisibility(StrEnum):
    """`public`: qualquer pessoa cadastrada vê o projeto e entra sozinha, com `join_project`.
    `private`: entra só quem um owner aceitar."""

    public = "public"
    private = "private"


class ETypeMessage(StrEnum):
    mudanca = "mudanca"
    pergunta = "pergunta"
    resposta = "resposta"
    decisao = "decisao"
    bloqueio = "bloqueio"


class EStatusTask(StrEnum):
    ideia = "ideia"
    em_andamento = "em_andamento"
    parcial = "parcial"
    feito = "feito"
    bloqueado = "bloqueado"
    aguardando_decisao = "aguardando_decisao"
    cancelada = "cancelada"


class EStatusProject(StrEnum):
    ativo = "ativo"
    pausado = "pausado"
    concluido = "concluido"
    arquivado = "arquivado"
