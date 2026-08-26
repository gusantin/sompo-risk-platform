import { Crosshair, Flame, Tractor } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { HotspotView, PropertyView, RiskLevel } from "@/lib/types";

const markerColor: Record<RiskLevel, string> = {
  low: "bg-emerald-400", moderate: "bg-amber-400", high: "bg-orange-500", critical: "bg-red-500", unknown: "bg-slate-400",
};

function position(latitude: number, longitude: number) {
  const left = Math.max(5, Math.min(95, ((longitude + 74) / 40) * 100));
  const top = Math.max(6, Math.min(94, ((6 - latitude) / 40) * 100));
  return { left: `${left}%`, top: `${top}%` };
}

export function RiskMap({ properties, hotspots, selectedId, onSelect }: {
  properties: PropertyView[];
  hotspots: HotspotView[];
  selectedId?: string;
  onSelect: (property: PropertyView) => void;
}) {
  return (
    <div className="relative h-[348px] overflow-hidden rounded-xl bg-[#081827] text-white xl:h-[388px]">
      <div className="absolute inset-0 map-grid opacity-40" />
      <svg aria-hidden="true" viewBox="0 0 500 420" className="absolute left-[12%] top-[-3%] h-[112%] w-[72%] opacity-20">
        <path d="M164 20 240 31 278 54 330 58 367 95 401 109 420 150 399 194 413 226 382 265 358 281 341 327 310 342 284 388 250 408 222 370 205 341 177 315 151 280 109 252 96 210 66 176 87 141 111 119 112 78 144 60Z" fill="#4f7891" stroke="#9ec3d5" strokeWidth="2" />
        <path d="M120 143 379 278M105 207 341 327M164 64 205 341M278 54 177 315M367 95 151 280" stroke="#a8ccda" strokeWidth="1" opacity=".45" />
      </svg>

      <div className="absolute left-5 top-5 z-10">
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-cyan-200/80"><Crosshair className="size-4" /> Visão geoespacial · piloto</div>
        <p className="mt-1 text-xs text-slate-400">Coordenadas das propriedades e focos disponíveis</p>
      </div>
      <Badge className="absolute right-5 top-5 z-10 border-white/10 bg-white/10 text-slate-200">MT · MS · GO · MG · PR</Badge>

      {hotspots.slice(0, 12).map((hotspot) => (
        <div key={hotspot.id} className="group absolute z-20 -translate-x-1/2 -translate-y-1/2" style={position(hotspot.latitude, hotspot.longitude)}>
          <span className="absolute -inset-2 animate-ping rounded-full bg-orange-500/25 motion-reduce:animate-none" />
          <span className="relative grid size-6 place-items-center rounded-full border border-orange-300/50 bg-orange-500 text-white shadow-lg">
            <Flame className="size-3.5" />
          </span>
          <span className="pointer-events-none absolute left-1/2 top-8 z-40 hidden w-max -translate-x-1/2 rounded-md bg-white px-2 py-1 text-[10px] font-semibold text-slate-800 shadow-xl group-hover:block">
            Hotspot {hotspot.demo ? "· DEMO" : ""} · {hotspot.detectedLabel}
          </span>
        </div>
      ))}

      {properties.map((property) => (
        <button key={property.id} type="button" onClick={() => onSelect(property)}
          className="group absolute z-30 -translate-x-1/2 -translate-y-1/2 text-left outline-none"
          style={position(property.latitude, property.longitude)} aria-label={`Abrir ${property.name}`}>
          <span className={cn("absolute -inset-2 rounded-full opacity-20", markerColor[property.level], selectedId === property.id && "animate-ping motion-reduce:animate-none")} />
          <span className={cn("relative grid size-7 place-items-center rounded-full border-2 border-white shadow-[0_0_0_3px_rgba(255,255,255,.12)]", markerColor[property.level])}>
            <Tractor className="size-3.5 text-white" />
          </span>
          <span className="absolute left-1/2 top-9 z-40 hidden w-max -translate-x-1/2 rounded-md border border-white/10 bg-slate-950/95 px-2.5 py-1.5 text-[10px] shadow-xl group-hover:block group-focus:block">
            <strong className="block text-white">{property.name}</strong>
            <span className="text-slate-400">{property.city} · {property.uf}{property.propertyDemo && property.environmentalDataOrigin === "real" ? " · propriedade demo / ambiente real" : property.demo ? " · DEMO" : ""}</span>
          </span>
        </button>
      ))}

      <div className="absolute bottom-4 left-5 right-5 z-10 flex flex-wrap items-center gap-4 rounded-lg border border-white/10 bg-slate-950/55 px-3 py-2 text-[10px] font-semibold text-slate-300 backdrop-blur-sm">
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-red-500" /> Crítico</span>
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-orange-500" /> Alto</span>
        <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-amber-400" /> Moderado</span>
        <span className="flex items-center gap-1.5"><Flame className="size-3 text-orange-400" /> Hotspot</span>
        <span className="ml-auto text-slate-500">Visualização indicativa · não representa probabilidade</span>
      </div>
    </div>
  );
}
