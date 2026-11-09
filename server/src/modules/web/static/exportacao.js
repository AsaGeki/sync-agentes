(() => {
  const form = document.querySelector('#exportacao-form');
  if (!form) return;
  const linhas = [...form.querySelectorAll('[data-task]')];
  const situacao = document.querySelector('#filtro-situacao');
  const tag = document.querySelector('#filtro-tag');
  const feature = document.querySelector('#filtro-feature');
  const repo = document.querySelector('#repo-lote');
  const sobrescrever = document.querySelector('#sobrescrever');
  const lote = document.querySelector('#aplicar-lote');
  const sugestoes = document.querySelector('#aplicar-sugestoes');
  const mensagem = document.querySelector('#exportacao-acao');
  const download = form.querySelector('button[type="submit"]');
  document.querySelector('[data-exportacao-controles]').hidden = false;

  function atualizar() {
    let pendentes = 0;
    let visiveis = 0;
    let elegiveis = 0;
    let sugeridas = 0;
    const contagens = new Map();
    for (const linha of linhas) {
      const select = linha.querySelector('select');
      const atribuida = Boolean(select.value);
      const mostrarSituacao = situacao.value === 'todas' ||
        (situacao.value === 'pendentes' && !atribuida) ||
        (situacao.value === 'atribuidas' && atribuida) ||
        (situacao.value === 'sugestoes' && !atribuida && Boolean(linha.dataset.sugestao));
      const mostrar = mostrarSituacao && (!tag.value || JSON.parse(linha.dataset.tags).includes(tag.value)) &&
        (!feature.value || linha.dataset.feature === feature.value);
      linha.hidden = !mostrar;
      linha.querySelector('[data-status]').textContent = atribuida ? 'Atribuída' : 'Sem repositório';
      linha.classList.toggle('atribuida', atribuida);
      if (mostrar) {
        visiveis++;
        if (!atribuida || sobrescrever.checked) elegiveis++;
        if (!atribuida && linha.dataset.sugestao) sugeridas++;
      }
      if (!atribuida) pendentes++;
      else {
        const nome = select.selectedOptions[0].textContent;
        contagens.set(nome, (contagens.get(nome) || 0) + 1);
      }
    }
    const concluidas = linhas.length - pendentes;
    document.querySelector('#exportacao-progresso-texto').textContent = pendentes
      ? `${pendentes} de ${linhas.length} tasks ainda precisam de repositório.`
      : `Todas as ${linhas.length} tasks têm repositório. O arquivo está pronto para baixar.`;
    const barra = document.querySelector('.exportacao-barra');
    barra.setAttribute('aria-valuenow', concluidas);
    barra.firstElementChild.style.width = `${linhas.length ? 100 * concluidas / linhas.length : 100}%`;
    document.querySelector('#exportacao-contagens').textContent = contagens.size
      ? `Atribuídas — ${[...contagens].map(([nome, n]) => `${nome}: ${n}`).join(' · ')}`
      : 'Nenhuma task atribuída ainda.';
    document.querySelector('#exportacao-visiveis').textContent = `${visiveis} de ${linhas.length} tasks exibidas`;
    document.querySelector('#exportacao-vazio').hidden = visiveis > 0;
    document.querySelector('#exportacao-download-ajuda').hidden = pendentes === 0;
    download.disabled = pendentes > 0;
    lote.disabled = !repo.value || elegiveis === 0;
    lote.textContent = `Atribuir a ${elegiveis} task(s)`;
    sugestoes.disabled = sugeridas === 0;
    sugestoes.textContent = `Aceitar ${sugeridas} sugestão(ões)`;
  }
  for (const campo of [situacao, tag, feature, repo, sobrescrever]) campo.addEventListener('change', () => {
    mensagem.textContent = '';
    atualizar();
  });
  form.addEventListener('change', event => {
    if (event.target.matches('[data-task] select')) {
      mensagem.textContent = 'Escolha atualizada. A lista segue os filtros selecionados.';
      atualizar();
    }
  });
  document.querySelector('#limpar-filtros').addEventListener('click', () => {
    situacao.value = 'todas'; tag.value = ''; feature.value = '';
    mensagem.textContent = '';
    atualizar();
  });
  lote.addEventListener('click', () => {
    let total = 0;
    for (const linha of linhas) {
      const select = linha.querySelector('select');
      if (!linha.hidden && (!select.value || sobrescrever.checked)) { select.value = repo.value; total++; }
    }
    mensagem.textContent = `${total} task(s) atribuídas. A lista segue os filtros selecionados.`;
    atualizar();
  });
  sugestoes.addEventListener('click', () => {
    let total = 0;
    for (const linha of linhas) {
      const select = linha.querySelector('select');
      if (!linha.hidden && !select.value && linha.dataset.sugestao) { select.value = linha.dataset.sugestao; total++; }
    }
    mensagem.textContent = `${total} sugestão(ões) aceitas. A lista segue os filtros selecionados.`;
    atualizar();
  });
  atualizar();
})();
