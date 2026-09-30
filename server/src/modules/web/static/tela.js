// Comportamentos de tela compartilhados.
(function () {
  // URL de filtro curta: os formulários `.filtros` mandam só o que tem valor e
  // foge do padrão, então o link compartilhado não leva `&q=&dono=&...`.
  const PADRAO = { visao: "lista", ordem: "code" };
  document.addEventListener("htmx:configRequest", (e) => {
    const { elt, parameters } = e.detail;
    if (!elt.classList || !elt.classList.contains("filtros")) return;
    for (const chave of Object.keys(parameters)) {
      const valor = parameters[chave];
      if (valor === "" || valor === PADRAO[chave]) delete parameters[chave];
    }
  });

  // `<details data-estado="chave">` lembra aberto/fechado por página, pra a
  // atualização em tempo real não reabrir o que a pessoa recolheu. Só o clique
  // na pessoa grava: o `toggle` também dispara na carga inicial e na restauração.
  const chave = (d) => "tela:" + location.pathname + ":" + d.dataset.estado;

  function guardar(d, aberto) {
    try {
      sessionStorage.setItem(chave(d), aberto ? "1" : "0");
    } catch (_) {}
  }

  function restaurar() {
    document.querySelectorAll("details[data-estado]").forEach((d) => {
      let salvo = null;
      try {
        salvo = sessionStorage.getItem(chave(d));
      } catch (_) {}
      if (salvo !== null && d.open !== (salvo === "1")) d.open = salvo === "1";
    });
  }

  document.addEventListener("click", (e) => {
    const resumo = e.target.closest && e.target.closest("details[data-estado] > summary");
    if (resumo && !e.target.closest("a")) guardar(resumo.parentElement, !resumo.parentElement.open);
  });

  // Botões "expandir tudo" / "recolher tudo" dos grupos de feature.
  window.alternarGrupos = function (abrir) {
    document.querySelectorAll("details.grupo-feature").forEach((d) => {
      d.open = abrir;
      guardar(d, abrir);
    });
  };

  document.addEventListener("DOMContentLoaded", restaurar);
  document.addEventListener("htmx:afterSettle", restaurar);
})();
