from enum import StrEnum


class ETipoAutor(StrEnum):
    ia = "ia"
    humano = "humano"


class ETipoMensagem(StrEnum):
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


class EStatusProjeto(StrEnum):
    ativo = "ativo"
    pausado = "pausado"
    concluido = "concluido"
    arquivado = "arquivado"


class EKindEvento(StrEnum):
    task_criada = "task_criada"
    mensagem = "mensagem"
    campo = "campo"
    corpo = "corpo"
    dependencia = "dependencia"
