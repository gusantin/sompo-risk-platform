import { loadPortfolioData } from "@/lib/backend";
export const dynamic = "force-dynamic";
export async function GET(_request: Request, { params }: { params: Promise<{ perspective: string }> }) {
  const { perspective } = await params;
  if (perspective !== "segurado" && perspective !== "seguradora") return Response.json({}, { status: 404 });
  try { return Response.json(await loadPortfolioData(false, perspective)); }
  catch { return Response.json({ mensagem: "Captura indisponível." }, { status: 503 }); }
}
