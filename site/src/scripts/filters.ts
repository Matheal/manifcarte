// Chargement des données et filtres partagés par la carte et la liste (navigateur).
import {
  type Dataset,
  type ManifEvent,
  addDays,
  compareEvents,
  countryFr,
  statusOf,
  strip,
  todayParis,
  withBase,
} from "../lib/shared";

export type Period = "upcoming" | "7d" | "30d" | "all";
export type Scope = "all" | "fr" | "world";

export interface Filters {
  period: Period;
  scope: Scope;
  causes: Set<string>;
  minLevel: 1 | 2 | 3;
  q: string;
}

// Par défaut, seules les mobilisations du jour et à venir sont affichées :
// les passées restent accessibles avec les autres périodes.
export const DEFAULT_PERIOD: Period = "upcoming";

export const PERIOD_LABEL: Record<Period, string> = {
  upcoming: "Aujourd'hui et à venir",
  "7d": "+ 7 jours passés",
  "30d": "+ 30 jours passés",
  all: "Tout l'historique",
};

export const SCOPE_LABEL: Record<Scope, string> = {
  all: "France + monde",
  fr: "France",
  world: "Monde",
};

export async function loadData(): Promise<Dataset> {
  const res = await fetch(withBase(import.meta.env.BASE_URL, "data/events.json"), { cache: "no-cache" });
  if (!res.ok) throw new Error(`Données indisponibles (${res.status})`);
  return res.json();
}

export function readFilters(defaults: Partial<Filters> = {}): Filters {
  const p = new URLSearchParams(location.search);
  const period = (p.get("periode") as Period) || defaults.period || DEFAULT_PERIOD;
  const scope = (p.get("zone") as Scope) || defaults.scope || "all";
  const level = Number(p.get("fiabilite") || defaults.minLevel || 1);
  return {
    period: period in PERIOD_LABEL ? period : DEFAULT_PERIOD,
    scope: scope in SCOPE_LABEL ? scope : "all",
    causes: new Set((p.get("cause") || "").split(",").filter(Boolean)),
    minLevel: (level >= 1 && level <= 3 ? level : 1) as 1 | 2 | 3,
    q: p.get("q") || "",
  };
}

export function writeFilters(f: Filters, defaults: Partial<Filters> = {}): void {
  const p = new URLSearchParams();
  if (f.period !== (defaults.period ?? DEFAULT_PERIOD)) p.set("periode", f.period);
  if (f.scope !== (defaults.scope ?? "all")) p.set("zone", f.scope);
  if (f.causes.size) p.set("cause", [...f.causes].join(","));
  if (f.minLevel > 1) p.set("fiabilite", String(f.minLevel));
  if (f.q) p.set("q", f.q);
  const qs = p.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

export function applyFilters(events: ManifEvent[], f: Filters, today = todayParis()): ManifEvent[] {
  const from = f.period === "7d" ? addDays(today, -7) : f.period === "30d" ? addDays(today, -30) : null;
  const q = strip(f.q.trim().toLowerCase());
  return events
    .filter((e) => {
      if (f.scope !== "all" && e.scope !== f.scope) return false;
      if (f.period === "upcoming" && statusOf(e, today) === "past") return false;
      if (from && e.date < from) return false;
      if (f.causes.size && !e.causes.some((c) => f.causes.has(c))) return false;
      if (e.reliability.level < f.minLevel) return false;
      if (q) {
        const hay = strip(`${e.title} ${e.city} ${e.place ?? ""} ${e.country} ${countryFr(e.country)} ${e.headline}`.toLowerCase());
        if (!hay.includes(q)) return false;
      }
      return true;
    })
    .sort((a, b) => compareEvents(a, b, today));
}

/** Nombre de mobilisations passées (30 derniers jours) masquées par la période actuelle. */
export function hiddenPastCount(events: ManifEvent[], f: Filters, today = todayParis()): number {
  if (f.period !== "upcoming") return 0;
  const from = addDays(today, -30);
  return applyFilters(events, { ...f, period: "30d" }, today).filter((e) => e.date < today && e.date >= from)
    .length;
}
