import { NextRequest, NextResponse } from "next/server";

const allowedId = /^[a-zA-Z0-9_-]{1,128}$/;
const actionsEnabled = () => process.env.NODE_ENV !== "production" && process.env.SOMPO_ENABLE_ALERT_ACTIONS === "true";
async function proxy(path: string, init: RequestInit = {}) {
  const base = (process.env.SOMPO_BACKEND_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
  const key = process.env.SOMPO_BACKEND_API_KEY;
  const response = await fetch(`${base}${path}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(10000),
    headers: { "Content-Type": "application/json", ...(key ? { Authorization: `Bearer ${key}` } : {}) } });
  if (!response.ok) return NextResponse.json({ error: "Operação indisponível", actionsEnabled: actionsEnabled() }, { status: response.status });
  return NextResponse.json({ ...await response.json(), actionsEnabled: actionsEnabled() }, { headers: { "Cache-Control": "no-store" } });
}
export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("alertId");
  if (id && !allowedId.test(id)) return NextResponse.json({ error: "ID inválido" }, { status: 400 });
  try { return await proxy(id ? `/alertas/${id}/notifications` : "/alertas?limit=100"); }
  catch { return NextResponse.json({ error: "Alertas indisponíveis" }, { status: 503 }); }
}
export async function PATCH(request: NextRequest) {
  // The demo selector is not authentication. Until user auth exists, writes are local opt-in only.
  if (!actionsEnabled()) return NextResponse.json({ error: "Ações desabilitadas neste ambiente" }, { status: 403 });
  // Next dev may normalize nextUrl.hostname to localhost for a 127.0.0.1 request.
  // Compare with the actual Host header; browsers cannot override it. Do not trust forwarded hosts.
  const requestOrigin = `${request.nextUrl.protocol}//${request.headers.get("host")}`;
  if (request.headers.get("origin") !== requestOrigin) return NextResponse.json({ error: "Origem inválida" }, { status: 403 });
  try {
    const body = await request.json();
    if (!allowedId.test(body.alertId ?? "") || !["acknowledged", "resolved"].includes(body.status)) return NextResponse.json({ error: "Dados inválidos" }, { status: 400 });
    return await proxy(`/alertas/${body.alertId}`, { method: "PATCH", body: JSON.stringify({ status: body.status }) });
  } catch { return NextResponse.json({ error: "Não foi possível atualizar o alerta" }, { status: 503 }); }
}
