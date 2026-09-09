from enum import StrEnum


class EAgent(StrEnum):
    """Ferramenta pela qual a pessoa escreveu. Não é quem assina - quem assina é
    sempre uma pessoa (`people`); isto é como ela escreveu."""

    claude = "claude"
    codex = "codex"
    cursor = "cursor"
    copilot = "copilot"
    human = "human"
    outro = "outro"


class ERole(StrEnum):
    owner = "owner"
    member = "member"


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


class EKindEvent(StrEnum):
    """Tipo do evento na trilha. `<entidade>.<fato no passado>` - é o que um
    consumidor externo (tela, auditoria) lê sem conhecer o interno daqui."""

    task_created = "task.created"
    task_field_changed = "task.field_changed"
    body_updated = "body.updated"
    message_created = "message.created"
    diff_published = "diff.published"
