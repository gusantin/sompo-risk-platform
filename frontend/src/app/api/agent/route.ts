import { backendUrl } from "@/lib/backend-config";
import { presentationAnswer } from "@/lib/presentation-assistant";
import { type NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const backend = backendUrl();
  const apiKey = process.env.SOMPO_BACKEND_API_KEY;
  const body = await request.text();
  let parsed;
  try { parsed = JSON.parse(body); } catch { return NextResponse.json({}, { status: 400 }); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return NextResponse.json({}, { status: 400 });
  if (parsed.mode === "portfolio") return presentationAnswer(parsed);
  try {
    if (!backend) throw new Error("Backend not configured");
    const response = await fetch(`${backend}/agent/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(3500),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { status: "erro", codigo: "agent_backend_unavailable", mensagem: "Assistente temporariamente indisponível." },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
