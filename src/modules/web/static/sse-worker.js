// Uma conexão SSE (/web/stream) para todas as abas da mesma pessoa. Cada aviso
// recebido é repassado a todas as abas conectadas.
const portas = new Set();
let fonte = null;

function abrir() {
  fonte = new EventSource("/web/stream");
  fonte.addEventListener("mudou", (e) => {
    const aviso = JSON.parse(e.data);
    for (const porta of portas) porta.postMessage(aviso);
  });
}

onconnect = (e) => {
  const porta = e.ports[0];
  portas.add(porta);
  porta.onmessage = (m) => {
    if (m.data === "sair") portas.delete(porta);
  };
  // 401 (sessão expirada) fecha o EventSource de vez; uma aba nova tenta de novo.
  if (!fonte || fonte.readyState === EventSource.CLOSED) abrir();
  porta.start();
};
