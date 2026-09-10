from enum import StrEnum


class EAgent(StrEnum):
    """Ferramenta pela qual a pessoa escreveu. Quem assina é sempre a pessoa
    (`people`); isto diz por onde."""

    claude = "claude"
    codex = "codex"
    human = "human"
    outro = "outro"


class ERole(StrEnum):
    owner = "owner"
    member = "member"


class EVisibility(StrEnum):
    team = "team"
    private = "private"


class ERequestStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


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
    """Tipo do evento na trilha, no formato `<entidade>.<fato no passado>`."""

    task_created = "task.created"
    task_field_changed = "task.field_changed"
    body_updated = "body.updated"
    message_created = "message.created"
    diff_published = "diff.published"
