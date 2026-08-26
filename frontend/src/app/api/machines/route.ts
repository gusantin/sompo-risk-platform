import { NextResponse } from "next/server";
import { getPhysicalMachines } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ machines: await getPhysicalMachines() });
}
