"use client";

import { FormEvent, useState } from "react";
import { Bot, LoaderCircle, Send, ShieldCheck, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Message {
  role: "user" | "assistant";
  text: string;
}

const suggestions = [
  "Por que Novo Mundo exige atenção?",
  "Existe algum alerta meteorológico ativo?",
  "Qual é o status do ESP32?",
];

export function RiskAssistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [contextPropertyId, setContextPropertyId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([{
    role: "assistant",
    text: "Olá! Pergunte sobre os riscos das propriedades monitoradas.",
  }]);

  async function ask(rawQuestion: string) {
    const nextQuestion = rawQuestion.trim();
    if (!nextQuestion || loading) return;
    setMessages((current) => [...current, { role: "user", text: nextQuestion }]);
    setQuestion("");
    setLoading(true);
    try {
      const response = await fetch("/api/agent", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: nextQuestion,
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
    <div className="fixed bottom-5 right-5 z-50">
      {open && <section aria-label="Assistente de Risco" className="mb-3 flex h-[min(560px,72vh)] w-[min(390px,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-slate-950 px-4 py-3 text-white">
          <div className="grid size-9 place-items-center rounded-lg bg-red-600"><Bot className="size-5" /></div>
          <div className="min-w-0 flex-1"><h2 className="text-sm font-bold">Assistente de Risco</h2><p className="text-[10px] text-slate-400">Análise das propriedades monitoradas</p></div>
          <Button type="button" variant="ghost" size="icon" onClick={() => setOpen(false)} className="text-slate-300 hover:bg-white/10 hover:text-white" aria-label="Fechar assistente"><X className="size-4" /></Button>
        </header>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          <div className="flex items-center gap-2"><Badge className="border-emerald-200 bg-emerald-50 text-emerald-700"><ShieldCheck className="mr-1 size-3" /> Somente consulta</Badge><span className="text-[9px] text-slate-400">Respostas baseadas nas informações disponíveis</span></div>
          {messages.map((message, index) => <div key={`${message.role}-${index}`} className={cn("max-w-[88%] rounded-xl px-3 py-2 text-xs leading-relaxed", message.role === "user" ? "ml-auto bg-slate-950 text-white" : "bg-slate-100 text-slate-700")}>{message.text}</div>)}
          {loading && <div className="flex items-center gap-2 text-xs text-slate-400"><LoaderCircle className="size-4 animate-spin" /> Analisando o risco…</div>}
          {messages.length === 1 && <div className="space-y-2 pt-2">{suggestions.map((suggestion) => <button key={suggestion} type="button" onClick={() => void ask(suggestion)} className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-[11px] text-slate-600 hover:border-slate-300 hover:bg-slate-50">{suggestion}</button>)}</div>}
        </div>
        <form onSubmit={submit} className="border-t border-slate-200 p-3">
          <div className="flex items-end gap-2"><textarea value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} rows={2} placeholder="Pergunte sobre risco, fontes, alertas ou máquinas…" className="min-h-16 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-xs outline-none focus:border-slate-400" /><Button type="submit" size="icon" disabled={loading || !question.trim()} aria-label="Enviar pergunta"><Send className="size-4" /></Button></div>
        </form>
      </section>}
      <Button type="button" onClick={() => setOpen((current) => !current)} className="h-12 rounded-full bg-slate-950 px-5 text-white shadow-xl hover:bg-slate-800" aria-expanded={open} aria-label="Abrir Assistente de Risco"><Bot className="mr-2 size-5" /> Assistente de Risco</Button>
    </div>
  );
}
