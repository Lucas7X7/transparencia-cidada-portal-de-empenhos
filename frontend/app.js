"use strict";

const state = {
  portais: [],
  sincronizacoes: {},
  portal: "",
  pagina: 1,
  porPagina: 50,
  grafico: null,
};

const $ = (id) => document.getElementById(id);

const fmtBRL = (v) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

function setStatus(msg, tipo = "") {
  const el = $("status-sync");
  el.textContent = msg;
  el.className = "status" + (tipo ? " " + tipo : "");
}

async function carregarPortais() {
  try {
    const r = await fetch("/api/portais");
    state.portais = await r.json();
    preencherSelect(state.portais);
    const ufs = new Set(state.portais.map((p) => p.uf).filter(Boolean));
    $("stat-portais").textContent = String(state.portais.length);
    $("stat-ufs").textContent = String(ufs.size);
    carregarSincronizacoes();
    atualizarAvisoPortal();
  } catch (e) {
    setStatus("Erro ao carregar portais: " + e.message, "erro");
  }
}

function preencherSelect(lista) {
  const sel = $("portal");
  const atual = state.portal;
  sel.innerHTML = "";
  for (const p of lista) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `${p.nome} (${p.esfera}, ${p.uf})`;
    sel.appendChild(opt);
  }
  if (atual && lista.some((p) => p.id === atual)) {
    sel.value = atual;
  } else {
    state.portal = sel.value;
  }
}

async function carregarSincronizacoes() {
  try {
    const r = await fetch("/api/sincronizacoes");
    const lista = await r.json();
    state.sincronizacoes = {};
    for (const s of lista) state.sincronizacoes[s.portal_id] = s;
    preencherSelect(state.portais);
    atualizarStatusSync();
  } catch (e) {
    /* sem status disponível */
  }
}

function statusTextoPortal() {
  const s = state.sincronizacoes[state.portal];
  if (!s) return "";
  if (s.status === "sincronizando") return `Sincronizando agora... (${s.portal_nome || ""})`;
  if (s.status === "erro") return `Última sincronização com erro.`;
  const fim = (s.fim || "").replace("T", " ").replace("Z", "");
  const n = Number(s.total || 0);
  return `Cache: ${n.toLocaleString("pt-BR")} empenhos (atualizado em ${fim})`;
}

function atualizarStatusSync() {
  const el = $("status-sync");
  const txt = statusTextoPortal();
  if (txt) {
    el.textContent = txt;
    el.className = "status ok";
  } else if (portalAtual().ao_vivo) {
    el.textContent = "Portal consulta ao vivo (não usa cache).";
    el.className = "status";
  } else if (!el.textContent) {
    el.textContent = "Sem dados no cache ainda — sincronize o portal para habilitar busca por palavra-chave.";
    el.className = "status";
  }
}

function portalAtual() {
  return state.portais.find((p) => p.id === state.portal) || {};
}

function atualizarAvisoPortal() {
  const p = portalAtual();
  const btn = $("btn-sincronizar");
  if (p.ao_vivo) {
    btn.disabled = true;
    btn.textContent = "Portal consulta ao vivo (lento)";
    btn.title = "Este portal não possui sincronização em lote; a busca consulta o portal diretamente.";
  } else {
    btn.disabled = false;
    btn.textContent = "Sincronizar dados do portal";
    btn.title = "Baixa os empenhos do período para o cache local (agiliza buscas por palavra-chave).";
  }
}

function parametros(pagina) {
  const f = new FormData($("form-busca"));
  const p = new URLSearchParams();
  p.set("portal_id", state.portal);
  for (const k of ["termo", "favorecido", "cpfcnpj", "unidade", "data_ini", "data_fim", "min_valor", "max_valor"]) {
    const v = (f.get(k) || "").trim();
    if (v) p.set(k, v);
  }
  p.set("pagina", String(pagina || state.pagina));
  p.set("por_pagina", String(state.porPagina));
  return p;
}

async function buscar() {
  const p = portalAtual();
  setStatus(p.ao_vivo ? "Consultando portal estadual (pode levar ~30s)..." : "Buscando...", "animado");
  $("btn-buscar").disabled = true;
  try {
    const r = await fetch("/api/empenhos?" + parametros(state.pagina));
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new Error(j.detail || "Erro na busca");
    }
    const dados = await r.json();
    renderizarResumo(dados.resumo);
    renderizarTabela(dados.empenhos);
    renderizarGrafico(dados.empenhos);
    atualizarPaginacao(dados);
    $("sec-resultados").classList.remove("hidden");
    $("resumo").classList.remove("hidden");
    $("sec-grafico").classList.remove("hidden");
    setStatus(`${dados.resumo.total} empenho(s) encontrados.`, "ok");
  } catch (e) {
    setStatus("Erro: " + e.message, "erro");
  } finally {
    $("btn-buscar").disabled = false;
  }
}

function renderizarResumo(r) {
  $("kpi-total").textContent = r.total.toLocaleString("pt-BR");
  $("kpi-empenhado").textContent = fmtBRL(r.total_empenhado);
  $("kpi-liquidado").textContent = fmtBRL(r.total_liquidado);
  $("kpi-pago").textContent = fmtBRL(r.total_pago);
  $("kpi-fav").textContent = r.total_favorecidos.toLocaleString("pt-BR");
}

