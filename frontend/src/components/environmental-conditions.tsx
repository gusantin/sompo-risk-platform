import type { EnvironmentalContext } from "@/lib/types";

function date(value: string | null | undefined) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" }) : "não informado";
}

export function EnvironmentalConditions({ context, compact = false }: { context?: EnvironmentalContext; compact?: boolean }) {
  if (!context?.sections?.length) return <p className="mt-3 text-xs text-slate-500">Condições ambientais: não disponíveis.</p>;
  const main = context.sections.filter((s) => !/Previsão de (6|12|72)h/.test(s.title));
  const detail = context.sections.filter((s) => /Previsão de (6|12|72)h/.test(s.title));
  function section(s: EnvironmentalContext["sections"][number]) {
    const facts = s.facts.filter((f) => f.value !== null && f.fetchedAt);
    return <div key={s.title} className="min-w-0 rounded-lg bg-slate-50 p-3">
      <h4 className="text-xs font-semibold text-slate-800">{s.title}</h4>
      <ul className="mt-1 space-y-1 text-xs text-slate-600">{s.lines.map((line, i) => <li key={i}>{s.title === "Avisos oficiais" ? line.split(" · ").slice(0, 3).join(" · ") : line}</li>)}</ul>
      {s.title === "Avisos oficiais" && facts.length > 0 && <details className="mt-2 text-xs text-slate-600"><summary className="cursor-pointer">Descrição e vigência dos avisos</summary>{s.lines.map((line, i) => <p className="mt-2" key={i}>{line}</p>)}</details>}
      {!!facts.length && <details className="mt-2 text-[10px] text-slate-500"><summary className="cursor-pointer">Fontes e horários</summary>
        {[...new Map(facts.map((f) => [JSON.stringify([f.source, f.fetchedAt, f.observedAt, f.forecastFor, f.freshness]), f])).values()].map((f, i) => <p key={i} className="mt-1 break-words">{f.source} · {f.freshness === "stale" || (f.fetchedAt && Date.now() - Date.parse(f.fetchedAt) > 21600000) ? "Leitura real desatualizada" : "Última leitura real"} · consulta {date(f.fetchedAt)}{f.observedAt ? ` · observação ${date(f.observedAt)}` : ""}{f.forecastFor ? ` · previsão ${date(f.forecastFor.start)} a ${date(f.forecastFor.end)}` : ""}</p>)}
      </details>}
    </div>;
  }
  return <section aria-label="Condições ambientais" className="mt-4 space-y-2">
    <h3 className="text-sm font-bold text-slate-800">Condições ambientais</h3>
    <p className="text-[10px] text-slate-500">Previsão e condições adicionais não substituem os fatores do risco. Horários de Brasília.</p>
    <div className={compact ? "space-y-2" : "grid gap-2 sm:grid-cols-2"}>{main.map(section)}</div>
    <details className="text-xs text-slate-600"><summary className="cursor-pointer">Previsões de 6h, 12h e 72h</summary><div className="mt-2 grid gap-2">{detail.map(section)}</div></details>
  </section>;
}
