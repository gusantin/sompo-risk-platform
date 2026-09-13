import { NextRequest } from "next/server";
import { POST as proxy } from "@/app/api/agent/route";
export async function POST(request: NextRequest, { params }: { params: Promise<{ perspective: string }> }) {
  const { perspective } = await params;
  if (perspective !== "segurado" && perspective !== "seguradora") return Response.json({}, { status: 404 });
  let body;
  try { body = await request.json(); } catch { return Response.json({}, { status: 400 }); }
  if (!body || typeof body !== "object" || Array.isArray(body)) return Response.json({}, { status: 400 });
  return proxy(new NextRequest(request.url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: body.question, contextPropertyId: body.contextPropertyId,
      snapshotGeneratedAt: body.snapshotGeneratedAt, mode: "portfolio", perspective,
      ...(perspective === "seguradora" && body.clientScope ? { clientScope: body.clientScope } : {}) }) }));
}
