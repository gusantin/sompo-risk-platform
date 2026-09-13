"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft, Plus, ShieldCheck } from "lucide-react";
import { EnvironmentalConditions } from "@/components/environmental-conditions";
import { RiskAssistant } from "@/components/risk-assistant";
import { RiskMap } from "@/components/risk-map";
import { FarmRow, Guidance, Operations, PriorityCard, PropertyHero } from "@/components/perspective-ui";
import type { CommandCenterData, PropertyView } from "@/lib/types";
const ranks = { critical: 4, high: 3, moderate: 2, low: 1, unknown: 0 };
const priority = (a: PropertyView, b: PropertyView) => ranks[b.level] - ranks[a.level] || (b.score ?? -1) - (a.score ?? -1);

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
    if (id) requestAnimationFrame(() => {
      const heading = document.querySelector<HTMLElement>(".ri-property-hero h2");
      heading?.focus({ preventScroll: true });
      heading?.scrollIntoView({ block: "start" });
    });
  }
  const all = [...data.properties].sort(priority);
  const scoped = insurer && client ? all.filter((p) => p.clientName === client) : all;
  const selected = scoped.find((p) => p.id === propertyId);
  const clients = [...new Set(all.map((p) => p.clientName).filter((name): name is string => Boolean(name)))];
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
  const featured = selected || (!insurer ? all[0] : undefined);
  const priorities = scoped.filter((p) => ranks[p.level] >= 2).slice(0, 3);
  const operationalKnown = scoped.length > 0 && scoped.every((p) => p.operationalState);
  const openAlerts = operationalKnown ? scoped.reduce((sum, p) => sum + p.operationalState!.openAlerts, 0) : null;
  const evidenceLabel = !all.length ? "Dados ambientais indisponíveis" : all.every((p) => p.environmentalDataOrigin === "real") ? "Evidências ambientais reais · captura armazenada" : "Origem e disponibilidade nos detalhes de cada fazenda";
  const addProperty = () => readOnly ? setNotice("Modo apresentação: cadastro e persistência desabilitados. As fazendas exibidas pertencem à captura armazenada.") : setAdding(true);
  const map = <section className="ri-surface ri-map-section" aria-label="Mapa do escopo"><div className="ri-section-heading"><div><p className="ri-eyebrow">Contexto territorial</p><h2>{insurer ? "Visão geográfica" : "Minhas fazendas no mapa"}</h2></div><span className="ri-muted">{mapProperties.length} {mapProperties.length === 1 ? "propriedade" : "propriedades"} neste recorte</span></div><RiskMap properties={mapProperties} machines={data.machines.filter((m) => mapProperties.some((p) => p.id === m.propertyId))} hotspots={data.hotspots.filter((h) => mapProperties.some((p) => p.id === h.propertyId))} perspective={insurer ? "sompo" : "client"} selectedId={selected?.id} onSelect={(p) => navigate(p.id, insurer ? p.clientName : "")} /><p className="ri-caption">Referências municipais do IBGE, não limites ou localização exata das fazendas. Detecção de calor não confirma incêndio.</p></section>;
  return <div className={`ri-product ${insurer ? "ri-insurer" : "ri-insured"}`}>
    <a className="ri-skip" href="#conteudo">Pular para o conteúdo</a>
    <header className="ri-header"><div className="ri-header-inner"><Link prefetch={false} href={`/${perspective}`} className="ri-brand"><ShieldCheck size={30} /><span><strong>SOMPO</strong><span>Risk Intelligence</span></span></Link><nav aria-label="Perspectiva de demonstração" className="ri-perspectives"><span>Demonstração</span>{["seguradora", "segurado"].map((route) => <Link prefetch={false} key={route} href={`/${route}`} aria-current={perspective === route ? "page" : undefined}>{route === "seguradora" ? "Seguradora" : "Segurado"}</Link>)}</nav></div></header>
    <main id="conteudo" tabIndex={-1} className="ri-main">
      <details className="ri-presentation"><summary><span className="ri-status-dot" />Ambiente demonstrativo <span>{evidenceLabel}</span><span className="ri-disclosure-link">Sobre os dados</span></summary><div className="ri-disclosure"><p>Identidades fictícias, não representam segurados SOMPO. Origem, disponibilidade e horários nos detalhes de cada fazenda. O seletor de perspectiva não é autenticação.</p>{data.notices.map((message, index) => <p key={index}>{message}</p>)}</div></details>
      {insurer && <div className="ri-page-heading"><div><p className="ri-eyebrow">Risk Operations</p><h1>{selected ? "Situação da propriedade" : client || "Onde precisamos agir agora?"}</h1><p className="ri-muted">Exposição registrada, contexto e orientação para uma atuação preventiva.</p></div><span className="ri-chip">Carteira demonstrativa</span></div>}
      {!insurer && <div className="ri-insured-heading"><div><p className="ri-eyebrow">Minha conta · Cliente A</p><h1>Minhas propriedades</h1></div><span className="ri-muted">{all.length} fazendas neste recorte</span></div>}
      {!insurer && <nav aria-label="Minhas propriedades" className="ri-property-switcher"><button onClick={() => navigate()} aria-pressed={!selected}>Visão geral</button>{all.map((p) => <button key={p.id} onClick={() => navigate(p.id)} aria-pressed={selected?.id === p.id}>{p.name}</button>)}<button className="ri-add" onClick={addProperty} aria-label="Adicionar fazenda"><Plus size={16} />Adicionar</button></nav>}
      {(selected || client) && insurer && <button onClick={() => navigate()} className="ri-button ri-button-quiet"><ArrowLeft size={16} />Voltar à carteira</button>}
      {propertyId && !selected && <p role="status" className="ri-notice">Fazenda indisponível neste escopo. Exibindo as propriedades disponíveis.</p>}
      {notice && <p role="status" className="ri-notice">{notice}</p>}
      {adding && <form onSubmit={create} className="ri-surface ri-form" aria-label="Adicionar fazenda"><h2>Adicionar fazenda</h2><p className="ri-muted">Cadastro isolado nesta demonstração. Localização e dados ambientais serão consultados automaticamente.</p>{[["nome", "Nome da fazenda"], ["municipio", "Município"], ["estado", "UF"]].map(([name, title]) => <label key={name}>{title}<input name={name} required maxLength={name === "estado" ? 2 : 150} /></label>)}<div className="ri-chips"><button disabled={busy} className="ri-button ri-button-primary">Salvar e analisar</button><button type="button" disabled={busy} onClick={() => setAdding(false)} className="ri-button">Cancelar</button></div></form>}
      {insurer && !selected && <>
        <section aria-label="Resumo" className="ri-summary ri-surface">{[["Clientes monitorados", new Set(scoped.map((p) => p.clientName)).size, "Neste recorte"], ["Propriedades monitoradas", scoped.length, "Neste recorte"], ["Requerem atenção", scoped.filter((p) => ranks[p.level] >= 3).length, "Exposição alta ou crítica"], ["Alertas não resolvidos", openAlerts ?? "—", operationalKnown ? "Até 20 registros por propriedade" : "Estado ainda não consultado"]].map(([title, value, caption]) => <div key={title}><p>{title}</p><strong>{value}</strong><small>{caption}</small></div>)}</section>
        <section aria-label="Prioridades dos clientes"><div className="ri-section-heading"><div><h2>Prioridades agora</h2><p className="ri-muted">Maiores exposições registradas · severidade antes do índice</p></div><span className="ri-chip">{priorities.length} em destaque</span></div><div className="ri-priorities">{priorities.map((p) => <PriorityCard key={p.id} property={p} onSelect={() => navigate(p.id, p.clientName)} />)}</div>{!priorities.length && <p className="ri-empty">Nenhuma exposição moderada, alta ou crítica registrada neste recorte.</p>}</section>
      </>}
      {featured && <section aria-label={selected ? "Detalhe da fazenda" : "Propriedade em destaque"} className="ri-property-detail" key={featured.id}><PropertyHero property={featured} insurer={insurer} featured={!selected} /><Guidance property={featured} />{!insurer && !readOnly && featured.score === null && <button disabled={busy} onClick={() => void analyze(featured.id)} className="ri-button">Consultar dados ambientais</button>}</section>}
      {insurer && map}
      {!selected && <section aria-label="Propriedades" className="ri-portfolio"><div className="ri-section-heading"><div><h2>{insurer ? "Carteira monitorada" : "Todas as minhas fazendas"}</h2><p className="ri-muted">{insurer ? "Compare a exposição e abra a situação de cada propriedade." : "Selecione uma fazenda para ver suas orientações e evidências."}</p></div><label className="ri-sort">Ordenar <select value={sort} onChange={(e) => setSort(e.target.value)}><option value="priority">Prioridade</option><option value="name">Nome</option></select></label></div>{insurer && <nav aria-label="Clientes da carteira" className="ri-client-filter"><button aria-pressed={!client} onClick={() => navigate()}>Todos os clientes</button>{clients.map((name) => <button key={name} aria-pressed={client === name} onClick={() => navigate("", name)}>{name}</button>)}</nav>}<div className="ri-surface ri-portfolio-list">{[...scoped].sort(sort === "name" ? (a, b) => a.name.localeCompare(b.name) : priority).map((p) => <FarmRow key={p.id} property={p} insurer={insurer} onSelect={() => navigate(p.id, insurer ? p.clientName : "")} />)}{!scoped.length && <p className="ri-empty">Aguardando a captura das propriedades. Consulte a disponibilidade dos dados acima.</p>}</div></section>}
      {featured && <section className="ri-surface ri-environment"><EnvironmentalConditions context={featured.environmentalContext} /></section>}
      {!insurer && map}
      {selected && <details className="ri-surface ri-support"><summary>Máquinas, alertas e histórico <span>Informações complementares</span></summary><div className="ri-support-grid"><section><h2>Máquinas</h2>{selected.machines.length ? selected.machines.map((m) => <p key={m.id}>{m.name} · {m.machineRisk}</p>) : <p className="ri-muted">Inventário de máquinas não disponível nesta captura.</p>}</section><section><h2>Alertas</h2><Operations property={selected} /><p className="ri-caption">Até 20 registros recentes por propriedade.</p></section><section><h2>Histórico</h2><p className="ri-muted">{selected.history.length ? selected.history.join(" → ") : "Série histórica não disponível nesta captura."}</p></section></div></details>}
      <footer className="ri-footer"><span>SOMPO Risk Intelligence</span><span>Informação para prevenção · identidades demonstrativas</span></footer>
      <RiskAssistant key={`${perspective}:${client}:${selected?.id || "all"}:${data.generatedAt}`} perspective={perspective} clientScope={client || undefined} initialPropertyId={selected?.id} portfolioSnapshot={data.generatedAt} />
    </main>
  </div>;
}
