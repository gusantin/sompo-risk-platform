import { type NextRequest, NextResponse } from "next/server";
import { getCommandCenterData } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const data = await getCommandCenterData(request.nextUrl.searchParams.get("mode") ?? undefined);
  return NextResponse.json(data, {
    headers: { "Cache-Control": "no-store" },
  });
}
