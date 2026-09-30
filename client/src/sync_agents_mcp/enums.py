from enum import StrEnum


class EVisibility(StrEnum):
    team = "team"
    private = "private"


class ETypeMessage(StrEnum):
    mudanca = "mudanca"
    pergunta = "pergunta"
    resposta = "resposta"
    decisao = "decisao"
    bloqueio = "bloqueio"


class EStatusTask(StrEnum):
    ideia = "ideia"
    parcial = "parcial"
    feito = "feito"
    bloqueado = "bloqueado"
    aguardando_decisao = "aguardando_decisao"


class EStatusProject(StrEnum):
    ativo = "ativo"
    pausado = "pausado"
    concluido = "concluido"
    arquivado = "arquivado"
