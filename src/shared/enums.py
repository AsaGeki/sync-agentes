from enum import StrEnum


class ETypeAuthor(StrEnum):
    ia = "ia"
    dev = "dev"


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


class EKindEvent(StrEnum):
    task_criada = "task_criada"
    mensagem = "mensagem"
    campo = "campo"
    corpo = "corpo"
