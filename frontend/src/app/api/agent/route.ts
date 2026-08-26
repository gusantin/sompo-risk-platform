import { type NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const backend = (process.env.SOMPO_BACKEND_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
  const apiKey = process.env.SOMPO_BACKEND_API_KEY;
  const body = await request.text();
  try {
    const response = await fetch(`${backend}/agent/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
      },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(125_000),
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
