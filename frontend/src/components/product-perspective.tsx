"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, Building2, Plus, ShieldCheck, Tractor } from "lucide-react";
import { EnvironmentalConditions } from "@/components/environmental-conditions";
import { RiskAssistant } from "@/components/risk-assistant";
import { RiskBadge } from "@/components/risk-badge";
import { RiskMap } from "@/components/risk-map";
import { exposureHeading, provenanceLabel } from "@/lib/provenance";
import { deliveryLabels, statusLabels } from "@/lib/operations";
import type { CommandCenterData, PropertyView } from "@/lib/types";

const ranks = { critical: 4, high: 3, moderate: 2, low: 1, unknown: 0 };
const priority = (a: PropertyView, b: PropertyView) => ranks[b.level] - ranks[a.level] || (b.score ?? -1) - (a.score ?? -1);
const panel = "rounded-2xl border border-slate-200 bg-white p-5 sm:p-6";
const label = "text-xs font-semibold uppercase tracking-widest text-slate-500";

function Operations({ property }: { property: PropertyView }) {
  const state = property.operationalState;
  if (!state) return <p className="text-sm text-slate-500">Alertas e entrega: não consultados.</p>;
  return <div className="space-y-2 text-sm"><p>{state.openAlerts} alertas não resolvidos · até 20 registros recentes</p>
    {state.alerts.map((a, i) => <p key={i}>Alerta: {statusLabels[a.status as keyof typeof statusLabels] ?? "Indisponível"} · Telegram: {a.notifications.filter((n) => n.channel === "telegram").map((n) => deliveryLabels[n.status] ?? n.status).join(", ") || "sem entrega registrada"}</p>)}
    {!state.alerts.length && <p>Nenhum alerta no recorte consultado. Sem entrega registrada.</p>}
  </div>;
}

function FarmCard({ property: p, onSelect, insurer }: { property: PropertyView; onSelect: () => void; insurer: boolean }) {
  return <article className={`${panel} flex min-w-0 flex-col gap-4`} data-testid="farm-card" data-property={p.id}>
    <div className="flex items-center justify-between gap-2"><span className={label}>{insurer ? p.clientName : "Minha fazenda"}</span><RiskBadge level={p.level} /></div>
    <button type="button" onClick={onSelect} className="group text-left"><h3 className="flex items-center gap-2 text-xl font-bold text-slate-900">{p.name}<ArrowUpRight className="size-4 shrink-0 text-slate-400 group-hover:text-red-600" /></h3><p className="mt-1 text-sm text-slate-500">{p.city} / {p.uf}</p></button>
    <div><p className={label}>{exposureHeading(p)}</p><p className="mt-1 text-3xl font-bold tabular-nums text-slate-900">{p.score !== null ? <>{p.score}<span className="text-sm font-normal text-slate-400"> /100</span></> : p.processingState === "waiting" ? <span className="text-lg">Aguardando dados</span> : <span className="text-lg">Dados ambientais indisponíveis</span>}</p><p className="mt-1 text-sm">{p.riskType || "Análise pendente"}</p></div>
    <ul className="space-y-2 text-sm text-slate-600">{p.factors.slice(0, 3).map((f) => <li key={f.key}>{f.description || f.label}</li>)}</ul>
    <Operations property={p} />
    <p className="text-xs leading-relaxed text-slate-500">{p.environmentalContext?.sections.find((s) => s.title === "Última leitura ambiental")?.lines.slice(0, 3).join(" · ") || "Resumo ambiental indisponível."}</p>
    <p className="mt-auto border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">{provenanceLabel(p)}{p.provenance?.environmental.state === "real_cached" ? " em cache" : ""}<br />Última leitura ambiental: {p.analysisTimestamp || "indisponível"}<br />{p.sources.filter((s) => s.updatedLabel).map((s) => s.name).join(" · ")}</p>
  </article>;
}

