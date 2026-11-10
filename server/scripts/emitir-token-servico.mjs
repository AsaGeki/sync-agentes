// Emite no destino uma credencial de administrador do sistema para a sincronização e grava o token no .env.
// Uso: node server/scripts/emitir-token-servico.mjs [--env caminho] [--usuario email] [--substituir]
import { randomBytes, randomUUID } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';

const argumentos = process.argv.slice(2);
const opcao = (nome) => {
  const posicao = argumentos.indexOf(nome);
  return posicao < 0 ? undefined : argumentos[posicao + 1];
};
const caminhoEnv = opcao('--env') ?? fileURLToPath(new URL('../.env', import.meta.url));
const usuario = opcao('--usuario') ?? 'sync-agents';
const substituir = argumentos.includes('--substituir');

const falhar = (mensagem) => {
  console.error(`Erro: ${mensagem}`);
  process.exit(1);
};

// Lê o token sem mostrá-lo na tela; com a entrada redirecionada, lê uma linha.
function pedirOculto(pergunta) {
  return new Promise((resolver) => {
    process.stdout.write(pergunta);
    process.stdin.setEncoding('utf8');
    if (!process.stdin.isTTY) {
      let dados = '';
      process.stdin.on('data', (parte) => {
        dados += parte;
        if (dados.includes('\n')) {
          process.stdin.pause();
          resolver(dados.split(/\r?\n/)[0].trim());
        }
      });
      return;
    }
    let valor = '';
    process.stdin.setRawMode(true);
    process.stdin.resume();
    const aoDigitar = (teclas) => {
      for (const tecla of teclas) {
        if (tecla === '\r' || tecla === '\n') {
          process.stdin.setRawMode(false);
          process.stdin.pause();
          process.stdin.off('data', aoDigitar);
          process.stdout.write('\n');
          return resolver(valor.trim());
        }
        if (tecla === '\u0003') process.exit(130);
        valor = tecla === '\u007f' || tecla === '\b' ? valor.slice(0, -1) : valor + tecla;
      }
    };
    process.stdin.on('data', aoDigitar);
  });
}

async function chamar(url, caminho, token, corpo) {
  let resposta;
  try {
    resposta = await fetch(`${url}${caminho}`, {
      method: corpo ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token}`, ...(corpo ? { 'Content-Type': 'application/json' } : {}) },
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
  } catch (erro) {
    falhar(`não consegui conectar em ${url}: ${erro.cause?.message ?? erro.message}`);
  }
  const texto = await resposta.text();
  let dados = {};
  try {
    dados = JSON.parse(texto);
  } catch {
    dados = { error: texto.slice(0, 200) };
  }
  return { status: resposta.status, dados };
}

if (!existsSync(caminhoEnv)) falhar(`arquivo .env não encontrado em ${caminhoEnv}.`);
const conteudo = readFileSync(caminhoEnv, 'utf8');
const env = parseEnv(conteudo);
const url = (env.DESTINO_URL ?? '').trim().replace(/\/+$/, '');
if (!url) falhar('defina DESTINO_URL no .env (endereço base do servidor de destino).');
if ((env.DESTINO_TOKEN ?? '').trim() && !substituir) {
  falhar('o .env já tem um DESTINO_TOKEN. Use --substituir para emitir outro; o atual continua valendo no destino.');
}

console.log(`Destino: ${url}`);
const mestre = await pedirOculto('Token mestre do destino (administrador do sistema): ');
if (!/^[a-f0-9]{64}$/.test(mestre)) falhar('o token mestre deve ter 64 caracteres hexadecimais.');

const novo = randomBytes(32).toString('hex');
const emissao = await chamar(url, '/admin', mestre, {
  action: 'issue', operationId: randomUUID(), userId: usuario, scope: 'human', systemAdmin: true, token: novo,
});
if (emissao.status === 401) falhar('o destino recusou o token mestre (inválido ou revogado).');
if (emissao.status === 403) falhar('o token informado não é de administrador do sistema, então não pode emitir outro.');
if (emissao.status !== 200) falhar(`o destino respondeu ${emissao.status}: ${emissao.dados.error ?? 'sem detalhe'}`);

// Confirma que o token novo é de administrador do sistema antes de gravá-lo.
const conferencia = await chamar(url, '/admin/credentials?limit=1', novo);
if (conferencia.status !== 200) falhar(`a credencial foi emitida, mas o token novo não funcionou como administrador (${conferencia.status}).`);

// Troca o valor de uma chave do .env, ou a acrescenta no fim, preservando o fim de linha do arquivo.
function definir(texto, chave, valor) {
  const padrao = new RegExp(`^${chave}=[^\\r\\n]*`, 'm');
  const quebra = texto.includes('\r\n') ? '\r\n' : '\n';
  if (padrao.test(texto)) return texto.replace(padrao, () => `${chave}=${valor}`);
  return `${texto}${texto === '' || /\n$/.test(texto) ? '' : quebra}${chave}=${valor}${quebra}`;
}
const gravado = definir(definir(conteudo, 'DESTINO_TOKEN', novo), 'DESTINO_USUARIO_SERVICO', usuario);
writeFileSync(caminhoEnv, gravado, 'utf8');

console.log(`Credencial de administrador emitida para ${usuario} (id ${emissao.dados.credentialId}).`);
console.log(`Token gravado em ${caminhoEnv} (termina em ...${novo.slice(-4)}). Reinicie o servidor do sync-agents.`);
console.log('O token mestre não foi alterado nem revogado.');
