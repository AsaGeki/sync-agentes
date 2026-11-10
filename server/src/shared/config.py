import os

from dotenv import load_dotenv

load_dotenv()

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))

# Gerencia people e projetos. Pela interface web (`/web/admin`) também lê
# qualquer projeto e gerencia membros; não escreve no canal - quem escreve usa
# o próprio token pessoal.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN não definido no .env - veja .env.example")

# Destino da sincronização (sistema de destino). Opcionais: sem eles a tela de
# sincronização só avisa que falta configurar. O token precisa ser humano, de
# administrador do sistema, e nunca é exibido na interface.
DESTINO_URL = os.environ.get("DESTINO_URL", "").strip().rstrip("/")
DESTINO_TOKEN = os.environ.get("DESTINO_TOKEN", "").strip()
# E-mail da conta dona do token acima: a tela mostra em nome de quem as mudanças vão aparecer.
DESTINO_USUARIO_SERVICO = os.environ.get("DESTINO_USUARIO_SERVICO", "").strip()
