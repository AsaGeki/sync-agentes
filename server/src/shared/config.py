from pathlib import Path

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PASTA_SERVER = Path(__file__).resolve().parent.parent.parent


class Configuracao(BaseSettings):
    """Variáveis do ambiente, com o `.env` da pasta do servidor como fallback."""

    model_config = SettingsConfigDict(
        env_file=PASTA_SERVER / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    host: str = "127.0.0.1"
    port: int = 8787
    # Gerencia people e projetos. Pela interface web (`/web/admin`) também lê
    # qualquer projeto e gerencia membros; não escreve no canal.
    admin_token: str
    # Troca o arquivo do banco, pra rodar contra um descartável.
    sync_agents_db: Path | None = None
    # Destino da sincronização. Opcionais: sem eles a tela só avisa que falta configurar.
    # O token precisa ser humano, de administrador do sistema, e nunca é exibido.
    destino_url: str = ""
    destino_token: str = ""
    # E-mail da conta dona do token acima: a tela mostra em nome de quem as mudanças vão aparecer.
    destino_usuario_servico: str = ""

    @field_validator("admin_token", "destino_token", "destino_usuario_servico")
    @classmethod
    def _sem_espacos(cls, valor: str) -> str:
        return valor.strip()

    @field_validator("destino_url")
    @classmethod
    def _url_sem_barra(cls, valor: str) -> str:
        return valor.strip().rstrip("/")

    @field_validator("admin_token")
    @classmethod
    def _admin_obrigatorio(cls, valor: str) -> str:
        if not valor:
            raise ValueError("vazio")
        return valor


try:
    _config = Configuracao()
except ValidationError as erro:
    if any(e["loc"] == ("admin_token",) for e in erro.errors()):
        raise RuntimeError("ADMIN_TOKEN não definido no .env - veja .env.example") from None
    raise

HOST = _config.host
PORT = _config.port
ADMIN_TOKEN = _config.admin_token
SYNC_AGENTS_DB = _config.sync_agents_db
DESTINO_URL = _config.destino_url
DESTINO_TOKEN = _config.destino_token
DESTINO_USUARIO_SERVICO = _config.destino_usuario_servico
