"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Bot, LoaderCircle, Send, ShieldCheck, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Message {
  role: "user" | "assistant";
  text: string;
}

export function RiskAssistant({ initialPropertyId, available = true, portfolioSnapshot, perspective, clientScope }: { initialPropertyId?: string; available?: boolean; portfolioSnapshot?: string; perspective?: "seguradora" | "segurado"; clientScope?: string }) {
  const suggestions = portfolioSnapshot ? initialPropertyId ? ["Por que minha propriedade está nesse nível?", "Existe algum foco de calor relevante?", "Quando esses dados foram atualizados?"] : ["Qual cliente precisa mais de atenção agora?", "Quais dados são reais e quais são demonstrativos?", "Quando esses dados foram atualizados?"] : initialPropertyId ? ["O que precisa da minha atenção agora?", "Qual máquina merece atenção?", "Algum dado está desatualizado?"] : ["Quais propriedades devo priorizar agora?", "Quais alertas ainda estão abertos?", "Resuma o risco atual da carteira."];
  const [open, setOpen] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [contextPropertyId, setContextPropertyId] = useState<string | null>(initialPropertyId ?? null);
  const [messages, setMessages] = useState<Message[]>([{
    role: "assistant",
    text: perspective === "segurado" ? "Pergunte sobre suas fazendas nesta conta demonstrativa. Somente consulta; fontes e horários acompanham as respostas." : available ? portfolioSnapshot ? "Pergunte sobre a captura da carteira demonstrativa. Clientes fictícios; a origem e a atualização dos dados ambientais acompanham as respostas." : "Olá! Pergunte sobre os riscos das propriedades monitoradas." : "O Copilot consulta dados oficiais. Neste cenário offline, consulte os fatores e recomendações exibidos nos cartões.",
  }]);
  useEffect(() => {
    transcript.current?.scrollTo({ top: transcript.current.scrollHeight });
  }, [messages, loading, open]);

  async function ask(rawQuestion: string) {
    const nextQuestion = rawQuestion.trim();
    if (!available || !nextQuestion || loading) return;
    setMessages((current) => [...current, { role: "user", text: nextQuestion }]);
    setQuestion("");
    setLoading(true);
    try {
      const response = await fetch(perspective ? `/api/perspectives/${perspective}/agent` : "/api/agent", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: nextQuestion,
          ...(clientScope ? { clientScope } : {}),
          ...(portfolioSnapshot ? { mode: "portfolio", snapshotGeneratedAt: portfolioSnapshot } : {}),
          ...(contextPropertyId ? { contextPropertyId } : {}),
        }),
      });
      const payload = await response.json() as {
        answer?: string;
        contextPropertyId?: string | null;
        mensagem?: string;
        error?: { message?: string };
      };
      if (payload.contextPropertyId) setContextPropertyId(payload.contextPropertyId);
      const text = payload.answer || payload.mensagem || payload.error?.message || "Resposta indisponível.";
      setMessages((current) => [...current, { role: "assistant", text }]);
    } catch {
      setMessages((current) => [...current, {
        role: "assistant", text: "Assistente temporariamente indisponível.",
      }]);
    } finally {
      setLoading(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question);
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/25" /><div className="ri-assistant fixed bottom-5 right-5 z-50">
      <Dialog.Content asChild><section aria-label="Assistente de Risco" className="mb-3 flex h-[min(560px,72dvh)] w-[min(390px,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-slate-950 px-4 py-3 text-white">
          <div className="grid size-9 place-items-center rounded-lg bg-red-600"><Bot className="size-5" /></div>
          <div className="min-w-0 flex-1"><Dialog.Title asChild><h2 className="text-sm font-bold">Assistente de Risco</h2></Dialog.Title><Dialog.Description className="text-xs text-slate-300">{portfolioSnapshot ? "Consulta da captura · sem interpretação por IA" : "Análise das propriedades monitoradas"}</Dialog.Description></div>
          <Button type="button" variant="ghost" size="icon" onClick={() => setOpen(false)} className="text-slate-300 hover:bg-white/10 hover:text-white" aria-label="Fechar assistente"><X className="size-4" /></Button>
        </header>
        <div ref={transcript} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          <div className="flex items-center gap-2"><Badge className="border-emerald-200 bg-emerald-50 text-emerald-700"><ShieldCheck className="mr-1 size-3" /> Somente consulta</Badge><span className="text-xs text-slate-600">Respostas baseadas nas informações disponíveis</span></div>
          <div role="log" aria-label="Conversa com o assistente" aria-live="polite" className="space-y-3">{messages.map((message, index) => <div key={`${message.role}-${index}`} className={cn("max-w-[88%] whitespace-pre-wrap break-words rounded-xl px-3 py-2 text-sm leading-relaxed", message.role === "user" ? "ml-auto bg-slate-950 text-white" : "bg-slate-100 text-slate-700")}>{message.text}</div>)}</div>
          {loading && <div role="status" className="flex items-center gap-2 text-xs text-slate-600"><LoaderCircle className="size-4 animate-spin" /> Consultando informações…</div>}
          {available && messages.length === 1 && <div className="space-y-2 pt-2">{(perspective === "segurado" && !initialPropertyId ? ["Qual das minhas fazendas está com maior risco?", "Tenho algum alerta ativo?", "Quando esses dados foram atualizados?"] : suggestions).map((suggestion) => <button key={suggestion} type="button" onClick={() => void ask(suggestion)} className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm text-slate-600 hover:border-slate-300 hover:bg-slate-50">{suggestion}</button>)}</div>}
        </div>
        <form onSubmit={submit} className="border-t border-slate-200 p-3">
          <div className="flex items-end gap-2"><textarea aria-label="Sua pergunta ao assistente" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} rows={2} placeholder="Pergunte sobre risco, fontes, alertas ou máquinas…" className="min-h-16 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-slate-400" /><Button type="submit" size="icon" disabled={!available || loading || !question.trim()} aria-label="Enviar pergunta"><Send className="size-4" /></Button></div>
        </form>
      </section></Dialog.Content>
      <Dialog.Trigger asChild><Button type="button" className="h-12 rounded-full bg-slate-950 px-5 text-white shadow-xl hover:bg-slate-800" aria-expanded={open} aria-label="Abrir Assistente de Risco"><Bot className="mr-2 size-5" /> Assistente de Risco</Button></Dialog.Trigger>
    </div></Dialog.Root>
  );
}
