import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em]", {
  variants: {
    variant: {
      default: "border-slate-200 bg-slate-100 text-slate-700",
      outline: "border-slate-300 bg-transparent text-slate-600",
      destructive: "border-red-200 bg-red-50 text-red-700",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
