import { redirect } from "next/navigation";
import { CommandCenter } from "@/components/command-center";
import { getCommandCenterData } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ mode?: string }> }) {
  const { mode } = await searchParams;
  if (!mode) redirect("/seguradora");
  const data = await getCommandCenterData(mode === "demo" || mode === "portfolio" || mode === "live" ? mode : undefined);
  return <CommandCenter initialData={data} />;
}
