// Tempo real da área da pessoa. Os avisos vêm do SharedWorker (uma conexão SSE
// por navegador) e viram eventos htmx no <body>: `mudou` pra qualquer mudança do
// projeto aberto e `mudou-task` quando ela é de uma task. Os trechos da página
// escutam com `hx-trigger="mudou from:body"`.
(function () {
  function repassar(aviso) {
    const area = document.querySelector("[data-projeto]");
    if (!area || area.dataset.projeto !== aviso.projeto) return;
    htmx.trigger(document.body, "mudou", aviso);
    if (aviso.task) htmx.trigger(document.body, "mudou-task", aviso);
  }

  let conectado = false;

  function conectar() {
    const area = document.querySelector("[data-pessoa]");
    if (conectado || !area) return;
    conectado = true;
    if ("SharedWorker" in window) {
      // O nome inclui a pessoa: outro login no mesmo navegador ganha um canal próprio.
      const worker = new SharedWorker("/web/static/sse-worker.js", { name: "sync-agents-" + area.dataset.pessoa });
      worker.port.onmessage = (e) => repassar(e.data);
      worker.port.start();
      addEventListener("pagehide", () => worker.port.postMessage("sair"));
    } else {
      const fonte = new EventSource("/web/stream");
      fonte.addEventListener("mudou", (e) => repassar(JSON.parse(e.data)));
      addEventListener("pagehide", () => fonte.close());
    }
  }

  // Com hx-boost o documento não recarrega: a conexão aberta uma vez serve a
  // navegação inteira. `afterSettle` cobre quem chega na área da pessoa por
  // navegação boost (depois do login, vindo do admin).
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", conectar);
  else conectar();
  document.addEventListener("htmx:afterSettle", conectar);
})();
