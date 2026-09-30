from enum import StrEnum

# Os enums que o cliente MCP usa moram em `sync_agents_mcp.enums`; reexportados aqui pros imports do servidor.
from sync_agents_mcp.enums import EStatusProject, EStatusTask, ETypeMessage, EVisibility

__all__ = [
    "EAgent",
    "EKindEvent",
    "ERequestStatus",
    "ERole",
    "EStatusProject",
    "EStatusTask",
    "ETypeMessage",
    "EVisibility",
]


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


class ERequestStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class EKindEvent(StrEnum):
    """Tipo do evento na trilha, no formato `<entidade>.<fato no passado>`."""

    task_created = "task.created"
    task_field_changed = "task.field_changed"
    body_updated = "body.updated"
    message_created = "message.created"
    diff_published = "diff.published"
    feature_created = "feature.created"
    feature_field_changed = "feature.field_changed"
    feature_deleted = "feature.deleted"
