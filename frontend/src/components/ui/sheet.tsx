"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

export function SheetContent({ className, children, ...props }: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out" />
      <DialogPrimitive.Content
        className={cn("fixed inset-y-0 right-0 z-50 w-full max-w-[540px] overflow-y-auto border-l border-slate-200 bg-white p-0 shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-right data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right", className)}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute right-5 top-5 grid size-9 place-items-center rounded-full border border-slate-200 bg-white text-slate-500 hover:text-slate-900" aria-label="Fechar painel">
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;
