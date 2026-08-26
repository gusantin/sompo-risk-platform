import { CommandCenter } from "@/components/command-center";
import { getCommandCenterData } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function Home() {
  const data = await getCommandCenterData();
  return <CommandCenter initialData={data} />;
}
