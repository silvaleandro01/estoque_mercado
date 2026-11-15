// Teste das funções de fuso horário do frontend (frontend/app.js).
//
// Por quê este arquivo existe: as funções `formatarDataBrasil`/
// `formatarHoraBrasil`/`formatarDataHoraBrasil` já causaram DOIS bugs reais
// de verdade nesta mesma sessão de desenvolvimento -- a primeira versão não
// normalizava string ISO sem fuso como UTC antes de criar o Date (mostrava
// hora ~3h adiantada), e a correção disso quebrou campos que são só DATA
// (sem hora, ex. "2026-11-14" de vendas_do_dia/compras_do_dia), que
// passaram a mostrar o dia ANTERIOR. Dado esse histórico, essas funções
// puras merecem teste automatizado mesmo o projeto não tendo suíte de
// frontend -- usa só `node:assert`/`node:test` (sem dependência nova).
//
// Executa direto do código-fonte real (não uma cópia): extrai só o bloco
// das funções de fuso de frontend/app.js (que não pode ser importado
// inteiro em Node -- usa `window`/`document` no escopo de módulo) e avalia
// num sandbox via `vm`, pra nunca divergir do que roda de verdade no
// navegador.
//
// Rodar: node --test tests/frontend_timezone.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appJs = readFileSync(join(__dirname, '..', 'frontend', 'app.js'), 'utf8');

const inicio = appJs.indexOf('const FUSO_BRASIL');
const fim = appJs.indexOf('function escapeHtml');
assert.ok(inicio !== -1 && fim !== -1 && fim > inicio, 'bloco de funções de fuso não encontrado em frontend/app.js -- os marcadores de extração deste teste ficaram desatualizados');

const bloco = appJs.slice(inicio, fim);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(bloco, sandbox);
const { formatarDataBrasil, formatarHoraBrasil, formatarDataHoraBrasil } = sandbox;

// ── naive datetime (sem 'Z'/offset) -- bug original: hora ~3h adiantada ────

test('formatarHoraBrasil: datetime UTC sem offset converte pra hora de Brasília', () => {
    // 21:27:53 UTC == 18:27:53 em Brasília (UTC-3).
    assert.equal(formatarHoraBrasil('2026-11-14T21:27:53.112153'), '18:27:53');
});

test('formatarHoraBrasil: datetime COM offset explícito (Z) também converte certo', () => {
    assert.equal(formatarHoraBrasil('2026-11-14T21:27:53Z'), '18:27:53');
});

test('formatarDataHoraBrasil: datetime sem offset perto da virada do dia', () => {
    // 00:30 UTC do dia 16 == 21:30 em Brasília do dia 15 (UTC-3).
    const resultado = formatarDataHoraBrasil('2026-06-16T00:30:00');
    assert.ok(resultado.includes('15/06/2026'), `esperava dia 15/06/2026 em "${resultado}"`);
    assert.ok(resultado.includes('21:30'), `esperava hora 21:30 em "${resultado}"`);
});

// ── campo só de DATA (sem hora) -- bug da correção: virava o dia anterior ──

test('formatarDataBrasil: data pura (sem hora) NÃO desloca de dia', () => {
    assert.equal(formatarDataBrasil('2026-11-14'), '14/11/2026');
});

test('formatarDataHoraBrasil: data pura (sem hora) também NÃO desloca de dia', () => {
    assert.equal(formatarDataHoraBrasil('2026-11-14'), '14/11/2026');
});

test('formatarDataBrasil: datetime completo (com hora) continua convertendo fuso normalmente', () => {
    // 00:30 UTC do dia 16 -> 15 em Brasília (não deve bater com a data "crua" do UTC).
    assert.equal(formatarDataBrasil('2026-06-16T00:30:00'), '15/06/2026');
});

// ── valores ausentes ─────────────────────────────────────────────────────

test('funções de fuso tratam null/undefined/vazio sem lançar erro', () => {
    assert.equal(formatarDataBrasil(null), '--');
    assert.equal(formatarDataBrasil(undefined), '--');
    assert.equal(formatarDataBrasil(''), '--');
    assert.equal(formatarHoraBrasil(null), '--:--');
    assert.equal(formatarDataHoraBrasil(null), '--');
});
