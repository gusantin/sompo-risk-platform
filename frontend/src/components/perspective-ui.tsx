import { ArrowUpRight, Check, Clock3, MapPin, ShieldCheck } from "lucide-react";
import { RiskBadge } from "@/components/risk-badge";
import { exposureHeading, provenanceLabel } from "@/lib/provenance";
import { deliveryLabels, statusLabels } from "@/lib/operations";
import type { PropertyView } from "@/lib/types";

export function Operations({ property }: { property: PropertyView }) {
  const state = property.operationalState;
  if (!state) return <div className="ri-chips"><span className="ri-chip">Alertas não consultados</span><span className="ri-chip">Entrega não consultada</span></div>;
  return <div className="ri-chips">
    <span className="ri-chip">{state.openAlerts} alertas não resolvidos no recorte</span>
    {state.alerts.map((a, i) => <span key={i} className="ri-chips">
      <span className="ri-chip">Alerta {statusLabels[a.status as keyof typeof statusLabels]?.toLowerCase() || "sem estado informado"}</span>
      {a.notifications.filter((n) => n.channel === "telegram").map((n, j) => <span key={j} className="ri-chip" title={deliveryLabels[n.status]}>{n.status === "delivered" ? "Entrega aceita pelo Telegram" : deliveryLabels[n.status] || "Estado de entrega não informado"}</span>)}
      {!a.notifications.some((n) => n.channel === "telegram") && <span className="ri-chip">Sem entrega registrada</span>}
    </span>)}
    {!state.alerts.length && <span className="ri-chip">Nenhum alerta no recorte · sem entrega registrada</span>}
  </div>;
}

export function Provenance({ property: p }: { property: PropertyView }) {
  return <details className="ri-provenance"><summary><Clock3 size={14} />{provenanceLabel(p)}{p.provenance?.environmental.state === "real_cached" ? " em cache" : ""}<span>Fontes e horários</span></summary>
    <div className="ri-disclosure"><p>Identidade fictícia de apresentação; não representa segurado SOMPO.</p><p>Última leitura ambiental: {p.analysisTimestamp || "Aguardando primeira leitura"}.</p><p>{p.sources.map((s) => s.name).join(" · ") || "Fontes ainda não disponíveis."}</p><p>O índice representa exposição, não probabilidade de sinistro.</p></div>
  </details>;
}

export function PriorityCard({ property: p, onSelect }: { property: PropertyView; onSelect: () => void }) {
  return <article className="ri-priority ri-surface" data-risk={p.level}>
    <div className="ri-between"><span className="ri-eyebrow">{p.clientName}</span><RiskBadge level={p.level} /></div>
    <h3>{p.name}</h3><p className="ri-muted">{p.city} · {p.uf}</p>
    <div className="ri-priority-score"><strong>{p.score ?? "—"}</strong><span>/100 · {p.riskType}<small>{exposureHeading(p)}</small></span></div>
    <ul className="ri-reasons">{p.factors.slice(0, 2).map((f) => <li key={f.key}>{f.label}</li>)}</ul>
    {!p.factors.length && <p className="ri-muted">Aguardando fatores da análise.</p>}
    <Operations property={p} />
    <button className="ri-button ri-button-primary" onClick={onSelect}>Ver situação <ArrowUpRight size={16} /></button>
  </article>;
}

export function FarmRow({ property: p, onSelect, insurer }: { property: PropertyView; onSelect: () => void; insurer: boolean }) {
  return <article data-testid="farm-card" data-property={p.id} className="ri-farm-row">
    <button onClick={onSelect} className="ri-farm-link"><span>{insurer ? p.clientName : "Minha propriedade"}</span><strong>{p.name}<ArrowUpRight size={16} /></strong><span>{p.city} · {p.uf}</span></button>
    <div className="ri-row-risk"><RiskBadge level={p.level} /><span>{p.score === null ? "Aguardando leitura" : `${p.score}/100`} · {p.riskType}</span></div>
    <div className="ri-row-status"><Operations property={p} /></div>
    <div className="ri-row-time"><span>{p.analysisTimestamp ? `${p.analysisTimestamp} · Brasília` : "Primeira leitura pendente"}</span><small>{provenanceLabel(p)}{p.provenance?.environmental.state === "real_cached" ? " em cache" : ""}</small></div>
  </article>;
}

export function PropertyHero({ property: p, insurer, featured = false }: { property: PropertyView; insurer: boolean; featured?: boolean }) {
  return <div className="ri-property-hero ri-surface" data-risk={p.level}>
    <div className="ri-hero-identity"><p className="ri-eyebrow">{insurer ? p.clientName : featured ? "Em destaque · maior exposição das suas fazendas" : "Minha propriedade"}</p>
      <h2 tabIndex={-1}>{p.name}</h2><p className="ri-location"><MapPin size={16} />{p.city} · {p.uf}</p>
      <Provenance property={p} />
    </div>
    <div className="ri-hero-score"><span>{exposureHeading(p)}</span><div><strong>{p.score ?? "—"}</strong>{p.score !== null && <span>/100</span>}</div><div className="ri-chips"><RiskBadge level={p.level} /><span>{p.riskType || "Análise pendente"}</span></div></div>
  </div>;
}

export function Guidance({ property: p }: { property: PropertyView }) {
  return <div className="ri-guidance-grid">
    <section className="ri-guidance ri-surface" aria-label="O que fazer agora"><div className="ri-section-heading"><ShieldCheck size={22} /><h2>O que fazer agora</h2></div>
      {p.recommendations?.length ? <ol>{p.recommendations.map((r, i) => <li key={r.ruleId}><span>{i + 1}</span><p>{r.text}</p></li>)}</ol> : <p className="ri-muted">Nenhuma recomendação específica registrada nesta análise.</p>}
      <p className="ri-caption">Orientações registradas na análise da propriedade.</p>
    </section>
    <section className="ri-context ri-surface" aria-label="O que está acontecendo"><h2>O que está acontecendo?</h2>
      <ul className="ri-reasons">{p.factors.slice(0, 3).map((f) => <li key={f.key}><Check size={16} />{f.label}</li>)}</ul>
      {!p.factors.length && <p className="ri-muted">Aguardando fatores da primeira análise ambiental.</p>}
      <Operations property={p} />
      <details className="ri-provenance"><summary>Entender os fatores do risco</summary><ul className="ri-disclosure">{p.factors.map((f) => <li key={f.key}>{f.description || f.label}</li>)}</ul></details>
    </section>
  </div>;
}
