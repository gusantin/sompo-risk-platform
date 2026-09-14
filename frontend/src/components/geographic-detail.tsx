"use client";

import type { ReactNode, RefObject } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

/** State and property/municipal-reference details share one bounded scroll area. */
export function GeographicDetail({ title, children, returnFocus }: {
  title: string;
  children: ReactNode;
  returnFocus: RefObject<HTMLElement | null>;
}) {
  return <Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px]" />
    <Dialog.Content className="geographic-detail" onCloseAutoFocus={(event) => {
      event.preventDefault();
      // A state-to-property transition mounts another dialog in the same render.
      requestAnimationFrame(() => {
        if (!document.querySelector('[role="dialog"]')) returnFocus.current?.focus({ preventScroll: true });
      });
    }}>
      <header className="geographic-detail-header">
        <span className="font-semibold text-slate-800">Detalhes geográficos</span>
        <Dialog.Close aria-label="Fechar painel" className="geographic-detail-close">
          <X size={20} />
        </Dialog.Close>
      </header>
      <div key={title} className="geographic-detail-scroll" tabIndex={0} role="region" aria-label={`Conteúdo de ${title}`}>
        {children}
      </div>
    </Dialog.Content>
  </Dialog.Portal>;
}
