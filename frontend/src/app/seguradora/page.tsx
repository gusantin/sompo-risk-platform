import { ProductPerspective } from "@/components/product-perspective";
import { loadPortfolioData } from "@/lib/backend";
export const dynamic = "force-dynamic";
export default async function Page() {
  return <ProductPerspective perspective="seguradora" initialData={await loadPortfolioData(false, "seguradora")} />;
}
