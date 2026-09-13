import { backendUrl, isPresentationDeployment } from "@/lib/backend-config";
export async function POST(request: Request) {
  const base = backendUrl();
  if (isPresentationDeployment() || !base) return Response.json({ mensagem: "Modo apresentação: cadastro e persistência desabilitados neste ambiente. Nenhuma fazenda foi salva." }, { status: 403 });
  const key = process.env.SOMPO_BACKEND_API_KEY;
  let body;
  try { body = await request.json(); } catch { return Response.json({}, { status: 400 }); }
  if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({}, { status: 400 });
  const id = typeof body.analyzeId === "string" && /^demo_portfolio_[a-zA-Z0-9_-]+$/.test(body.analyzeId) ? body.analyzeId : null;
  if (body.analyzeId && !id) return Response.json({}, { status: 400 });
  try {
    const response = await fetch(`${base}/showcase/insured/properties${id ? `/${id}/analyze` : ""}`, {
      method: "POST", headers: { "Content-Type": "application/json", ...(key ? { Authorization: `Bearer ${key}` } : {}) },
      body: JSON.stringify(id ? {} : body), signal: AbortSignal.timeout(180000), cache: "no-store" });
    return new Response(await response.text(), { status: response.status, headers: { "Content-Type": "application/json" } });
  } catch { return Response.json({ mensagem: "Serviço indisponível. O cadastro já salvo permanece aguardando análise." }, { status: 503 }); }
}
