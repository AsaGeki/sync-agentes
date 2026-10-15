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

  // Paginação local mantém cada tabela de grupo independente, inclusive as
  // tabelas abertas/feitas da página de feature. Os registros já vêm filtrados
  // pelo servidor; aqui só controlamos as linhas visíveis.
  const rotulosOrdenacao = new Intl.Collator("pt-BR", { numeric: true, sensitivity: "base" });

  function atualizarContagemFiltros(form) {
    const contador = form.querySelector("[data-filter-count]");
    if (!contador) return;
    const marcados = form.querySelectorAll('input[type="checkbox"]:checked').length;
    const selecionados = ["dono", "feature", "tag", "periodo"].filter((nome) => form.elements.namedItem(nome)?.value).length;
    const total = marcados + selecionados;
    contador.textContent = String(total);
    contador.hidden = total === 0;
    contador.setAttribute("aria-label", `${total} filtros ativos`);
  }

  function atualizarTabela(frame) {
    const tabela = frame.querySelector("table.tabela-tasks");
    const rodape = frame.querySelector("[data-table-footer]");
    const corpo = tabela?.tBodies[0];
    if (!tabela || !rodape || !corpo) return;

    const linhas = [...corpo.querySelectorAll("tr[data-task-row]")];
    const tamanho = Math.max(1, Number(rodape.querySelector("[data-table-page-size]")?.value || 10));
    const total = linhas.length;
    const paginas = Math.max(1, Math.ceil(total / tamanho));
    const pagina = Math.min(paginas, Math.max(1, Number(rodape.dataset.page || 1)));
    const inicio = total ? (pagina - 1) * tamanho : 0;
    const fim = Math.min(inicio + tamanho, total);

    rodape.dataset.page = String(pagina);
    linhas.forEach((linha, indice) => { linha.hidden = indice < inicio || indice >= fim; });
    const faixa = rodape.querySelector("[data-page-range]");
    const paginaTexto = rodape.querySelector("[data-page-label]");
    const anterior = rodape.querySelector('[data-table-page-step="-1"]');
    const proxima = rodape.querySelector('[data-table-page-step="1"]');
    if (faixa) faixa.textContent = total ? `${inicio + 1}–${fim} de ${total} ${total === 1 ? "tarefa" : "tarefas"}` : "0 tarefas";
    if (paginaTexto) paginaTexto.textContent = `Página ${pagina} de ${paginas}`;
    if (anterior) anterior.disabled = pagina <= 1;
    if (proxima) proxima.disabled = pagina >= paginas;
  }

  function iniciarTabelas() {
    document.querySelectorAll("[data-data-table]").forEach(atualizarTabela);
  }

  document.addEventListener("change", (e) => {
    const form = e.target.closest && e.target.closest("form.filtros");
    if (form) atualizarContagemFiltros(form);

    const seletor = e.target.closest && e.target.closest("[data-table-page-size]");
    if (!seletor) return;
    const frame = seletor.closest("[data-data-table]");
    const rodape = frame?.querySelector("[data-table-footer]");
    if (!frame || !rodape) return;
    rodape.dataset.page = "1";
    atualizarTabela(frame);
  });

  document.addEventListener("click", (e) => {
    const controlePagina = e.target.closest && e.target.closest("[data-table-page-step]");
    if (controlePagina) {
      const frame = controlePagina.closest("[data-data-table]");
      const rodape = frame?.querySelector("[data-table-footer]");
      if (!frame || !rodape || controlePagina.disabled) return;
      rodape.dataset.page = String(Number(rodape.dataset.page || 1) + Number(controlePagina.dataset.tablePageStep));
      atualizarTabela(frame);
      return;
    }

    const botaoOrdenacao = e.target.closest && e.target.closest("[data-table-sort]");
    if (!botaoOrdenacao) return;
    const frame = botaoOrdenacao.closest("[data-data-table]");
    const tabela = frame?.querySelector("table.tabela-tasks");
    const corpo = tabela?.tBodies[0];
    const rodape = frame?.querySelector("[data-table-footer]");
    const cabecalho = botaoOrdenacao.closest("th");
    if (!frame || !tabela || !corpo || !rodape || !cabecalho) return;

    const direcao = cabecalho.getAttribute("aria-sort") === "ascending" ? -1 : 1;
    tabela.querySelectorAll("th[aria-sort]").forEach((celula) => celula.removeAttribute("aria-sort"));
    cabecalho.setAttribute("aria-sort", direcao === 1 ? "ascending" : "descending");
    const chave = botaoOrdenacao.dataset.tableSort;
    const linhas = [...corpo.querySelectorAll("tr[data-task-row]")];
    linhas.sort((a, b) => {
      const valor = (linha) => [...linha.cells].find((celula) => celula.dataset.sortKey === chave)?.dataset.sortValue || "";
      const primeiro = valor(a);
      const segundo = valor(b);
      const comparacao = chave === "progress"
        ? Number(primeiro) - Number(segundo)
        : rotulosOrdenacao.compare(primeiro, segundo);
      return comparacao * direcao;
    });
    linhas.forEach((linha) => corpo.append(linha));
    rodape.dataset.page = "1";
    atualizarTabela(frame);
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
    document.querySelectorAll("details.grupo-feature, details.grupo-status").forEach((d) => {
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
  document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("form.filtros").forEach(atualizarContagemFiltros));
  document.addEventListener("DOMContentLoaded", iniciarTabelas);
  document.addEventListener("DOMContentLoaded", iniciarSidebar);
  document.addEventListener("htmx:afterSettle", restaurar);
  document.addEventListener("htmx:afterSettle", iniciarTabelas);
  document.addEventListener("htmx:afterSettle", iniciarSidebar);
})();
