import os

from dotenv import load_dotenv

load_dotenv()

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))

# Token de administração: só emite/lista pessoa. Não dá acesso ao conteúdo de
# projeto nenhum - quem escreve no canal usa o próprio token pessoal.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN não definido no .env - veja .env.example")