export function ProductPerspective({ initialData, perspective, readOnly = false }: { readOnly?: boolean; initialData: CommandCenterData; perspective: "seguradora" | "segurado" }) {
  const insurer = perspective === "seguradora";
  const [data, setData] = useState(initialData);
  const [propertyId, setPropertyId] = useState("");
  const [client, setClient] = useState("");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [sort, setSort] = useState("priority");
  useEffect(() => {
    const sync = () => { const query = new URLSearchParams(location.search); setPropertyId(query.get("fazenda") || ""); setClient(insurer ? query.get("cliente") || "" : ""); };
    sync(); window.addEventListener("popstate", sync); return () => window.removeEventListener("popstate", sync);
  }, [insurer]);
  function navigate(id = "", selectedClient = "") {
    setPropertyId(id); setClient(selectedClient);
    const query = new URLSearchParams(); if (id) query.set("fazenda", id); if (insurer && selectedClient) query.set("cliente", selectedClient);
    window.history.pushState(null, "", `/${perspective}${query.size ? `?${query}` : ""}`);
  }
  const all = [...data.properties].sort(priority);
  const scoped = insurer && client ? all.filter((p) => p.clientName === client) : all;
  const selected = scoped.find((p) => p.id === propertyId);
  const clients = [...new Set(all.map((p) => p.clientName || "Cliente demonstrativo"))].sort((a, b) => priority(all.find((p) => p.clientName === a)!, all.find((p) => p.clientName === b)!));
  const mapProperties = selected ? [selected] : scoped;
  async function reload() {
    const r = await fetch(`/api/perspectives/${perspective}`, { cache: "no-store" });
    if (!r.ok) throw new Error("Não foi possível atualizar a captura.");
    setData(await r.json());
  }
  async function analyze(id: string) {
    setBusy(true); setNotice("Analisando condições. O risco será exibido após o resultado do motor.");
    try { const r = await fetch("/api/insured/properties", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analyzeId: id }) });
      const result = await r.json(); if (!r.ok) throw new Error(result.mensagem || "Análise indisponível."); await reload(); setNotice("Consulta concluída. Consulte a disponibilidade e os horários das fontes.");
    } catch (e) { setNotice(e instanceof Error ? e.message : "Consulta indisponível."); } finally { setBusy(false); }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const fields = new FormData(event.currentTarget); setBusy(true); setNotice("Salvando fazenda demonstrativa…");
    try { const r = await fetch("/api/insured/properties", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(fields)) });
      const result = await r.json(); if (!r.ok) throw new Error(result.mensagem || "Cadastro indisponível.");
      setAdding(false); await reload(); navigate(result.property.fazendaId); await analyze(result.property.fazendaId);
    } catch (e) { setNotice(e instanceof Error ? e.message : "Cadastro indisponível."); } finally { setBusy(false); }
  }
  return <div className="min-h-screen bg-slate-50 text-slate-700">
    <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 px-5 py-5 sm:px-10"><Link prefetch={false} href={`/${perspective}`} className="flex items-center gap-3 text-lg font-extrabold tracking-tight text-slate-950"><ShieldCheck className="size-8 text-red-600" />SOMPO <span className="text-sm font-normal text-slate-500">{insurer ? "Risk Operations" : "Minhas fazendas"}</span></Link><nav aria-label="Perspectiva de demonstração" className="flex gap-1 rounded-lg bg-slate-100 p-1">{["seguradora", "segurado"].map((route) => <Link prefetch={false} key={route} href={`/${route}`} className={`rounded-md px-3 py-2 text-xs font-semibold ${perspective === route ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}>{route === "seguradora" ? "Seguradora" : "Segurado"}</Link>)}</nav></div></header>
    <main className="mx-auto max-w-[1600px] space-y-7 px-5 py-8 pb-24 sm:px-10">
      <div className="flex flex-wrap items-end justify-between gap-4"><div><p className={label}>{insurer ? "Operação de riscos · carteira demonstrativa" : "Conta demonstrativa · Cliente A"}</p><h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">{insurer ? client || "Prioridades da carteira" : "Minhas propriedades"}</h1><p className="mt-3 max-w-2xl text-sm text-slate-500">{insurer ? "Priorize clientes pela exposição registrada e acompanhe a situação operacional." : "Acompanhe suas fazendas, entenda os riscos e veja o que fazer agora."}</p></div>{!insurer && <button onClick={() => readOnly ? setNotice("Modo apresentação: cadastro e persistência desabilitados. As fazendas exibidas pertencem à captura armazenada.") : setAdding(true)} className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-3 text-sm font-bold text-white"><Plus className="size-4" />Adicionar fazenda</button>}</div>
      <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">Apresentação: identidades fictícias, não representam segurados SOMPO. Evidências ambientais reais com fontes e horários. O seletor de perspectiva não é autenticação.</p>
      {data.notices.map((message, index) => <p key={index} role="status" className="text-sm text-slate-600">{message}</p>)}
      {(selected || client) && <button onClick={() => navigate()} className="flex items-center gap-2 text-sm font-semibold"><ArrowLeft className="size-4" />{insurer ? "Voltar à carteira" : "Todas as minhas propriedades"}</button>}
      <section aria-label="Resumo" className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[[insurer ? "Clientes neste recorte" : "Minhas propriedades", insurer ? new Set(scoped.map((p) => p.clientName)).size : all.length], [insurer ? "Propriedades" : "Requerem atenção", insurer ? scoped.length : all.filter((p) => ranks[p.level] >= 3).length], ["Exposição moderada", scoped.filter((p) => p.level === "moderate").length], ["Exposição baixa", scoped.filter((p) => p.level === "low").length]].map(([title, value]) => <div key={title} className={panel}><p className={label}>{title}</p><p className="mt-3 text-3xl font-bold text-slate-900">{value}</p></div>)}</section>
      {!insurer && <nav aria-label="Minhas propriedades" className="flex flex-wrap gap-2">{all.map((p) => <button key={p.id} onClick={() => navigate(p.id)} aria-pressed={selected?.id === p.id} className={`rounded-lg border px-4 py-3 text-sm font-semibold ${selected?.id === p.id ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white"}`}>{p.name}</button>)}</nav>}
      {notice && <p role="status" className="rounded-lg bg-blue-50 p-4 text-sm text-blue-900">{notice}</p>}
      {adding && <form onSubmit={create} className={`${panel} max-w-xl space-y-4`} aria-label="Adicionar fazenda"><h2 className="text-xl font-bold">Adicionar fazenda</h2><p className="text-sm text-slate-500">Cadastro isolado nesta demonstração. Localização e dados ambientais serão consultados automaticamente.</p>{[["nome", "Nome da fazenda"], ["municipio", "Município"], ["estado", "UF"]].map(([name, title]) => <label key={name} className="block text-sm font-medium">{title}<input name={name} required maxLength={name === "estado" ? 2 : 150} className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2" /></label>)}<div className="flex gap-3"><button disabled={busy} className="rounded-lg bg-slate-950 px-4 py-2 text-white disabled:opacity-50">Salvar e analisar</button><button type="button" disabled={busy} onClick={() => setAdding(false)}>Cancelar</button></div></form>}
      {!selected && insurer && !client && <section aria-label="Prioridades dos clientes" className="grid gap-4 lg:grid-cols-3">{clients.map((name) => { const farms = all.filter((p) => p.clientName === name); const top = farms[0]; return <div key={name} className={`${panel} border-t-4 border-t-slate-900`}><div className="flex items-center gap-2"><Building2 className="size-5 text-red-600" /><h2 className="text-xl font-bold">{name}</h2></div><p className="mt-1 text-xs text-slate-500">Identidade demonstrativa · {farms.length} propriedades</p><p className="mb-3 mt-5 font-semibold">Maior exposição: {top.name}</p><RiskBadge level={top.level} /><p className="mt-3 text-sm">{top.score === null ? "Índice indisponível" : `${top.score}/100`} · {top.riskType}</p><div className="mt-4"><Operations property={top} /></div><button onClick={() => navigate("", name)} className="mt-5 text-sm font-bold text-red-700">Abrir cliente →</button></div>; })}</section>}
      {!selected && <section aria-label="Propriedades"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-bold text-slate-900">{insurer ? "Exposição por propriedade" : "Como estão minhas fazendas?"}</h2><label className="text-xs">Ordenar <select value={sort} onChange={(e) => setSort(e.target.value)} className="ml-2 rounded border bg-white p-2"><option value="priority">Prioridade</option><option value="name">Nome</option></select></label></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[...scoped].sort(sort === "name" ? (a, b) => a.name.localeCompare(b.name) : priority).map((p) => <FarmCard key={p.id} property={p} insurer={insurer} onSelect={() => navigate(p.id, insurer ? p.clientName : "")} />)}</div></section>}
      {selected && <section aria-label="Detalhe da fazenda" className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]"><div className="min-w-0 space-y-5"><FarmCard property={selected} insurer={insurer} onSelect={() => {}} /><div className={panel}><h2 className="font-bold">O que fazer agora?</h2>{selected.recommendations?.length ? selected.recommendations.map((r) => <p key={r.ruleId} className="mt-3 text-sm">{r.text}</p>) : <p className="mt-3 text-sm">Nenhuma recomendação específica registrada nesta análise.</p>}{!insurer && selected.score === null && <button disabled={busy} onClick={() => void analyze(selected.id)} className="mt-4 text-sm font-bold text-red-700">Consultar dados ambientais</button>}</div></div><div className={`${panel} min-w-0`}><h2 className="text-xl font-bold">O que está acontecendo?</h2><p className="mt-2 text-sm">{exposureHeading(selected)} · {selected.riskType || "Aguardando análise"}. O índice representa exposição, não probabilidade de sinistro.</p><h3 className="mt-5 font-bold">Por que esse risco foi identificado?</h3><ul className="mt-2 space-y-2 text-sm">{selected.factors.map((f) => <li key={f.key}>{f.description || f.label}</li>)}</ul>{!selected.factors.length && <p className="mt-2 text-sm">Fatores não disponíveis.</p>}<EnvironmentalConditions context={selected.environmentalContext} /></div></section>}
      <section className={panel} aria-label="Mapa do escopo"><h2 className="mb-4 text-xl font-bold">{insurer ? "Mapa de exposição" : "Minhas fazendas no mapa"}</h2><RiskMap properties={mapProperties} machines={data.machines.filter((m) => mapProperties.some((p) => p.id === m.propertyId))} hotspots={data.hotspots.filter((h) => mapProperties.some((p) => p.id === h.propertyId))} perspective={insurer ? "sompo" : "client"} selectedId={selected?.id} onSelect={(p) => navigate(p.id, insurer ? p.clientName : "")} /><p className="mt-3 text-xs text-slate-500">Pontos de referência municipais do IBGE; não representam limites ou localização exata das fazendas. Detecção de calor não confirma incêndio.</p></section>
      {selected && <div className="grid gap-4 md:grid-cols-3"><section className={panel}><h2 className="flex items-center gap-2 font-bold"><Tractor className="size-4" />{insurer ? "Máquinas" : "Minhas máquinas"}</h2>{selected.machines.length ? selected.machines.map((m) => <p key={m.id} className="mt-3 text-sm">{m.name} · {m.machineRisk}</p>) : <p className="mt-3 text-sm">Inventário de máquinas não disponível nesta captura.</p>}</section><section className={panel}><h2 className="font-bold">Alertas</h2><div className="mt-3"><Operations property={selected} /></div></section><section className={panel}><h2 className="font-bold">Histórico</h2><p className="mt-3 text-sm">{selected.history.length ? selected.history.join(" → ") : "Série histórica não disponível nesta captura."}</p></section></div>}
      <RiskAssistant key={`${perspective}:${client}:${selected?.id || "all"}:${data.generatedAt}`} perspective={perspective} clientScope={client || undefined} initialPropertyId={selected?.id} portfolioSnapshot={data.generatedAt} />
    </main>
  </div>;
}
