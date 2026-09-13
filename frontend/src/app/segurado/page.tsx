import { ProductPerspective } from "@/components/product-perspective";
import { loadPortfolioData } from "@/lib/backend";
export const dynamic = "force-dynamic";
export default async function Page() {
  return <ProductPerspective perspective="segurado" initialData={await loadPortfolioData(false, "segurado")} />;
}