function renderizarTabela(empenhos) {
  const tbody = $("corpo-tabela");
  tbody.innerHTML = "";
  if (!empenhos.length) {
    tbody.innerHTML = `<tr><td colspan="9"><div class="vazio"><strong>Nenhum empenho encontrado</strong>
      Ajuste os filtros ou sincronize o portal para ter dados no cache.</div></td></tr>`;
    return;
  }
  for (const e of empenhos) {
    const tr = document.createElement("tr");
    const unid = e.unidadeOrcamentaria || e.orgao || "-";
    const hist = e.historico ? montarHistorico(e.historico) : "";
    tr.innerHTML = `
      <td>${escapeHtml(e.numeroAno)}</td>
      <td>${escapeHtml(e.dataEmpenho)}</td>
      <td><span class="fav">${escapeHtml(e.favorecido)}</span></td>
      <td><span class="cpf">${escapeHtml(e.cpfCnpj || "-")}</span></td>
      <td>${escapeHtml(unid)}</td>
      <td>${escapeHtml(e.elementoDespesa || "-")}${hist}</td>
      <td class="ativo">${fmtBRL(e.empenhado)}</td>
      <td class="ativo">${fmtBRL(e.liquidado)}</td>
      <td class="ativo">${fmtBRL(e.pago)}</td>`;
    tbody.appendChild(tr);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

const HIST_LIMITE = 160;

function montarHistorico(texto) {
  const total = String(texto).length;
  if (total <= HIST_LIMITE) {
    return `<div class="historico">${escapeHtml(texto)}</div>`;
  }
  const resumo = escapeHtml(String(texto).slice(0, HIST_LIMITE));
  const completo = escapeHtml(String(texto));
  return `
    <div class="historico" data-colapso>
      <span class="hist-resumo">${resumo}</span><span class="hist-resto" hidden>${completo}</span>
      <button type="button" class="hist-toggle" data-hist-toggle>ver mais</button>
    </div>`;
}

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-hist-toggle]");
  if (!btn) return;
  const wrap = btn.closest("[data-colapso]");
  const resto = wrap.querySelector(".hist-resto");
  const resumo = wrap.querySelector(".hist-resumo");
  const expandido = !resto.hidden;
  resto.hidden = expandido;
  resumo.hidden = !expandido;
  btn.textContent = expandido ? "ver mais" : "ver menos";
});

function atualizarPaginacao(d) {
  const totalPag = Math.max(1, Math.ceil(d.resumo.total / d.por_pagina));
  $("info-pagina").textContent = `Página ${d.pagina} de ${totalPag}`;
  $("btn-ant").disabled = d.pagina <= 1;
  $("btn-prox").disabled = d.pagina >= totalPag;
  state.pagina = d.pagina;
}

function renderizarGrafico(empenhos) {
  const mensal = {};
  for (const e of empenhos) {
    const chave = (e.dataEmpenho || "").slice(0, 7);
    if (!chave) continue;
    mensal[chave] = (mensal[chave] || 0) + e.empenhado;
  }
  const labels = Object.keys(mensal).sort();
  const valores = labels.map((k) => mensal[k]);
  const ctx = $("grafico").getContext("2d");
  if (state.grafico) state.grafico.destroy();
  state.grafico = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Empenhado",
        data: valores,
        backgroundColor: "rgba(15,118,110,0.75)",
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { callback: (v) => fmtBRL(v) } },
      },
    },
  });
}

async function sincronizar() {
  const p = new URLSearchParams();
  p.set("portal_id", state.portal);
  const ano = new Date().getFullYear();
  p.set("ano", String(ano));
  const ini = $("data_ini").value;
  const fim = $("data_fim").value;
  if (ini) p.set("data_ini", ini);
  if (fim) p.set("data_fim", fim);
  $("btn-sincronizar").disabled = true;
  setStatus("Baixando dados do portal (pode demorar)...", "animado");
  try {
    const r = await fetch("/api/sincronizar?" + p, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || "Falha na sincronização");
    setStatus(`Sincronizado: ${j.total} empenhos lidos (${j.novos} novos, ${j.atualizados} atualizados).`, "ok");
  } catch (e) {
    setStatus("Erro na sincronização: " + e.message, "erro");
  } finally {
    $("btn-sincronizar").disabled = false;
  }
}

function baixar(url, nome) {
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function relatorio() {
  const p = parametros(1);
  p.delete("pagina");
  p.delete("por_pagina");
  baixar("/api/relatorio/markdown?" + p.toString(), "relatorio_empenhos.md");
}

function csv() {
  const p = parametros(1);
  p.delete("pagina");
  p.delete("por_pagina");
  baixar("/api/relatorio/csv?" + p.toString(), "empenhos.csv");
}

$("filtro-portal").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  const lista = q
    ? state.portais.filter((p) =>
        `${p.nome} ${p.esfera} ${p.uf}`.toLowerCase().includes(q)
      )
    : state.portais;
  preencherSelect(lista);
});

$("form-busca").addEventListener("submit", (e) => {
  e.preventDefault();
  state.pagina = 1;
  buscar();
});

$("form-busca").addEventListener("reset", () => {
  state.pagina = 1;
  setTimeout(() => {
    $("sec-resultados").classList.add("hidden");
    $("resumo").classList.add("hidden");
    $("sec-grafico").classList.add("hidden");
    setStatus("");
  }, 0);
});

$("portal").addEventListener("change", (e) => {
  state.portal = e.target.value;
  state.pagina = 1;
  atualizarAvisoPortal();
  setStatus("");
  atualizarStatusSync();
});
$("btn-sincronizar").addEventListener("click", sincronizar);
$("btn-ant").addEventListener("click", () => {
  if (state.pagina > 1) { state.pagina--; buscar(); }
});
$("btn-prox").addEventListener("click", () => {
  state.pagina++; buscar();
});
$("btn-md").addEventListener("click", relatorio);
$("btn-csv").addEventListener("click", csv);

carregarPortais();
