// Comportamentos de tela: estado de interface em componentes Alpine, mais dois ganchos do htmx.
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

  // A atualização em tempo real não troca as propriedades da task enquanto a pessoa digita nelas (Tags).
  document.addEventListener("htmx:oobBeforeSwap", (e) => {
    const alvo = e.detail.target;
    const foco = document.activeElement;
    if (alvo?.id === "propriedades" && alvo.contains(foco) && foco.matches("input[type=text], textarea")) {
      e.detail.shouldSwap = false;
    }
  });

  function ler(armazem, chave) {
    try { return armazem.getItem(chave); } catch (_) { return null; }
  }
  function gravar(armazem, chave, valor) {
    try { armazem.setItem(chave, valor); } catch (_) {}
  }
  const semAcento = (texto) => (texto || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("pt-BR");
  const colacao = new Intl.Collator("pt-BR", { numeric: true, sensitivity: "base" });
  const raiz = document.documentElement;
  const telaEstreita = window.matchMedia("(max-width: 900px)");
  const CHAVE_RECOLHIDA = "sync-agents:sidebar-recolhida";
  const CHAVE_LARGURA = "sync-agents:sidebar-largura";
  const FOCAVEIS = "a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])";

  document.addEventListener("alpine:init", () => {
    // Recolhida e largura ficam no <html>, que o hx-boost não troca; o script do <head> já aplicou o estado salvo.
    Alpine.store("sidebar", {
      recolhida: raiz.classList.contains("sidebar-recolhida"),
      largura: parseInt(raiz.style.getPropertyValue("--sidebar-largura"), 10) || 248,
      gaveta: false,
      arrastando: false,
      estreita: telaEstreita.matches,

      get expandida() { return this.estreita ? this.gaveta : !this.recolhida; },
      get rotulo() {
        if (this.estreita) return this.gaveta ? "Fechar navegação" : "Abrir navegação";
        return this.recolhida ? "Expandir navegação" : "Recolher navegação";
      },

      alternar() {
        if (this.estreita) {
          this.gaveta = !this.gaveta;
          if (this.gaveta) Alpine.nextTick(() => document.querySelector("#app-sidebar")?.querySelector(FOCAVEIS)?.focus());
        } else {
          this.definirRecolhida(!this.recolhida);
        }
      },
      definirRecolhida(valor) {
        this.recolhida = valor;
        raiz.classList.toggle("sidebar-recolhida", valor);
        gravar(localStorage, CHAVE_RECOLHIDA, valor ? "1" : "0");
      },
      definirLargura(px, salvar = true) {
        this.largura = Math.max(176, Math.min(360, px));
        raiz.style.setProperty("--sidebar-largura", `${this.largura}px`);
        if (salvar) gravar(localStorage, CHAVE_LARGURA, String(this.largura));
      },
      fecharGaveta(devolverFoco) {
        if (!this.gaveta) return;
        this.gaveta = false;
        if (devolverFoco) document.querySelector(".sidebar-trigger")?.focus();
      },

      // Link da gaveta navega e fecha a gaveta; o menu da conta tem os próprios links.
      cliqueNaLateral(e) {
        if (this.estreita && e.target.closest("a[href]") && !e.target.closest("[data-user-menu]")) this.fecharGaveta(false);
      },
      // Com a gaveta aberta no celular, o Tab circula só dentro dela.
      prenderFoco(e, lateral) {
        if (!this.estreita || !this.gaveta) return;
        const foco = [...lateral.querySelectorAll(FOCAVEIS)].filter((el) => !el.hidden && el.offsetParent !== null);
        const primeiro = foco[0];
        const ultimo = foco[foco.length - 1];
        if (e.shiftKey && document.activeElement === primeiro) { e.preventDefault(); ultimo?.focus(); }
        else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primeiro?.focus(); }
      },
      // Atalhos: Esc fecha a gaveta, Ctrl+B alterna a navegação, "/" busca projeto.
      teclado(e) {
        const digitando = e.target instanceof Element && e.target.matches("input, textarea, select, [contenteditable='true']");
        if (e.key === "Escape") this.fecharGaveta(true);
        if (digitando) return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
          e.preventDefault();
          this.alternar();
        } else if (e.key === "/") {
          const busca = document.querySelector("[data-sidebar-search]");
          if (!busca) return;
          e.preventDefault();
          if (this.estreita && !this.gaveta) this.alternar();
          if (!this.estreita && this.recolhida) this.definirRecolhida(false);
          busca.focus();
        }
      },
    });

    telaEstreita.addEventListener("change", (e) => {
      const sidebar = Alpine.store("sidebar");
      sidebar.estreita = e.matches;
      if (!e.matches) sidebar.gaveta = false;
    });

    // Trilho entre a navegação e o conteúdo: arrastar redimensiona, clique simples alterna.
    Alpine.data("trilhoLateral", () => ({
      iniciar(e) {
        const sidebar = this.$store.sidebar;
        if (sidebar.estreita || e.button !== 0) return;
        e.preventDefault();
        const trilho = this.$el;
        const xInicial = e.clientX;
        const larguraInicial = sidebar.recolhida ? 64 : sidebar.largura;
        let moveu = false;
        sidebar.arrastando = true;
        trilho.setPointerCapture(e.pointerId);
        const mover = (ev) => {
          if (ev.pointerId !== e.pointerId) return;
          const nova = Math.max(64, Math.min(360, larguraInicial + ev.clientX - xInicial));
          moveu = moveu || Math.abs(ev.clientX - xInicial) >= 3;
          if (nova < 132) {
            sidebar.recolhida = true;
            raiz.classList.add("sidebar-recolhida");
          } else {
            sidebar.recolhida = false;
            raiz.classList.remove("sidebar-recolhida");
            sidebar.definirLargura(nova, false);
          }
        };
        const terminar = (ev) => {
          if (ev.pointerId !== e.pointerId) return;
          trilho.removeEventListener("pointermove", mover);
          trilho.removeEventListener("pointerup", terminar);
          trilho.removeEventListener("pointercancel", terminar);
          sidebar.arrastando = false;
          if (moveu) {
            sidebar.definirRecolhida(sidebar.recolhida);
            sidebar.definirLargura(sidebar.largura);
          } else {
            sidebar.alternar();
          }
        };
        trilho.addEventListener("pointermove", mover);
        trilho.addEventListener("pointerup", terminar);
        trilho.addEventListener("pointercancel", terminar);
      },
      teclado(e) {
        const sidebar = this.$store.sidebar;
        if (e.key === "Home") sidebar.definirRecolhida(true);
        else if (e.key === "End") { sidebar.definirRecolhida(false); sidebar.definirLargura(360); }
        else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          const base = sidebar.recolhida ? 128 : sidebar.largura;
          sidebar.definirRecolhida(false);
          sidebar.definirLargura(base + (e.key === "ArrowRight" ? 16 : -16));
        } else if (e.key === "Enter" || e.key === " ") sidebar.alternar();
        else return;
        e.preventDefault();
      },
    }));

    Alpine.data("buscaProjetos", () => ({
      busca: "",
      corresponde(nome) { return !this.busca.trim() || semAcento(nome).includes(semAcento(this.busca.trim())); },
      get vazio() {
        return [...this.$root.querySelectorAll("[data-project-name]")].every((item) => !this.corresponde(item.dataset.projectName));
      },
    }));

    Alpine.data("menuConta", () => ({
      aberto: false,
      itens() { return [...this.$root.querySelectorAll("[role='menuitem']")]; },
      alternar() { this.aberto = !this.aberto; },
      abrir(indice) {
        this.aberto = true;
        this.$nextTick(() => this.itens().at(indice)?.focus());
      },
      fechar(devolverFoco) {
        if (!this.aberto) return;
        this.aberto = false;
        if (devolverFoco) this.$root.querySelector("[data-user-trigger]")?.focus();
      },
      mover(direcao) {
        const itens = this.itens();
        const atual = itens.indexOf(document.activeElement);
        itens[(atual + direcao + itens.length) % itens.length]?.focus();
      },
      sairDoFoco(e) { if (!this.$root.contains(e.relatedTarget)) this.fechar(false); },
    }));

    // Tabela de tasks: ordena e pagina as linhas que o servidor já mandou filtradas.
    Alpine.data("tabelaTasks", () => ({
      pagina: 1,
      tamanho: 10,
      chave: null,
      direcao: 1,
      total: 0,
      init() { this.aplicar(); },
      linhas() { return [...this.$refs.corpo.querySelectorAll("tr[data-task-row]")]; },
      get paginas() { return Math.max(1, Math.ceil(this.total / this.tamanho)); },
      get inicio() { return this.total ? (this.pagina - 1) * this.tamanho : 0; },
      get fim() { return Math.min(this.inicio + this.tamanho, this.total); },
      get faixa() {
        return this.total ? `${this.inicio + 1}–${this.fim} de ${this.total} ${this.total === 1 ? "tarefa" : "tarefas"}` : "0 tarefas";
      },
      aplicar() {
        const linhas = this.linhas();
        this.total = linhas.length;
        this.pagina = Math.min(this.paginas, Math.max(1, this.pagina));
        linhas.forEach((linha, i) => { linha.hidden = i < this.inicio || i >= this.fim; });
      },
      irPara(passo) { this.pagina += passo; this.aplicar(); },
      mudarTamanho() { this.pagina = 1; this.aplicar(); },
      ordem(chave) {
        if (this.chave !== chave) return null;
        return this.direcao === 1 ? "ascending" : "descending";
      },
      ordenar(chave) {
        this.direcao = this.chave === chave ? -this.direcao : 1;
        this.chave = chave;
        const valor = (linha) => linha.querySelector(`[data-sort-key="${chave}"]`)?.dataset.sortValue || "";
        const linhas = this.linhas().sort((a, b) => {
          const comparacao = chave === "progress" ? Number(valor(a)) - Number(valor(b)) : colacao.compare(valor(a), valor(b));
          return comparacao * this.direcao;
        });
        linhas.forEach((linha) => this.$refs.corpo.append(linha));
        this.pagina = 1;
        this.aplicar();
      },
    }));

    Alpine.data("contadorFiltros", () => ({
      total: 0,
      init() { this.contar(); },
      contar() {
        const form = this.$root;
        const marcados = form.querySelectorAll('input[type="checkbox"]:checked').length;
        const selecionados = ["dono", "feature", "tag", "periodo"].filter((nome) => form.elements.namedItem(nome)?.value).length;
        this.total = marcados + selecionados;
      },
    }));

    // `<details>` que lembra aberto/fechado por página, pra a atualização em tempo
    // real não reabrir o que a pessoa recolheu. Só o clique da pessoa grava.
    Alpine.data("lembrarAberto", () => ({
      chave() { return "tela:" + location.pathname + ":" + this.$root.dataset.estado; },
      init() {
        const salvo = ler(sessionStorage, this.chave());
        if (salvo !== null) this.$root.open = salvo === "1";
      },
      clicou(e) {
        const resumo = e.target.closest("summary");
        if (!resumo || resumo.parentElement !== this.$root || e.target.closest("a")) return;
        gravar(sessionStorage, this.chave(), this.$root.open ? "0" : "1");
      },
      definir(aberto) {
        this.$root.open = aberto;
        gravar(sessionStorage, this.chave(), aberto ? "1" : "0");
      },
    }));

    // Texto longo começa recolhido; o botão só aparece se ele de fato passa do limite.
    Alpine.data("colapsavel", () => ({
      aberto: false,
      excede: false,
      init() {
        this.$nextTick(() => {
          const texto = this.$refs.texto;
          texto.classList.add("colapsada");
          this.excede = texto.scrollHeight > texto.clientHeight + 4;
          if (!this.excede) texto.classList.remove("colapsada");
        });
      },
      alternar() {
        this.aberto = !this.aberto;
        this.$refs.texto.classList.toggle("colapsada", !this.aberto);
      },
    }));

    // Sidebar recolhida só abre por cima depois de o mouse parar nela um instante; sair fecha na hora.
    Alpine.data("espiarLateral", () => ({
      espiando: false,
      espera: null,
      entrar() {
        if (!Alpine.store("sidebar").recolhida) return;
        clearTimeout(this.espera);
        this.espera = setTimeout(() => (this.espiando = true), 400);
      },
      sair() {
        clearTimeout(this.espera);
        this.espiando = false;
      },
    }));

    // Tags da task como chips. Cada mudança grava o campo escondido `tags` e dispara o `change` do formulário.
    Alpine.data("editorTags", () => ({
      tags: [],
      todas: [],
      texto: "",
      aberto: false,
      ativo: 0,
      init() {
        this.tags = JSON.parse(this.$el.dataset.tags);
        this.todas = JSON.parse(this.$el.dataset.sugestoes);
      },
      get opcoes() {
        const busca = semAcento(this.texto.trim());
        const lista = this.todas
          .filter((t) => !this.tags.includes(t) && semAcento(t).includes(busca))
          .slice(0, 8)
          .map((valor) => ({ valor, nova: false }));
        const repetida = [...this.todas, ...this.tags].some((t) => semAcento(t) === busca);
        if (busca && !repetida) lista.push({ valor: this.texto.trim(), nova: true });
        return lista;
      },
      get mostrarLista() {
        return this.aberto && this.opcoes.length > 0;
      },
      digitou() {
        this.ativo = 0;
        this.aberto = true;
      },
      adicionar(valor) {
        valor = valor.trim();
        this.texto = "";
        if (!valor) return;
        valor = this.todas.find((t) => semAcento(t) === semAcento(valor)) || valor;
        if (this.tags.includes(valor)) return;
        this.tags.push(valor);
        this.salvar();
      },
      remover(tag) {
        this.tags = this.tags.filter((t) => t !== tag);
        this.salvar();
      },
      salvar() {
        this.$refs.valor.value = this.tags.join(",");
        this.$refs.valor.dispatchEvent(new Event("change", { bubbles: true }));
      },
      teclado(e) {
        const n = this.opcoes.length;
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          this.aberto = true;
          if (n) this.ativo = (this.ativo + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
        } else if (e.key === "Enter" || e.key === ",") {
          e.preventDefault();
          const escolhida = this.mostrarLista && e.key === "Enter" ? this.opcoes[this.ativo] : null;
          this.adicionar(escolhida ? escolhida.valor : this.texto);
        } else if (e.key === "Backspace" && !this.texto && this.tags.length) {
          this.remover(this.tags[this.tags.length - 1]);
        } else if (e.key === "Escape") {
          this.aberto = false;
        }
      },
      sair(e) {
        if (this.$el.contains(e.relatedTarget)) return;
        this.aberto = false;
        if (this.texto.trim()) this.adicionar(this.texto);
      },
    }));
  });
})();
