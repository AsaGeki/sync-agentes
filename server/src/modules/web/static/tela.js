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

  const chaveSidebar = "sync-agents:sidebar-recolhida";
  const chaveSidebarLargura = "sync-agents:sidebar-largura";
  const sidebarMovel = window.matchMedia("(max-width: 900px)");

  function iniciarSidebar() {
    const app = document.querySelector("[data-sidebar-app]");
    if (!app || app.dataset.sidebarReady) return;
    app.dataset.sidebarReady = "true";

    const sidebar = app.querySelector("#app-sidebar");
    const toggles = app.querySelectorAll("[data-sidebar-toggle]");
    const trilho = app.querySelector("[data-sidebar-rail]");
    const fechar = app.querySelector("[data-sidebar-close]");
    const busca = app.querySelector("[data-sidebar-search]");
    const menuConta = app.querySelector("[data-user-menu]");
    const gatilhoConta = menuConta && menuConta.querySelector("[data-user-trigger]");
    const painelConta = menuConta && menuConta.querySelector("[role='menu']");

    if (!sidebar) return;

    let recolhida = false;
    let largura = 248;
    try {
      recolhida = localStorage.getItem(chaveSidebar) === "1";
      const larguraSalva = Number(localStorage.getItem(chaveSidebarLargura));
      if (larguraSalva >= 176 && larguraSalva <= 360) largura = larguraSalva;
    } catch (_) {}
    app.style.setProperty("--sidebar-largura", `${largura}px`);

    function sincronizar() {
      app.classList.toggle("sidebar-recolhida", recolhida);
      if (trilho) trilho.setAttribute("aria-valuenow", String(recolhida ? 64 : largura));
      const drawerAberto = app.classList.contains("sidebar-drawer-aberto");
      const expandida = sidebarMovel.matches ? drawerAberto : !recolhida;
      const rotulo = sidebarMovel.matches
        ? (drawerAberto ? "Fechar navegação" : "Abrir navegação")
        : (recolhida ? "Expandir navegação" : "Recolher navegação");
      toggles.forEach((botao) => {
        botao.setAttribute("aria-expanded", String(expandida));
        botao.setAttribute("aria-label", rotulo);
        botao.title = rotulo;
      });
    }

    function fecharConta(devolverFoco) {
      if (!gatilhoConta || !painelConta || painelConta.hidden) return;
      painelConta.hidden = true;
      gatilhoConta.setAttribute("aria-expanded", "false");
      if (devolverFoco) gatilhoConta.focus();
    }

    function fecharDrawer(devolverFoco) {
      if (!app.classList.contains("sidebar-drawer-aberto")) return;
      app.classList.remove("sidebar-drawer-aberto");
      document.body.classList.remove("sidebar-drawer-aberto");
      sincronizar();
      if (devolverFoco) app.querySelector(".sidebar-trigger")?.focus();
    }

    function alternarSidebar() {
      if (sidebarMovel.matches) {
        const aberto = app.classList.toggle("sidebar-drawer-aberto");
        document.body.classList.toggle("sidebar-drawer-aberto", aberto);
        sincronizar();
        if (aberto) sidebar.querySelector("a, button, input")?.focus();
      } else {
        recolhida = !recolhida;
        try {
          localStorage.setItem(chaveSidebar, recolhida ? "1" : "0");
        } catch (_) {}
        sincronizar();
      }
    }

    function salvarLargura() {
      try {
        localStorage.setItem(chaveSidebar, recolhida ? "1" : "0");
        localStorage.setItem(chaveSidebarLargura, String(largura));
      } catch (_) {}
    }

    trilho?.addEventListener("pointerdown", (e) => {
      if (sidebarMovel.matches || e.button !== 0) return;
      e.preventDefault();
      const xInicial = e.clientX;
      const larguraInicial = recolhida ? 64 : largura;
      let larguraNova = larguraInicial;
      let moveu = false;
      app.classList.add("sidebar-redimensionando");
      trilho.setPointerCapture(e.pointerId);

      const mover = (evento) => {
        if (evento.pointerId !== e.pointerId) return;
        larguraNova = Math.max(64, Math.min(360, larguraInicial + evento.clientX - xInicial));
        moveu = Math.abs(evento.clientX - xInicial) >= 3;
        if (larguraNova < 132) {
          recolhida = true;
        } else {
          recolhida = false;
          largura = Math.max(176, larguraNova);
          app.style.setProperty("--sidebar-largura", `${largura}px`);
        }
        sincronizar();
      };

      const terminar = (evento) => {
        if (evento.pointerId !== e.pointerId) return;
        trilho.removeEventListener("pointermove", mover);
        trilho.removeEventListener("pointerup", terminar);
        trilho.removeEventListener("pointercancel", terminar);
        app.classList.remove("sidebar-redimensionando");
        if (moveu) salvarLargura();
        else alternarSidebar();
        sincronizar();
      };

      trilho.addEventListener("pointermove", mover);
      trilho.addEventListener("pointerup", terminar);
      trilho.addEventListener("pointercancel", terminar);
    });

    trilho?.addEventListener("keydown", (e) => {
      if (e.key === "Home") {
        e.preventDefault();
        recolhida = true;
      } else if (e.key === "End") {
        e.preventDefault();
        recolhida = false;
        largura = 360;
        app.style.setProperty("--sidebar-largura", `${largura}px`);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const base = recolhida ? 128 : largura;
        largura = Math.max(176, Math.min(360, base + (e.key === "ArrowRight" ? 16 : -16)));
        recolhida = false;
        app.style.setProperty("--sidebar-largura", `${largura}px`);
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        alternarSidebar();
      } else {
        return;
      }
      salvarLargura();
      sincronizar();
    });

    toggles.forEach((botao) => botao.addEventListener("click", alternarSidebar));
    fechar?.addEventListener("click", () => fecharDrawer(false));
    sincronizar();

    if (gatilhoConta && painelConta) {
      gatilhoConta.addEventListener("click", () => {
        const aberto = painelConta.hidden;
        painelConta.hidden = !aberto;
        gatilhoConta.setAttribute("aria-expanded", String(aberto));
      });
      gatilhoConta.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        painelConta.hidden = false;
        gatilhoConta.setAttribute("aria-expanded", "true");
        const itens = painelConta.querySelectorAll("a[role='menuitem'], button[role='menuitem']");
        (e.key === "ArrowDown" ? itens[0] : itens[itens.length - 1])?.focus();
      });
      painelConta.addEventListener("click", (e) => {
        if (e.target.closest("[role='menuitem']")) fecharConta(false);
      });
      menuConta.addEventListener("focusout", (e) => {
        if (!menuConta.contains(e.relatedTarget)) fecharConta(false);
      });

      painelConta.addEventListener("keydown", (e) => {
        const itens = [...painelConta.querySelectorAll("a[role='menuitem'], button[role='menuitem']")];
        if (e.key === "Escape") {
          e.preventDefault();
          fecharConta(true);
        } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const atual = itens.indexOf(document.activeElement);
          const direcao = e.key === "ArrowDown" ? 1 : -1;
          itens[(atual + direcao + itens.length) % itens.length]?.focus();
        }
      });
    }

    document.addEventListener("click", (e) => {
      if (menuConta && !menuConta.contains(e.target)) fecharConta(false);
      if (sidebarMovel.matches && app.classList.contains("sidebar-drawer-aberto") && sidebar.contains(e.target)) {
        if (e.target.closest("a[href]") && !e.target.closest("[data-user-menu]")) fecharDrawer(false);
      }
    });

    busca?.addEventListener("input", () => {
      const consulta = busca.value.trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
      const projetos = [...app.querySelectorAll("[data-sidebar-project-item]")];
      let visiveis = 0;
      projetos.forEach((item) => {
        const nome = (item.dataset.projectName || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
        item.hidden = Boolean(consulta) && !nome.includes(consulta);
        if (!item.hidden) visiveis += 1;
      });
      const vazio = app.querySelector("[data-sidebar-empty]");
      if (vazio) vazio.hidden = !consulta || visiveis > 0;
      if (consulta) app.querySelector(".sidebar-project-section")?.setAttribute("open", "");
    });

    document.addEventListener("keydown", (e) => {
      const digitando = e.target.matches("input, textarea, select, [contenteditable='true']");
      if (e.key === "Escape") {
        fecharConta(false);
        fecharDrawer(true);
      }
      if (!digitando && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        alternarSidebar();
      } else if (!digitando && e.key === "/" && busca) {
        e.preventDefault();
        if (sidebarMovel.matches && !app.classList.contains("sidebar-drawer-aberto")) alternarSidebar();
        if (recolhida && !sidebarMovel.matches) {
          recolhida = false;
          try { localStorage.setItem(chaveSidebar, "0"); } catch (_) {}
          sincronizar();
        }
        busca.focus();
      }
      if (sidebarMovel.matches && app.classList.contains("sidebar-drawer-aberto") && e.key === "Tab") {
        const foco = [...sidebar.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])")]
          .filter((el) => !el.hidden && el.offsetParent !== null);
        const primeiro = foco[0];
        const ultimo = foco[foco.length - 1];
        if (e.shiftKey && document.activeElement === primeiro) {
          e.preventDefault();
          ultimo?.focus();
        } else if (!e.shiftKey && document.activeElement === ultimo) {
          e.preventDefault();
          primeiro?.focus();
        }
      }
    });

    window.addEventListener("resize", () => {
      if (!sidebarMovel.matches) fecharDrawer(false);
      sincronizar();
    });
  }

  document.addEventListener("DOMContentLoaded", restaurar);
  document.addEventListener("DOMContentLoaded", iniciarSidebar);
  document.addEventListener("htmx:afterSettle", restaurar);
  document.addEventListener("htmx:afterSettle", iniciarSidebar);
})();
