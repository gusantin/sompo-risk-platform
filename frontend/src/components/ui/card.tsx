import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("rounded-xl border border-slate-200/90 bg-white shadow-[0_1px_2px_rgba(15,23,42,.03)]", className)} {...props} />;
}
