import "server-only";
import { loadPortfolioData } from "@/lib/backend";

// Read-only context summary. No LLM, providers, risk calculation or persistence.
export async function presentationAnswer(body: Record<string, unknown>) {
  const perspective = body.perspective === "segurado" ? "segurado" : "seguradora";
  if (typeof body.question !== "string" || !body.question.trim() || body.question.length > 1000) {
    return Response.json({ mensagem: "Informe uma pergunta de até 1000 caracteres." }, { status: 400 });
  }
  const data = await loadPortfolioData(false, perspective);
  if (data.source === "unavailable") return Response.json({ mensagem: data.notices[0] }, { status: 503 });
  if (body.snapshotGeneratedAt && body.snapshotGeneratedAt !== data.generatedAt) {
    return Response.json({ mensagem: "A captura mudou. Atualize a página antes de consultar." }, { status: 409 });
  }
  let properties = data.properties;
  if (perspective === "seguradora" && body.clientScope) properties = properties.filter((p) => p.clientName === body.clientScope);
  if (body.contextPropertyId) properties = properties.filter((p) => p.id === body.contextPropertyId);
  if (!properties.length) return Response.json({ mensagem: "Propriedade indisponível neste escopo demonstrativo." }, { status: 404 });
  const ranks = { critical: 4, high: 3, moderate: 2, low: 1, unknown: 0 };
  const levels = { critical: "crítico", high: "alto", moderate: "moderado", low: "baixo", unknown: "indisponível" };
  properties.sort((a, b) => ranks[b.level] - ranks[a.level] || (b.score ?? -1) - (a.score ?? -1));
  const lines = properties.map((p) => [
    `${p.clientName} · ${p.name}: ${p.riskType}, nível ${levels[p.level]}, índice armazenado ${p.score ?? "indisponível"}.`,
    `Leitura original: ${p.analysisTimestamp || "indisponível"}; ${p.provenance?.environmental.state === "stale" ? "desatualizada" : "em cache"}.`,
    ...p.factors.map((f) => f.description || f.label),
    ...p.environmentalValues.map((v) => `${v.label}: ${v.value}.`),
    ...p.hotspotDetails.map((v) => `${v.label}: ${v.value}.`),
    ...p.recommendations?.map((r) => r.text) || [],
    `Fontes: ${p.sources.map((s) => s.name).join(", ") || "indisponíveis"}.`,
    p.operationalState ? `Alertas na captura: ${p.operationalState.openAlerts}.` : "Alertas e entregas não consultados; não é possível confirmar ausência de alertas.",
  ].join(" "));
  return Response.json({ answer: [
    "Consulta determinística da captura, sem interpretação por IA. Identidades fictícias; evidências ambientais reais armazenadas, não ao vivo. Resumo do escopo em ordem de exposição registrada:",
    ...lines,
    "Foco de calor não confirma incêndio. Índice não é probabilidade de sinistro. Para outras interpretações, consulte os detalhes da fazenda; IA indisponível neste modo.",
  ].join("\n\n"), contextPropertyId: body.contextPropertyId || null }, { headers: { "Cache-Control": "no-store" } });
}
