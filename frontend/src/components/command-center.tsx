"use client";

import { useMemo, useRef, useState, type RefObject } from "react";
import {
  Activity, AlertTriangle, ArrowRight, BellRing, Building2,
  CheckCircle2, ChevronRight, CircleDot, CloudSun, Cpu, Flame, Gauge,
  MapPin, Radio, RefreshCw, Satellite, Search, ShieldCheck, Signal, Thermometer, Tractor,
  TrendingDown, TrendingUp, Wifi, WifiOff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { RiskBadge, riskLabels } from "@/components/risk-badge";
import { GeographicDetail } from "@/components/geographic-detail";
import { RiskMap } from "@/components/risk-map";
import { RiskSparkline } from "@/components/risk-sparkline";
import { OperationsPanel } from "@/components/operations-panel";
import { RiskAssistant } from "@/components/risk-assistant";
import { ExposureSummary } from "@/components/exposure-summary";
import { EnvironmentalConditions } from "@/components/environmental-conditions";
import { provenanceLabel } from "@/lib/provenance";
import { cn } from "@/lib/utils";
import type { CommandCenterData, HotspotView, LiveEvent, MachineView, PropertyView, RiskLevel, StateSummary } from "@/lib/types";

const severityBorder: Record<RiskLevel, string> = {
  low: "border-l-emerald-500", moderate: "border-l-amber-500", high: "border-l-orange-500",
  critical: "border-l-red-600", unknown: "border-l-slate-300",
};

const eventIcon: Record<LiveEvent["kind"], typeof Flame> = {
  hotspot: Flame, property: Building2, machine: Tractor, device: WifiOff, risk: Activity,
};

function sourceLabel(source: CommandCenterData["source"]) {
  if (source === "live") return "Dados ambientais reais";
  if (source === "backend") return "Dados do backend";
  if (source === "mixed") return "Backend + demonstração";
  if (source === "demo") return "Modo demonstração";
  return "Dados reais indisponíveis";
}

function trendCopy(trend: PropertyView["trend"]) {
  if (trend === "up") return { label: "risco aumentando", icon: TrendingUp, tone: "text-red-600" };
  if (trend === "down") return { label: "risco reduzindo", icon: TrendingDown, tone: "text-emerald-600" };
  if (trend === "stable") return { label: "risco estável", icon: ArrowRight, tone: "text-slate-500" };
  return { label: "tendência indisponível", icon: ArrowRight, tone: "text-slate-400" };
}

const classificationCopy: Record<RiskLevel, string> = {
  low: "Poucos fatores relevantes foram identificados no contexto atual.",
  moderate: "Existem condições que merecem acompanhamento.",
  high: "A avaliação registrada atingiu o nível alto. Consulte os fatores e evidências abaixo.",
  critical: "A avaliação registrada atingiu o nível crítico. Consulte os fatores e evidências abaixo.",
  unknown: "Os dados disponíveis não permitem explicar uma classificação.",
};

function connectionMeta(connection: MachineView["connection"]) {
  if (connection === "online") return { label: "Online", tone: "text-emerald-600", dot: "bg-emerald-500", icon: Wifi };
  if (connection === "stale") return { label: "Dados desatualizados", tone: "text-amber-600", dot: "bg-amber-500", icon: Signal };
  if (connection === "offline") return { label: "Offline", tone: "text-red-600", dot: "bg-red-500", icon: WifiOff };
  return { label: "Sem dados", tone: "text-slate-500", dot: "bg-slate-400", icon: WifiOff };
}

function Kpi({ icon: Icon, label, value, detail, accent }: { icon: typeof Activity; label: string; value: number | string; detail: string; accent?: boolean }) {
  return (
    <Card className="flex min-h-[104px] items-center gap-4 p-4 xl:p-5">
      <div className={cn("grid size-11 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600", accent && "bg-red-50 text-red-600")}><Icon className="size-5" /></div>
      <div className="min-w-0">
        <p className="truncate text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500">{label}</p>
        <div className="mt-1 flex items-baseline gap-2"><strong className="text-2xl font-bold tracking-tight text-slate-950">{value}</strong><span className="truncate text-xs text-slate-400">{detail}</span></div>
      </div>
    </Card>
  );
}

function StateStrip({ state, onSelect }: { state: CommandCenterData["states"][number]; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className="relative w-full min-w-0 px-5 py-4 text-left transition-colors hover:bg-slate-50" aria-label={`Ver carteira em ${state.uf}`}>
      <div className="flex items-center justify-between gap-2">
        <strong className="text-xl font-black tracking-tight text-slate-950">{state.uf}</strong>
        {state.demo && <Badge className="border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[8px] text-violet-700">Carteira demo</Badge>}
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-[.65fr_.65fr_1.35fr_1.35fr]">
        <div className="rounded-md border border-slate-200 bg-white px-3 py-2.5"><p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Monitoradas</p><strong className="mt-1 block text-lg text-slate-900">{state.propertiesMonitored}</strong></div>
        <div className="rounded-md border border-slate-200 bg-white px-3 py-2.5"><p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Alto/crítico</p><strong className="mt-1 block text-lg text-slate-900">{state.highCriticalCount}</strong></div>
        <div className="rounded-md bg-slate-50 px-3 py-2.5">
          <p className="text-[9px] text-slate-400">Maior risco da carteira em {state.uf}</p>
          <div className="mt-1.5 flex items-center justify-between gap-2"><RiskBadge level={state.highestLevel} /><strong className="text-lg text-slate-900">{state.highestScore !== null ? `${state.highestScore}/100` : "—"}</strong></div>
        </div>
        <div className="grid grid-cols-2 gap-3 rounded-md border border-slate-200 bg-white px-3 py-2.5">
          <div><p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Alertas</p><strong className="mt-1 block text-sm text-slate-900">{state.alertCount ?? "—"}</strong></div>
          <div><p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Propriedades com foco no entorno</p><strong className="mt-1 block text-sm text-slate-900">{state.nearbyHotspotCount === null ? "Não disponível" : state.nearbyHotspotCount}</strong></div>
        </div>
      </div>
    </button>
  );
}

function PropertyRow({ property, onSelect }: { property: PropertyView; onSelect: () => void }) {
  const trend = trendCopy(property.trend);
  const TrendIcon = trend.icon;
  return (
    <button type="button" onClick={onSelect} aria-label={`Abrir detalhes de ${property.name}`} className={cn("group w-full border-l-2 px-4 py-3 text-left transition-colors hover:bg-slate-50", severityBorder[property.level])}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2"><strong className="truncate text-sm text-slate-900">{property.name}</strong>{property.propertyDemo && property.environmentalDataOrigin === "real" ? <Badge className="border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[8px] text-emerald-700">Prop. demo · ambiente real</Badge> : property.demo && <Badge className="border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[8px] text-violet-700">Demo</Badge>}</div>
          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500"><MapPin className="size-3" /> {property.city} · {property.uf}</p>
        </div>
        <ChevronRight className="mt-1 size-4 shrink-0 text-slate-300 group-hover:text-slate-600" />
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{property.riskType}</p><div className="mt-1 flex items-center gap-2"><strong className="text-xl text-slate-950">{property.score ?? "—"}<span className="text-xs font-medium text-slate-400">/100</span></strong><RiskBadge level={property.level} /></div></div>
        {property.hotspotDistanceKm !== null && <div className="text-right"><p className="flex items-center justify-end gap-1 text-[10px] font-semibold text-orange-600"><Flame className="size-3" /> Hotspot próximo</p><strong className="text-sm text-slate-800">{property.hotspotDistanceKm.toLocaleString("pt-BR")} km</strong></div>}
      </div>
      <div className="mt-2 border-t border-slate-100 pt-2">
        <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Principais motivos</p>
        {property.factors.length ? <ul className="mt-1 space-y-0.5">{property.factors.slice(0, 3).map((factor) => <li key={factor.key} className="truncate text-[10px] text-slate-600">• {factor.label}</li>)}</ul> : <p className="mt-1 text-[10px] text-slate-400">Motivos detalhados indisponíveis</p>}
      </div>
      <p className={cn("mt-2 flex items-center gap-1 text-[10px] font-semibold", trend.tone)}><TrendIcon className="size-3" /> {trend.label}</p>
    </button>
  );
}

function MachinePanel({ machine, machines, onChange }: { machine: MachineView; machines: MachineView[]; onChange: (machine: MachineView) => void }) {
  const connection = connectionMeta(machine.connection);
  const ConnectionIcon = connection.icon;
  const machineRiskContent = machine.machineRiskStatus === "insufficient_data" ? <span className="text-xs font-bold text-slate-500">Dados insuficientes</span> : <RiskBadge level={machine.machineRisk} />;
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <div>
          <div className="flex items-center gap-2"><span className={cn("size-2 rounded-full", (machine.deviceLinked || machine.demo) ? connection.dot : "bg-slate-400")} /><span className="text-[10px] font-extrabold uppercase tracking-[0.18em] text-slate-500">Máquina monitorada</span>{machine.deviceLinked && <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">Telemetria física</Badge>}{machine.demo && <Badge className="border-violet-300 bg-violet-100 text-violet-800">Dados demonstrativos</Badge>}</div>
          <h2 className="mt-1 text-lg font-bold text-slate-950">{machine.name}</h2>
          <p className="mt-0.5 text-xs text-slate-500">{machine.propertyName}</p>
        </div>
        <div className="flex items-center gap-2">
          {machines.length > 1 && <select aria-label="Selecionar máquina" value={`${machine.propertyId}:${machine.id}`} onChange={(event) => { const next = machines.find((item) => `${item.propertyId}:${item.id}` === event.target.value); if (next) onChange(next); }} className="h-9 max-w-44 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 outline-none">
            {machines.map((item) => <option key={`${item.propertyId}_${item.id}`} value={`${item.propertyId}:${item.id}`}>{item.name}</option>)}
          </select>}
          <span className={cn("flex items-center gap-1.5 rounded-full bg-slate-50 px-3 py-1.5 text-xs font-bold uppercase", (machine.deviceLinked || machine.demo) ? connection.tone : "text-slate-500")}><ConnectionIcon className="size-3.5" /> {(machine.deviceLinked || machine.demo) ? connection.label : "Aguardando dispositivo"}</span>
        </div>
      </div>
      {!machine.deviceLinked && !machine.demo && <div className="flex items-center gap-3 border-b border-slate-200 bg-slate-50 px-5 py-3"><Cpu className="size-5 shrink-0 text-slate-500" /><div><strong className="text-xs text-slate-800">Aguardando dispositivo embarcado</strong><p className="mt-0.5 text-[10px] text-slate-500">Nenhum ESP32 físico está vinculado a esta apresentação. Os níveis abaixo pertencem ao cenário demonstrativo quando marcados como DEMO.</p></div></div>}
      <div className="grid gap-0 lg:grid-cols-[.85fr_1.35fr]">
        <div className="grid grid-cols-2 gap-px bg-slate-200 lg:grid-cols-1">
          <div className="bg-white p-4"><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Dispositivo embarcado</p><div className="mt-2 flex items-center gap-2"><Cpu className="size-5 text-slate-600" /><strong className="text-sm text-slate-900">{machine.demo ? "Dispositivo simulado · DEMO" : machine.deviceLinked ? machine.deviceModel : "Não conectado"}</strong></div></div>
          <div className="bg-white p-4"><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Última comunicação</p><div className="mt-2 flex items-center gap-2"><Radio className="size-5 text-slate-600" /><strong className="text-sm text-slate-900">{machine.lastCommunication}</strong></div></div>
          <div className="bg-white p-4"><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Temperatura</p><div className="mt-2 flex items-center gap-2"><Thermometer className="size-5 text-slate-600" />{machine.temperature ? <div><strong className="text-sm text-slate-900">{machine.temperature.value.toLocaleString("pt-BR")} {machine.temperature.unit}</strong><p className="text-[9px] text-slate-400">{machine.temperature.scopeLabel}</p></div> : <div><strong className="text-sm text-slate-500">Leitura indisponível</strong><p className="text-[9px] text-slate-400">{machine.connection === "stale" ? "O último valor não é exibido como atual" : machine.connection === "offline" ? "Dispositivo sem comunicação recente" : "Aguardando primeira leitura"}</p></div>}</div></div>
          <div className="bg-white p-4"><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Umidade</p><div className="mt-2 flex items-center gap-2"><Gauge className="size-5 text-slate-600" />{machine.humidity ? <div><strong className="text-sm text-slate-900">{machine.humidity.value.toLocaleString("pt-BR")} {machine.humidity.unit}</strong><p className="text-[9px] text-slate-400">{machine.humidity.scopeLabel}</p></div> : <div><strong className="text-sm text-slate-500">Leitura indisponível</strong><p className="text-[9px] text-slate-400">{machine.connection === "stale" ? "O último valor não é exibido como atual" : machine.connection === "offline" ? "Dispositivo sem comunicação recente" : "Aguardando primeira leitura"}</p></div>}</div></div>
        </div>
        <div className="p-5">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">Contextos separados no backend</p>
          <div className="mt-4 flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1 rounded-lg border border-sky-200 bg-sky-50/60 p-3"><div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-sky-800"><CloudSun className="size-4" /> Ambiente</div><p className="mt-1 text-[9px] text-sky-700">APIs / clima / satélite / hotspots</p><div className="mt-2"><RiskBadge level={machine.environmentalRisk} /></div></div>
            <span className="grid place-items-center text-slate-300"><span className="hidden sm:block">+</span><span className="sm:hidden">+</span></span>
            <div className="min-w-0 flex-1 rounded-lg border border-amber-200 bg-amber-50/60 p-3"><div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-amber-800"><Cpu className="size-4" /> Máquina</div><p className="mt-1 text-[9px] text-amber-700">ESP32 / sensores embarcados</p><div className="mt-2">{machineRiskContent}</div></div>
            <ArrowRight className="mx-1 hidden size-5 shrink-0 text-slate-300 sm:block" />
            <div className="min-w-0 flex-1 rounded-lg border border-slate-900 bg-slate-950 p-3 text-white"><div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-wider text-slate-200"><ShieldCheck className="size-4" /> Risco operacional</div><p className="mt-1 text-[9px] text-slate-400">cruzamento dos dois contextos</p><div className="mt-2"><RiskBadge level={machine.operationalRisk} /></div></div>
          </div>
          <p className="mt-3 text-[10px] leading-relaxed text-slate-400">“Motor” só é exibido quando `scope` e `target` do sensor confirmam esse contexto. Sem semântica configurada, a interface informa o escopo desconhecido.</p>
        </div>
      </div>
      <div className="space-y-2 border-t border-slate-200 p-4 text-xs text-slate-600">
        <p><strong>Telemetria:</strong> {machine.demo ? "DEMO · estado simulado" : machine.telemetryFreshness === "fresh" ? "Atual na consulta" : machine.telemetryFreshness === "stale" ? "Desatualizada" : machine.demo ? "DEMO" : "Indisponível / insuficiente"}</p>
        <p><strong>Sensores configurados:</strong> {machine.configuredSensors?.length ? machine.configuredSensors.map((sensor) => `${sensor.id} · ${sensor.type} (${sensor.scope})`).join("; ") : "Configuração indisponível neste snapshot."}</p>
        <p><strong>GPS:</strong> {machine.location?.current && Number.isFinite(machine.location.latitude) && Number.isFinite(machine.location.longitude) ? `${machine.location.latitude.toFixed(5)}, ${machine.location.longitude.toFixed(5)} · atual na consulta` : "Posição atual indisponível"}</p>
        {machine.recommendations?.map((r) => <p key={r.ruleId} className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950"><strong>Ação preventiva:</strong> {r.text}</p>)}
      </div>
    </Card>
  );
}

function PropertyDrawer({ property, onClose, returnFocus }: { property: PropertyView | null; onClose: () => void; returnFocus: RefObject<HTMLElement | null> }) {
  return (
    <Sheet open={Boolean(property)} onOpenChange={(open) => { if (!open) onClose(); }}>
      {property && <GeographicDetail key={property.id} title={property.name} returnFocus={returnFocus}>
        <div className="geographic-detail-heading"><SheetTitle className="text-xl font-bold text-slate-950">{property.name}</SheetTitle><SheetDescription className="mt-1 text-sm text-slate-600">{property.city} · {property.uf}</SheetDescription></div>
        <div className="px-6 pt-5 text-xs text-slate-600">{property.clientName && <p>{property.clientName} · identidade demonstrativa</p>}<p>{provenanceLabel(property)} · {property.analysisTimestamp ?? "Atualização indisponível"}</p>{property.coordinateDisclosure && <p className="mt-2">{property.coordinateDisclosure}</p>}</div>
        <div className="border-b border-slate-200 bg-slate-50 px-6 pb-5 pt-6">
          <Badge className={property.environmentalDataOrigin === "real" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-violet-300 bg-violet-100 text-violet-800"}>{property.propertyDemo && property.environmentalDataOrigin === "real" ? "Propriedade demonstrativa — condições ambientais reais" : property.demo ? "Cenário demonstrativo" : property.environmentalDataOrigin === "real" ? "Dados ambientais reais" : "Dados indisponíveis"}</Badge>
          <p className="mt-4 text-[9px] font-black uppercase tracking-[0.18em] text-red-600">Por que esta propriedade exige atenção?</p>
          <div className="mt-4 grid grid-cols-2 gap-2 rounded-lg border border-slate-200 bg-white p-3 text-xs"><div><p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Latitude</p><strong className="mt-1 block text-slate-800">{Number.isFinite(property.latitude) ? property.latitude.toFixed(6) : "Não disponível"}</strong></div><div><p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Longitude</p><strong className="mt-1 block text-slate-800">{Number.isFinite(property.longitude) ? property.longitude.toFixed(6) : "Não disponível"}</strong></div></div>
          <div className="mt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Tipo de risco · {property.riskType}</p><p className="mt-1 text-[10px] text-slate-500">Índice de risco e nível</p><div className="mt-1 flex items-center gap-3"><strong className="text-4xl tracking-tight text-slate-950">{property.score ?? "—"}<span className="text-base font-medium text-slate-400">/100</span></strong><RiskBadge level={property.level} /></div></div>
        </div>
        <div className="space-y-6 p-6">
          <section><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Tendência recente</h3><span className={cn("text-xs font-semibold", trendCopy(property.trend).tone)}>{trendCopy(property.trend).label}</span></div>{property.history.length > 1 ? <div className="mt-3 rounded-lg border border-slate-200 p-3"><RiskSparkline values={property.history} level={property.level} /></div> : <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">Histórico insuficiente para exibir tendência gráfica.</p>}</section>
          <Separator />
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Qualidade e cobertura</h3><div className="mt-3 rounded-lg border border-slate-200 p-3"><div className="grid grid-cols-2 gap-3"><div><span className="text-[10px] text-slate-500">Qualidade dos dados</span><strong className="mt-1 block text-sm text-slate-800">{property.confidence ?? "Não disponível"}</strong></div><div><span className="text-[10px] text-slate-500">Cobertura</span><strong className="mt-1 block text-sm text-slate-800">{property.coveragePercent !== null ? `${property.coveragePercent}%` : "Não disponível"}</strong></div></div><p title="Representa a qualidade e cobertura das informações utilizadas no cálculo. Não representa chance de ocorrência do sinistro." className="mt-2 cursor-help text-[10px] text-slate-400">Representa qualidade e cobertura das informações; não é probabilidade de sinistro.</p><div className="mt-3 flex flex-wrap gap-1.5">{property.coverage.length ? property.coverage.map((item) => <span key={item.label} className={cn("rounded-full border px-2 py-1 text-[9px] font-semibold", item.available === true ? "border-emerald-200 bg-emerald-50 text-emerald-700" : item.available === false ? "border-slate-200 bg-slate-50 text-slate-500" : "border-slate-200 text-slate-400")}>{item.label}: {item.available === true ? "disponível" : item.available === false ? "ausente" : "não informado"}</span>) : <span className="text-xs text-slate-400">Cobertura não disponível no snapshot.</span>}</div></div></section>
          <Separator />
          <section><div className="flex items-center justify-between gap-3"><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Explicação da classificação</h3><RiskBadge level={property.level} /></div><p className="mt-2 text-xs leading-relaxed text-slate-600"><strong>{riskLabels[property.level]}.</strong> {classificationCopy[property.level]}</p><p className="mt-1 text-[10px] text-slate-400">Explica a categoria do índice; não significa probabilidade de sinistro.</p></section>
          <Separator />
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Por quê</h3><div className="mt-3 space-y-3"><div className="rounded-lg border border-slate-200 p-3"><p className="text-[10px] font-black uppercase tracking-[0.15em] text-sky-700">Na avaliação registrada</p>{property.factors.length ? <div className="mt-2 space-y-2">{property.factors.map((factor) => <div key={factor.key} className="flex gap-2"><CircleDot className="mt-0.5 size-4 shrink-0 text-red-500" /><div><strong className="text-xs text-slate-800">{factor.label}</strong>{factor.description && <p className="mt-0.5 text-[10px] leading-relaxed text-slate-500">{factor.description}</p>}</div></div>)}</div> : <p className="mt-2 text-xs text-slate-400">Motivos detalhados indisponíveis.</p>}</div><div className="rounded-lg border border-slate-200 p-3"><p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-700">Histórico</p>{property.historyDetails.length ? <dl className="mt-2 space-y-2">{property.historyDetails.map((item) => <div key={item.label} className="flex justify-between gap-3 text-xs"><dt className="text-slate-500">{item.label}</dt><dd className="font-semibold text-slate-800">{item.value}</dd></div>)}</dl> : <p className="mt-2 text-xs text-slate-400">Histórico não disponível.</p>}</div><div className="rounded-lg border border-slate-200 p-3"><p className="text-[10px] font-black uppercase tracking-[0.15em] text-emerald-700">Contexto da propriedade</p>{property.contextDetails.length ? <dl className="mt-2 space-y-2">{property.contextDetails.map((item) => <div key={item.label} className="text-xs"><dt className="text-slate-500">{item.label}</dt><dd className="mt-0.5 font-semibold text-slate-800">{item.value}</dd></div>)}</dl> : <p className="mt-2 text-xs text-slate-400">Contexto não disponível.</p>}</div></div></section>
          <Separator />
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Valores ambientais participantes</h3>{property.environmentalValues.length ? <dl className="mt-3 grid grid-cols-2 gap-2">{property.environmentalValues.map((item) => <div key={`${item.label}_${item.value}`} className="rounded-lg bg-slate-50 p-3"><dt className="text-[9px] font-bold uppercase text-slate-400">{item.label}</dt><dd><p className="mt-1 text-sm font-semibold text-slate-800">{item.value}</p>{item.source && <p className="mt-1 text-[9px] font-semibold text-sky-700">{item.source}</p>}{item.updatedLabel && <p className="mt-0.5 text-[9px] text-slate-400">Atualizado {item.updatedLabel}</p>}</dd></div>)}</dl> : <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">Valores ambientais não disponíveis no snapshot atual. Nenhum valor foi inferido.</p>}</section>
          <Separator />
          {property.riskType === "Incêndio" && <section className={cn("rounded-xl p-4", property.hotspotDistanceKm !== null ? "border border-orange-200 bg-orange-50" : "border border-slate-200 bg-slate-50")}><div className="flex items-center justify-between"><div className={cn("flex items-center gap-2 text-sm font-bold", property.hotspotDistanceKm !== null ? "text-orange-800" : "text-slate-600")}><Flame className="size-5" /> Foco de calor mais próximo</div><strong className={cn("text-xl", property.hotspotDistanceKm !== null ? "text-orange-900" : "text-slate-400")}>{property.hotspotDistanceKm !== null ? `${property.hotspotDistanceKm.toLocaleString("pt-BR")} km` : "Não disponível"}</strong></div>{property.hotspotDetails.length > 0 && <dl className="mt-3 space-y-1">{property.hotspotDetails.map((item) => <div key={item.label} className="flex justify-between gap-3 text-xs"><dt className="text-slate-500">{item.label}</dt><dd className="font-medium text-slate-700">{item.value}</dd></div>)}</dl>}<p className="mt-2 text-[10px] text-slate-500">{property.hotspotDistanceKm !== null ? "Foco de calor não confirma incêndio atingindo a propriedade." : "Distância de foco recente indisponível neste snapshot."}</p></section>}
          <Separator />
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Timestamp e freshness</h3><div className="mt-3 grid grid-cols-2 gap-2"><div className="rounded-lg bg-slate-50 p-3"><p className="text-[9px] uppercase text-slate-400">Última análise</p><strong className="mt-1 block text-xs text-slate-700">{property.analysisTimestamp ?? "Não disponível"}</strong></div><div className="rounded-lg bg-slate-50 p-3"><p className="text-[9px] uppercase text-slate-400">Freshness</p><strong className="mt-1 block text-xs text-slate-700">{property.analysisFreshness}</strong></div></div></section>
          <Separator />
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Fontes utilizadas</h3>{property.sources.length ? <div className="mt-3 space-y-2">{property.sources.map((source) => <div key={source.name} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2"><div><strong className="text-xs text-slate-700">{source.name}</strong><p className="mt-0.5 text-[9px] text-slate-400">{source.updatedLabel ? `Atualizado ${source.updatedLabel}` : "Horário de atualização não informado"}</p></div><span className="text-[10px] font-bold uppercase text-slate-500">{source.status}{source.cacheHit === true ? " · cache" : ""}</span></div>)}</div> : <p className="mt-3 text-xs text-slate-500">Fontes não disponíveis no snapshot atual.</p>}</section>
          <Separator />
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Máquinas</h3>{property.machines.length ? <div className="mt-3 space-y-2">{property.machines.map((machine) => { const status = connectionMeta(machine.connection); return <div key={machine.id} className="flex items-center justify-between rounded-lg border border-slate-200 p-3"><div><strong className="text-sm text-slate-900">{machine.name}</strong><p className="mt-0.5 text-[10px] text-slate-400">{machine.deviceLinked ? machine.deviceModel : "Aguardando dispositivo embarcado"}</p></div><div className="text-right"><span className={cn("text-[10px] font-bold uppercase", machine.deviceLinked ? status.tone : "text-slate-400")}>{machine.deviceLinked ? status.label : "não vinculado"}</span><div className="mt-1">{machine.machineRiskStatus === "insufficient_data" ? <span className="text-[10px] font-semibold text-slate-500">Dados insuficientes</span> : <RiskBadge level={machine.machineRisk} />}</div></div></div>; })}</div> : <p className="mt-3 text-sm text-slate-400">Nenhuma máquina disponível no snapshot atual.</p>}</section>
        </div>
        <div className="px-6 pb-6"><EnvironmentalConditions context={property.environmentalContext} /></div>
      </GeographicDetail>}
    </Sheet>
  );
}

function StateDrawer({ state, properties, onClose, onProperty, returnFocus }: {
  state: StateSummary | null;
  returnFocus: RefObject<HTMLElement | null>;
  properties: PropertyView[];
  onClose: () => void;
  onProperty: (property: PropertyView) => void;
}) {
  const stateProperties = state ? properties.filter((property) => property.uf === state.uf) : [];
  const hasRealEnvironment = stateProperties.some((property) => property.environmentalDataOrigin === "real");
  return (
    <Sheet open={Boolean(state)} onOpenChange={(open) => { if (!open) onClose(); }}>
      {state && <GeographicDetail key={state.uf} title={state.uf} returnFocus={returnFocus}>
        <div className="geographic-detail-heading"><SheetTitle className="text-xl font-bold text-slate-950">{state.uf}</SheetTitle><SheetDescription className="mt-1 text-sm text-slate-600">Propriedades monitoradas disponíveis neste estado</SheetDescription></div>
        <div className="border-b border-slate-200 bg-slate-50 px-6 pb-5 pt-6">
          <Badge>{state.demo ? `Carteira demonstrativa${hasRealEnvironment ? " · ambiente real" : ""}` : "Carteira SOMPO"} · não é risco territorial</Badge>
          <div className="mt-5 grid grid-cols-3 gap-2"><div className="rounded-lg bg-white p-3"><p className="text-[9px] uppercase text-slate-400">Monitoradas</p><strong className="text-xl">{state.propertiesMonitored}</strong></div><div className="rounded-lg bg-white p-3"><p className="text-[9px] uppercase text-slate-400">Alto/crítico</p><strong className="text-xl">{state.highCriticalCount}</strong></div><div className="rounded-lg bg-white p-3"><p className="text-[9px] uppercase text-slate-400">Alertas</p><strong className="text-xl">{state.alertCount ?? "—"}</strong></div></div>
        </div>
        <div className="p-6"><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Propriedades da carteira</h3>{stateProperties.length ? <div className="mt-3 space-y-2">{stateProperties.map((property) => <button type="button" key={property.id} onClick={() => onProperty(property)} className="geographic-state-property grid w-full grid-cols-1 items-center gap-3 rounded-lg border border-slate-200 p-3 text-left hover:bg-slate-50 sm:grid-cols-[minmax(0,1fr)_max-content]"><div><div className="flex flex-wrap items-center gap-2"><strong className="text-sm text-slate-900">{property.name}</strong>{property.propertyDemo && <Badge className={property.environmentalDataOrigin === "real" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-violet-200 bg-violet-50 text-violet-700"}>{property.environmentalDataOrigin === "real" ? "Ambiente real" : "Demo"}</Badge>}</div><p className="mt-0.5 text-[10px] text-slate-500">{property.city} · {property.uf}</p></div><div className="text-left sm:text-right"><strong className="text-sm text-slate-800">{property.score ?? "—"}/100</strong><div className="mt-1"><RiskBadge level={property.level} /></div></div></button>)}</div> : <p className="mt-3 rounded-lg bg-slate-50 p-4 text-sm text-slate-500">Nenhuma propriedade disponível nesta UF.</p>}</div>
      </GeographicDetail>}
    </Sheet>
  );
}

function HotspotDrawer({ hotspot, hotspots, properties, onClose, onSelect }: {
  hotspot: HotspotView | null;
  hotspots: HotspotView[];
  properties: PropertyView[];
  onClose: () => void;
  onSelect: (hotspot: HotspotView) => void;
}) {
  const property = hotspot?.propertyId ? properties.find((item) => item.id === hotspot.propertyId) : undefined;
  return (
    <Sheet open={Boolean(hotspot)} onOpenChange={(open) => { if (!open) onClose(); }}>
      {hotspot && <SheetContent>
        <div className="border-b border-slate-200 bg-slate-50 px-6 pb-5 pt-6">
          <div className="flex items-center gap-2"><Badge>Evento observado</Badge>{hotspot.demo ? <Badge className="border-violet-200 bg-violet-50 text-violet-700">Cenário demonstrativo</Badge> : <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">Dados reais</Badge>}</div>
          <SheetTitle className="mt-4 pr-12 text-2xl font-bold text-slate-950">Focos recentes</SheetTitle>
          <SheetDescription className="mt-1 text-sm text-slate-500">Detalhes retornados pela fonte disponível</SheetDescription>
        </div>
        <div className="space-y-6 p-6">
          <section className="rounded-xl border border-orange-200 bg-orange-50 p-4"><div className="flex items-center gap-2 text-sm font-bold text-orange-800"><Flame className="size-5" /> Foco selecionado</div><dl className="mt-4 grid grid-cols-2 gap-3 text-xs"><div><dt className="text-orange-700/70">Detectado</dt><dd className="mt-1 font-bold text-orange-950">{hotspot.detectedAt ?? "Horário não disponível"}</dd></div><div><dt className="text-orange-700/70">Tempo decorrido</dt><dd className="mt-1 font-bold text-orange-950">{hotspot.detectedLabel}</dd></div>{hotspot.distanceKm !== undefined && <div><dt className="text-orange-700/70">Distância</dt><dd className="mt-1 font-bold text-orange-950">{hotspot.distanceKm.toLocaleString("pt-BR")} km da propriedade</dd></div>}<div><dt className="text-orange-700/70">Fonte</dt><dd className="mt-1 font-bold text-orange-950">{hotspot.source}</dd></div>{hotspot.satellite && <div><dt className="text-orange-700/70">Satélite</dt><dd className="mt-1 font-bold text-orange-950">{hotspot.satellite}</dd></div>}<div><dt className="text-orange-700/70">Coordenadas</dt><dd className="mt-1 font-bold text-orange-950">{hotspot.latitude.toFixed(5)}, {hotspot.longitude.toFixed(5)}</dd></div></dl>{property && <p className="mt-3 text-xs text-orange-800">Relacionado a {property.name} · {property.city}/{property.uf}</p>}<p className="mt-3 text-[10px] text-orange-700">Foco de calor por satélite não confirma incêndio acontecendo na propriedade.</p></section>
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Outros focos retornados</h3><div className="mt-3 space-y-2">{hotspots.filter((item) => item.id !== hotspot.id).slice(0, 6).map((item) => <button type="button" key={item.id} onClick={() => onSelect(item)} className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left hover:bg-slate-50"><div><strong className="text-xs text-slate-800">{item.detectedAt ?? item.detectedLabel}</strong><p className="text-[9px] text-slate-400">{item.latitude.toFixed(3)}, {item.longitude.toFixed(3)}</p></div><span className="text-[10px] text-slate-500">{item.distanceKm !== undefined ? `${item.distanceKm.toLocaleString("pt-BR")} km` : item.source}</span></button>)}</div></section>
        </div>
      </SheetContent>}
    </Sheet>
  );
}

function EventDrawer({ event, property, onClose, onProperty }: {
  event: LiveEvent | null;
  property: PropertyView | null;
  onClose: () => void;
  onProperty: (property: PropertyView) => void;
}) {
  return (
    <Sheet open={Boolean(event)} onOpenChange={(open) => { if (!open) onClose(); }}>
      {event && <SheetContent>
        <div className="border-b border-slate-200 bg-slate-50 px-6 pb-5 pt-6">
          <div className="flex items-center gap-2"><Badge className={event.category === "alert" ? "border-red-200 bg-red-50 text-red-700" : "border-sky-200 bg-sky-50 text-sky-700"}>{event.category === "alert" ? event.alertStatus === "resolved" ? "Alerta resolvido · histórico" : event.alertStatus === "acknowledged" ? "Alerta reconhecido" : "Alerta · precisa de atenção" : "Evento · algo aconteceu"}</Badge>{event.demo ? <Badge className="border-violet-200 bg-violet-50 text-violet-700">Cenário demonstrativo</Badge> : <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">Dados reais</Badge>}</div>
          <SheetTitle className="mt-4 pr-12 text-2xl font-bold text-slate-950">{event.title}</SheetTitle>
          <SheetDescription className="mt-1 text-sm text-slate-500">{event.eventType}</SheetDescription>
        </div>
        <div className="space-y-6 p-6">
          <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">{event.category === "alert" ? "Detalhes do alerta" : "O que aconteceu"}</h3><dl className="mt-3 space-y-3 rounded-lg border border-slate-200 p-4 text-xs"><div><dt className="text-slate-400">Tipo do evento</dt><dd className="mt-0.5 font-bold text-slate-800">{event.eventType}</dd></div>{event.sourceSeverity && <div><dt className="text-slate-400">Severidade da fonte</dt><dd className="mt-0.5 font-bold text-slate-800">{event.sourceSeverity}</dd></div>}{event.propertyName && <div><dt className="text-slate-400">Relacionado a</dt><dd className="mt-0.5 font-bold text-slate-800">{event.propertyName}</dd></div>}{event.location && <div><dt className="text-slate-400">Local informado pela fonte</dt><dd className="mt-0.5 font-bold leading-relaxed text-slate-800">{event.location}</dd></div>}{event.city && event.uf && <div><dt className="text-slate-400">Local</dt><dd className="mt-0.5 font-bold text-slate-800">{event.city} · {event.uf}</dd></div>}{event.machineName && <div><dt className="text-slate-400">Máquina</dt><dd className="mt-0.5 font-bold text-slate-800">{event.machineName}</dd></div>}{event.distanceKm !== undefined && <div><dt className="text-slate-400">Distância</dt><dd className="mt-0.5 font-bold text-slate-800">{event.distanceKm.toLocaleString("pt-BR")} km da propriedade</dd></div>}{event.detectedAt && <div><dt className="text-slate-400">Detectado</dt><dd className="mt-0.5 font-bold text-slate-800">{event.detectedAt}</dd></div>}{event.startsAt && <div><dt className="text-slate-400">Início</dt><dd className="mt-0.5 font-bold text-slate-800">{event.startsAt}</dd></div>}{event.endsAt && <div><dt className="text-slate-400">Fim</dt><dd className="mt-0.5 font-bold text-slate-800">{event.endsAt}</dd></div>}{!event.startsAt && <div><dt className="text-slate-400">Tempo decorrido</dt><dd className="mt-0.5 font-bold text-slate-800">{event.timeLabel}</dd></div>}{event.source && <div><dt className="text-slate-400">Fonte</dt><dd className="mt-0.5 font-bold text-slate-800">{event.source}</dd></div>}{event.satellite && <div><dt className="text-slate-400">Satélite</dt><dd className="mt-0.5 font-bold text-slate-800">{event.satellite}</dd></div>}{event.latitude !== undefined && event.longitude !== undefined && <div><dt className="text-slate-400">Coordenadas</dt><dd className="mt-0.5 font-bold text-slate-800">{event.latitude.toFixed(5)}, {event.longitude.toFixed(5)}</dd></div>}</dl>{event.category === "alert" && <div className="mt-3 rounded-lg bg-slate-50 p-4 text-xs leading-relaxed text-slate-600"><p>{event.description}</p>{event.hailExplicit && <p className="mt-2 font-bold text-slate-800">Granizo mencionado explicitamente no aviso do INMET.</p>}</div>}</section>
          {event.recommendations?.map((r) => <p key={r.ruleId} className="rounded-lg bg-amber-50 p-3 text-sm">{r.text}<span className="block text-xs">Regra: {r.ruleId} · orientação operacional.</span></p>)}
          {event.previousLevel && event.currentLevel && <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Mudança registrada</h3><div className="mt-3 flex items-center gap-3"><RiskBadge level={event.previousLevel} /><ArrowRight className="size-4 text-slate-400" /><RiskBadge level={event.currentLevel} /></div></section>}
          {event.factors.length > 0 && <section><h3 className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">Principais mudanças</h3><div className="mt-3 space-y-2">{event.factors.map((factor) => <div key={factor.key} className="rounded-lg bg-slate-50 p-3"><strong className="text-xs text-slate-800">{factor.label}</strong>{factor.description && <p className="mt-1 text-[10px] text-slate-500">{factor.description}</p>}</div>)}</div></section>}
          {property && <section className="rounded-lg bg-slate-950 p-4 text-white"><p className="text-[9px] uppercase tracking-wider text-slate-400">Risco atual da propriedade</p><div className="mt-2 flex items-center gap-3"><strong className="text-2xl">{property.score ?? "—"}/100</strong><RiskBadge level={property.level} /></div><Button type="button" variant="outline" size="sm" className="mt-4" onClick={() => onProperty(property)}>Ver propriedade</Button></section>}
        </div>
      </SheetContent>}
    </Sheet>
  );
}

export function CommandCenter({ initialData }: { initialData: CommandCenterData }) {
  const [data, setData] = useState(initialData);
  const [query, setQuery] = useState("");
  const [selectedProperty, setSelectedProperty] = useState<PropertyView | null>(null);
  const geographicReturnFocus = useRef<HTMLElement | null>(null);
  function openProperty(property: PropertyView) {
    if (!(document.activeElement as HTMLElement)?.closest('[role="dialog"]')) geographicReturnFocus.current = document.activeElement as HTMLElement;
    setSelectedProperty(property);
  }
  const [selectedState, setSelectedState] = useState<StateSummary | null>(null);
  const [selectedHotspot, setSelectedHotspot] = useState<HotspotView | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<LiveEvent | null>(null);
  const [selectedMachine, setSelectedMachine] = useState<MachineView | null>(initialData.machines[0] ?? null);
  const [refreshing, setRefreshing] = useState(false);
  const [perspective, setPerspective] = useState<"sompo" | "client">("sompo");
  const [clientProperty, setClientProperty] = useState("");
  const [refreshError, setRefreshError] = useState("");

  const normalizedQuery = query.trim().toLocaleLowerCase("pt-BR");
  const visibleProperties = useMemo(() => {
    const rank = { critical: 4, high: 3, moderate: 2, low: 1, unknown: 0 };
    const sorted = data.properties.filter((p) => perspective === "sompo" || p.id === (clientProperty || data.properties[0]?.id)).sort((a, b) => rank[b.level] - rank[a.level] || (b.score ?? -1) - (a.score ?? -1));
    if (!normalizedQuery) return sorted;
    return sorted.filter((property) => [property.name, property.city, property.uf, `${property.latitude}`, `${property.longitude}`].some((value) => value.toLocaleLowerCase("pt-BR").includes(normalizedQuery)));
  }, [data.properties, normalizedQuery, perspective, clientProperty]);
  const attention = visibleProperties.filter((property) => ["critical", "high", "moderate"].includes(property.level)).slice(0, 5);
  const highRisk = data.properties.filter((property) => ["high", "critical"].includes(property.environmentalLevel ?? property.level)).length;
  const onlineMachines = data.machines.filter((machine) => machine.connection === "online").length;
  const visibleStates = data.states.filter((state) => state.propertiesMonitored > 0);
  const presentationMachines = data.machines.filter((m) => perspective === "sompo" || m.propertyId === (clientProperty || data.properties[0]?.id));
  const activeMachine = presentationMachines.find((m) => m.id === selectedMachine?.id && m.propertyId === selectedMachine?.propertyId) ?? presentationMachines[0] ?? null;

  async function refresh() {
    setRefreshing(true);
    setRefreshError("");
    try {
      const response = await fetch(data.requestMode === "portfolio" ? "/api/command-center?mode=portfolio-live" : "/api/command-center", { cache: "no-store" });
      if (!response.ok) throw new Error("Falha ao atualizar");
      const next = await response.json() as CommandCenterData;
      setData(next);
      setSelectedMachine((current) => next.machines.find((item) => item.id === current?.id && item.propertyId === current?.propertyId) ?? next.machines[0] ?? null);
    } catch { setRefreshError("Atualização indisponível; a última leitura foi preservada."); } finally { setRefreshing(false); }
  }

  async function useDemo() {
    setRefreshing(true);
    setRefreshError("");
    try {
      const response = await fetch("/api/command-center?mode=demo", { cache: "no-store" });
      if (!response.ok) throw new Error("Falha ao carregar cenário demonstrativo");
      setData(await response.json() as CommandCenterData);
    } catch { setRefreshError("Atualização indisponível; a última leitura foi preservada."); } finally { setRefreshing(false); }
  }

  return (
    <main className="min-h-screen bg-[#f3f5f7] text-slate-900">
      <header className="border-b border-slate-800 bg-[#07111f] text-white">
        <div className="mx-auto flex min-h-[72px] max-w-[1800px] items-center gap-5 px-5 lg:px-8">
          <div className="flex shrink-0 items-center gap-4 border-r border-white/15 pr-5">
            <div className="text-[26px] font-black tracking-[-0.08em] text-[#e31b23]">SOMPO</div>
            <div className="hidden sm:block"><p className="text-xs font-bold tracking-wide text-white">Rural Risk Intelligence</p><p className="text-[9px] uppercase tracking-[0.2em] text-slate-500">Command Center</p></div>
          </div>
          <div className="relative mx-auto hidden max-w-xl flex-1 md:block"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar propriedade, cidade ou coordenadas…" className="border-white/10 bg-white/[.07] pl-10 text-white placeholder:text-slate-500 focus:border-white/20 focus:ring-white/10" /></div>
          <div className="ml-auto flex shrink-0 items-center gap-3">
            <span className="hidden items-center gap-2 text-xs font-semibold text-emerald-300 sm:flex"><span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-50 motion-reduce:animate-none" /><span className="relative inline-flex size-2 rounded-full bg-emerald-400" /></span>Monitoramento ativo</span>
            <Button variant="ghost" size="icon" onClick={refresh} disabled={refreshing} className="text-slate-300 hover:bg-white/10 hover:text-white" aria-label="Atualizar dados"><RefreshCw className={cn("size-4", refreshing && "animate-spin")} /></Button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1800px] space-y-4 px-5 py-5 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-[10px] font-bold uppercase tracking-[0.2em] text-red-600">SOMPO Rural Risk Command Center</p><h1 className="mt-1 text-xl font-bold tracking-tight text-slate-950 lg:text-2xl">{perspective === "sompo" ? "SOMPO Control Center" : "Client Operations Center"}</h1></div>
          <div className="flex flex-wrap items-center justify-end gap-2"><Badge className={["live", "backend"].includes(data.source) ? "border-emerald-200 bg-emerald-50 text-emerald-700" : data.source === "unavailable" ? "border-amber-200 bg-amber-50 text-amber-700" : "border-violet-200 bg-violet-50 text-violet-700"}>{sourceLabel(data.source)}</Badge>{data.stale && <Badge className="border-amber-200 bg-amber-50 text-amber-700">Dados desatualizados</Badge>}{data.source === "unavailable" && <Button type="button" size="sm" variant="outline" onClick={useDemo} disabled={refreshing}>Usar cenário demonstrativo</Button>}{data.source === "demo" && <Button type="button" size="sm" variant="outline" onClick={refresh} disabled={refreshing}>Tentar dados reais</Button>}</div>
        </div>

        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex gap-2" aria-label="Perspectiva de demonstração">
            <Button variant={perspective === "sompo" ? "default" : "outline"} onClick={() => { setPerspective("sompo"); setSelectedProperty(null); }}>SOMPO</Button>
            <Button variant={perspective === "client" ? "default" : "outline"} onClick={() => { setPerspective("client"); setSelectedProperty(null); }}>Cliente</Button>
          </div>
          <p className="text-xs text-slate-500">Seleção de perspectiva para demonstração · não concede permissões de acesso.</p>
          {perspective === "client" && <select aria-label="Propriedade do cliente" className="max-w-full rounded-lg border p-2 text-sm" value={clientProperty || data.properties[0]?.id || ""} onChange={(e) => { setClientProperty(e.target.value); setSelectedProperty(null); }}>
            {data.properties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>}
          {perspective === "sompo" && <Button variant="outline" size="sm" onClick={async () => { setRefreshing(true); try { const r = await fetch("/api/command-center?mode=live"); if (!r.ok) throw new Error(); setData(await r.json()); } catch { setRefreshError("Showcase indisponível."); } finally { setRefreshing(false); } }} disabled={refreshing}>Showcase ambiental real</Button>}
        </div>
        {perspective === "sompo" && <Button variant="outline" size="sm" onClick={async () => { setRefreshing(true); try { const r = await fetch("/api/command-center?mode=portfolio"); setData(await r.json()); } catch { setRefreshError("Carteira indisponível."); } finally { setRefreshing(false); } }}>Carteira demonstrativa · dados reais</Button>}
        {refreshError && <p role="alert" className="text-sm text-amber-800">{refreshError}</p>}
        {data.requestMode === "portfolio" && <p className="text-xs text-slate-600">{data.presentationMode === "live" ? "Modo consulta às integrações · confira origem e horário de cada leitura" : "Modo última captura real · atualizar consulta as integrações"}</p>}
        {(data.requestMode === "portfolio" || perspective === "client") && <ExposureSummary properties={visibleProperties} client={perspective === "client"} onSelect={openProperty} />}
        {data.requestMode !== "portfolio" && <OperationsPanel key={`${data.source}:${data.generatedAt}:${perspective}:${clientProperty}`} data={data} perspective={perspective} onAlertUpdated={(alert) => { setData((current) => {
          const properties = current.properties.map((p) => p.id === alert.fazendaId && alert.status === "resolved" ? { ...p, alertCount: p.alertCount === null ? null : Math.max(0, p.alertCount - 1) } : p);
          return { ...current, properties, states: current.states.map((state) => ({ ...state, alertCount: properties.some((p) => p.uf === state.uf && p.alertCount === null) ? null : properties.filter((p) => p.uf === state.uf).reduce((total, p) => total + (p.alertCount ?? 0), 0) })), events: current.events.map((event) => event.id === alert.alertId ? { ...event, alertStatus: alert.status } : event) };
        }); setSelectedEvent((current) => current?.id === alert.alertId ? { ...current, alertStatus: alert.status } : current); }} propertyId={clientProperty || data.properties[0]?.id} />}
        {data.notices.length > 0 && <div className={cn("rounded-lg border px-4 py-3 text-xs", data.source === "unavailable" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-white text-slate-600")}><ul className="space-y-1">{data.notices.map((notice) => <li key={notice}>• {notice}</li>)}</ul></div>}

        <div className="relative md:hidden"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar propriedade, cidade ou coordenadas…" className="pl-10" /></div>

        {perspective === "sompo" && data.source !== "live" && <section aria-label="Indicadores principais" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <Kpi icon={Building2} label="Propriedades monitoradas" value={data.source === "unavailable" ? "—" : data.properties.length} detail="no recorte carregado" />
          <Kpi icon={AlertTriangle} label="Em risco alto/crítico" value={data.source === "unavailable" ? "—" : highRisk} detail="exigem atenção" accent />
          <Kpi icon={BellRing} label="Sem avaliação ambiental" value={data.source === "unavailable" ? "—" : data.properties.filter((p) => (p.environmentalLevel ?? p.level) === "unknown").length} detail="no recorte carregado" />
          <Kpi icon={Wifi} label="Máquinas monitoradas" value={data.source === "unavailable" || data.machineInventoryAvailable === false ? "—" : data.machines.length} detail={data.machineInventoryAvailable === false ? "inventário incompleto" : `${onlineMachines} conectadas no recorte`} />
        </section>}

        {perspective === "sompo" && visibleStates.length > 0 && <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3"><div><h2 className="text-xs font-bold uppercase tracking-[0.15em] text-slate-600">Carteira por estado · exposição ambiental</h2><p className="mt-0.5 text-[10px] text-slate-400">Agregações somente das propriedades disponíveis neste recorte · não representa o risco do estado inteiro</p></div><Gauge className="size-5 text-slate-300" /></div>
          <div>{visibleStates.map((state) => <StateStrip key={state.uf} state={state} onSelect={() => { geographicReturnFocus.current = document.activeElement as HTMLElement; setSelectedState(state); }} />)}</div>
        </Card>}

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(350px,.75fr)]">
          <RiskMap perspective={perspective} machines={presentationMachines} properties={visibleProperties} hotspots={data.hotspots.filter((h) => perspective === "sompo" || h.propertyId === (clientProperty || data.properties[0]?.id))} selectedId={selectedProperty?.id} onSelect={openProperty} />
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3"><div><h2 className="text-xs font-bold uppercase tracking-[0.15em] text-slate-700">Exposições das propriedades</h2><p className="mt-0.5 text-[10px] text-slate-400">Severidade e evidências da avaliação registrada</p></div><Badge>{attention.length}</Badge></div>
            <div className="divide-y divide-slate-100">{attention.length ? attention.map((property) => <PropertyRow key={property.id} property={property} onSelect={() => openProperty(property)} />) : <div className="grid min-h-48 place-items-center p-6 text-center"><div><CheckCircle2 className="mx-auto size-8 text-emerald-500" /><p className="mt-2 text-sm font-semibold text-slate-700">Nenhuma situação sinalizada no recorte disponível</p></div></div>}</div>
          </Card>
        </section>

        <section className="grid gap-4 2xl:grid-cols-[minmax(0,1.45fr)_minmax(390px,.55fr)]">
          {activeMachine ? <MachinePanel machine={activeMachine} machines={presentationMachines} onChange={setSelectedMachine} /> : data.requestMode !== "portfolio" ? <Card className="grid min-h-64 place-items-center"><div className="text-center"><Cpu className="mx-auto size-8 text-slate-300" /><p className="mt-2 text-sm font-semibold text-slate-600">Aguardando dispositivo embarcado</p><p className="mt-1 text-xs text-slate-400">Nenhum ESP32 físico vinculado.</p></div></Card> : null}
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4"><div className="flex items-center gap-2"><span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-red-500 opacity-50 motion-reduce:animate-none" /><span className="relative inline-flex size-2 rounded-full bg-red-500" /></span><h2 className="text-xs font-black uppercase tracking-[0.16em] text-slate-800">Sompo Live</h2></div><span className="text-[10px] text-slate-400">Eventos recentes</span></div>
            <div className="divide-y divide-slate-100">{data.events.length === 0 && <p className="p-5 text-xs text-slate-500">Eventos / avisos não disponíveis no recorte atual.</p>}{data.events.filter((e) => perspective === "sompo" || e.propertyId === (clientProperty || data.properties[0]?.id)).slice(0, 6).map((event) => { const Icon = eventIcon[event.kind]; return <button key={event.id} type="button" onClick={(click) => { geographicReturnFocus.current = click.currentTarget; setSelectedEvent(event); }} aria-label={`Abrir ${event.category === "alert" ? "alerta" : "evento"}: ${event.title}`} className="flex w-full gap-3 px-5 py-3 text-left hover:bg-slate-50"><div className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-full", event.severity === "critical" ? "bg-red-50 text-red-600" : event.severity === "high" ? "bg-orange-50 text-orange-600" : "bg-slate-100 text-slate-600")}><Icon className="size-4" /></div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><Badge className={cn("px-1.5 py-0.5 text-[8px]", event.category === "alert" ? "border-red-200 bg-red-50 text-red-700" : "border-sky-200 bg-sky-50 text-sky-700")}>{event.category === "alert" ? event.alertStatus === "resolved" ? "Resolvido" : event.alertStatus === "acknowledged" ? "Reconhecido" : "Alerta" : "Evento"}</Badge><strong className="truncate text-xs text-slate-800">{event.title}</strong>{event.demo && <Badge className="border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[8px] text-violet-700">Demo</Badge>}</div><p className="mt-1 truncate text-[10px] text-slate-500">{event.propertyName ? `${event.propertyName}${event.city && event.uf ? ` · ${event.city}/${event.uf}` : ""}` : event.location ?? event.description}</p></div><time className="shrink-0 text-[9px] text-slate-400">{event.timeLabel}</time></button>; })}</div>
          </Card>
        </section>

        <section className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          <Card className="p-5"><div className="flex items-center justify-between"><div><h2 className="text-xs font-bold uppercase tracking-[0.15em] text-slate-700">Focos recentes</h2><p className="mt-1 text-[10px] text-slate-400">Somente localidades presentes nos dados recebidos</p></div><Satellite className="size-5 text-slate-300" /></div><div className="mt-4 grid gap-2 sm:grid-cols-3">{data.hotspots.filter((h) => perspective === "sompo" || h.propertyId === (clientProperty || data.properties[0]?.id)).slice(0, 3).map((hotspot) => <button type="button" key={hotspot.id} onClick={() => setSelectedHotspot(hotspot)} aria-label={`Abrir foco ${hotspot.id}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-left hover:border-orange-200 hover:bg-orange-50/50"><div className="flex items-center justify-between"><Flame className="size-4 text-orange-500" />{hotspot.demo && <Badge className="border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[8px] text-violet-700">Demo</Badge>}</div><strong className="mt-2 block text-xs text-slate-800">{hotspot.city && hotspot.uf ? `${hotspot.city} · ${hotspot.uf}` : `${hotspot.latitude.toFixed(3)}, ${hotspot.longitude.toFixed(3)}`}</strong><p className="mt-1 text-[10px] text-slate-400">Detectado {hotspot.detectedLabel}</p>{hotspot.distanceKm !== undefined && <p className="mt-1 text-[10px] font-semibold text-orange-700">{hotspot.distanceKm.toLocaleString("pt-BR")} km da propriedade</p>}</button>)}</div></Card>
          <Card className="flex items-center gap-4 p-5"><div className="grid size-12 shrink-0 place-items-center rounded-xl bg-slate-950 text-white"><ShieldCheck className="size-6" /></div><div><h2 className="text-sm font-bold text-slate-900">Leitura responsável do risco</h2><p className="mt-1 text-xs leading-relaxed text-slate-500">Scores e níveis são índices operacionais baseados na cobertura disponível. Não representam probabilidade de acidente ou incêndio.</p></div></Card>
        </section>
      </div>
      <PropertyDrawer returnFocus={geographicReturnFocus} property={selectedProperty} onClose={() => setSelectedProperty(null)} />
      <StateDrawer returnFocus={geographicReturnFocus} state={selectedState} properties={data.properties} onClose={() => setSelectedState(null)} onProperty={(property) => { setSelectedState(null); setSelectedProperty(property); }} />
      <HotspotDrawer hotspot={selectedHotspot} hotspots={data.hotspots} properties={data.properties} onClose={() => setSelectedHotspot(null)} onSelect={setSelectedHotspot} />
      <EventDrawer event={selectedEvent} property={selectedEvent?.propertyId ? data.properties.find((item) => item.id === selectedEvent.propertyId) ?? null : null} onClose={() => setSelectedEvent(null)} onProperty={(property) => { setSelectedEvent(null); setSelectedProperty(property); }} />
      <RiskAssistant available={data.source !== "demo" && data.source !== "unavailable"} portfolioSnapshot={data.requestMode === "portfolio" ? data.generatedAt : undefined} key={`${perspective}:${clientProperty}:${data.source}:${data.requestMode}:${data.generatedAt}`} initialPropertyId={perspective === "client" && (data.source === "backend" || data.requestMode === "portfolio") ? clientProperty || data.properties[0]?.id : undefined} />
    </main>
  );
}
