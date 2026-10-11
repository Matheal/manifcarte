// Types et fonctions partagés entre les pages (build) et les scripts du navigateur.

export interface Source {
  title: string;
  url: string;
  outlet: string;
  kind: "presse" | "social" | "manuel";
  published: string;
}

export interface ManifEvent {
  id: string;
  scope: "fr" | "world";
  kind: string;
  title: string;
  headline: string;
  /** Résumé neutre rédigé par l'IA (absent si aucun article n'a été analysé). */
  summary?: string | null;
  /** Selon l'IA : "annoncee" (à venir) ou "attestee" (a eu lieu / en cours). */
  nature?: "annoncee" | "attestee" | null;
  ai_count?: number;
  /** Ajoutée ou confirmée manuellement par l'équipe. */
  verified?: boolean;
  city: string;
  insee?: string;
  dep?: string;
  country: string;
  lat: number;
  lon: number;
  geo_precision: "lieu" | "commune";
  place: string | null;
  date: string; // AAAA-MM-JJ, heure de Paris
  date_precision: "explicite" | "relative" | "ia" | "publication";
  time: string | null;
  causes: string[];
  cause_labels: string[];
  signals: string[];
  participants: number | null;
  reliability: { level: 1 | 2 | 3; label: string; score: number };
  source_count: number;
  sources: Source[];
}

export interface SourceStatus {
  ok: boolean;
  at: string;
  last_ok?: string | null;
  fetched?: number;
  added?: number;
  error?: string;
  // Analyse IA
  disabled?: boolean;
  analyzed?: number;
  pending?: number;
  quota?: boolean;
  model?: string | null;
}

export type RestrictionType = "transport" | "circulation" | "etablissement" | "arrete" | "commerce" | "autre";

export interface Restriction {
  id: string;
  type: RestrictionType;
  type_label: string;
  city: string;
  lat: number;
  lon: number;
  geo_precision: "lieu" | "commune";
  place: string | null;
  start: string;
  end: string;
  description: string;
  details: string[];
  lines: string[];
  origin: "ia" | "manuel";
  verified: boolean;
  sources: Source[];
}

export interface Dataset {
  generated_at: string;
  focus: { name: string; insee: string; lat: number; lon: number; zoom: number };
  sources: Record<string, SourceStatus>;
  count: { fr: number; world: number };
  events: ManifEvent[];
  restrictions?: Restriction[];
  moderation?: { pending: number; manual_events: number; manual_restrictions: number; removed: number };
}

export type Status = "today" | "upcoming" | "past";

export const STATUS_LABEL: Record<Status, string> = {
  today: "Aujourd'hui",
  upcoming: "À venir",
  past: "Passée",
};

export const CAUSES: Record<string, string> = {
  education: "Éducation & lycéens",
  retraites: "Retraites",
  travail: "Travail & syndicats",
  climat: "Climat & environnement",
  international: "International & paix",
  droits: "Droits & égalité",
  police: "Police & justice",
  agriculture: "Agriculture",
  sante: "Santé & hôpital",
  services: "Services publics & pouvoir d'achat",
  politique: "Politique & institutions",
  autre: "Autre",
};

export const SIGNAL_LABEL: Record<string, string> = {
  annonce: "Appel / annonce",
  blocus: "Blocus",
  tensions: "Tensions signalées",
  interdite: "Interdiction évoquée",
  annulee: "Annulée ou reportée",
  non_verifie: "Non vérifiée",
  dementi: "Démentie",
  verifie: "Vérifiée par l'équipe",
};

/** Signaux affichés en orange (prudence). */
export const WARN_SIGNALS = new Set(["tensions", "interdite", "non_verifie", "dementi", "annulee"]);

export const SOURCE_LABEL: Record<string, string> = {
  google_news: "Google News",
  rss: "Flux RSS de presse",
  mastodon: "Mastodon",
  gdelt: "GDELT (monde)",
  ai: "Analyse IA (Gemini)",
  moderation: "Contributions (GitHub)",
};

/** Date du jour à Paris, au format AAAA-MM-JJ (indépendant du fuseau du visiteur). */
export function todayParis(now = new Date()): string {
  return new Intl.DateTimeFormat("fr-CA", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function statusOf(e: Pick<ManifEvent, "date">, today = todayParis()): Status {
  if (e.date === today) return "today";
  return e.date > today ? "upcoming" : "past";
}

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b + "T12:00:00Z") - Date.parse(a + "T12:00:00Z")) / 86_400_000);
}

export function addDays(day: string, n: number): string {
  const d = new Date(day + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

const dayFmt = new Intl.DateTimeFormat("fr-FR", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});
const shortFmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });

export function formatDay(day: string): string {
  return dayFmt.format(new Date(day + "T12:00:00Z"));
}

export function formatShort(day: string): string {
  return shortFmt.format(new Date(day + "T12:00:00Z"));
}

/** « aujourd'hui », « demain », « hier », sinon la date en toutes lettres. */
export function relativeDay(day: string, today = todayParis()): string {
  const diff = daysBetween(today, day);
  if (diff === 0) return "aujourd'hui";
  if (diff === 1) return "demain";
  if (diff === -1) return "hier";
  if (diff > 1 && diff < 7) return `dans ${diff} jours`;
  if (diff < -1 && diff > -7) return `il y a ${-diff} jours`;
  return formatDay(day);
}

export function formatTime(t: string | null): string {
  return t ? t.replace(":", " h ").replace(" h 00", " h") : "";
}

export function formatAgo(iso: string, now = Date.now()): string {
  const min = Math.round((now - Date.parse(iso)) / 60_000);
  if (min < 1) return "à l'instant";
  if (min < 60) return `il y a ${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `il y a ${h} h`;
  return `il y a ${Math.round(h / 24)} jours`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("fr-FR").format(n);
}

let countryNames: Map<string, string> | null = null;

/** Nom de pays anglais (GDELT) -> français, via les tables Intl du navigateur. */
export function countryFr(name: string): string {
  if (!countryNames) {
    countryNames = new Map();
    try {
      const en = new Intl.DisplayNames(["en"], { type: "region" });
      const fr = new Intl.DisplayNames(["fr"], { type: "region" });
      const A = 65;
      for (let i = 0; i < 26; i++) {
        for (let j = 0; j < 26; j++) {
          const code = String.fromCharCode(A + i, A + j);
          const e = en.of(code);
          if (e && e !== code) countryNames.set(e, fr.of(code) ?? e);
        }
      }
      countryNames.set("Czech Republic", "Tchéquie");
      countryNames.set("Burma", "Birmanie");
      countryNames.set("Ivory Coast", "Côte d'Ivoire");
    } catch {
      /* Intl.DisplayNames indisponible : on garde l'anglais */
    }
  }
  return countryNames.get(name) ?? name;
}

export function placeLabel(e: ManifEvent): string {
  if (e.scope === "world") return `${e.city}, ${countryFr(e.country)}`;
  return e.place ? `${e.place}, ${e.city}` : e.city;
}

export function precisionNote(e: ManifEvent): string | null {
  if (e.date_precision === "publication") return "Date estimée d'après la parution des articles";
  if (e.date_precision === "relative") return "Date déduite d'une formulation comme « ce jeudi » ou « demain »";
  if (e.date_precision === "ia") return "Date déterminée par l'IA à partir des articles";
  return null;
}

/** Préfixe une URL interne avec le chemin de base du site (GitHub Pages). */
export function withBase(base: string, path = ""): string {
  const b = base.endsWith("/") ? base : base + "/";
  return b + path.replace(/^\//, "");
}

export function eventPath(base: string, id: string): string {
  return withBase(base, `manif/${id}/`);
}

/** Supprime les accents (recherche insensible aux accents). */
export function strip(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** Tri d'affichage : aujourd'hui, puis à venir (proche d'abord), puis passées (récentes d'abord). */
export function compareEvents(a: ManifEvent, b: ManifEvent, today = todayParis()): number {
  const rank = (e: ManifEvent) => ({ today: 0, upcoming: 1, past: 2 })[statusOf(e, today)];
  const ra = rank(a), rb = rank(b);
  if (ra !== rb) return ra - rb;
  if (a.date !== b.date) return ra === 1 ? (a.date < b.date ? -1 : 1) : a.date < b.date ? 1 : -1;
  if (a.scope !== b.scope) return a.scope === "fr" ? -1 : 1;
  return b.reliability.score - a.reliability.score;
}

/** Fichier .ics (agenda) pour un événement. */
export function toIcs(e: ManifEvent, pageUrl: string): string {
  const d = e.date.replace(/-/g, "");
  const esc = (s: string) => s.replace(/[\\;,]/g, (c) => "\\" + c).replace(/\n/g, "\\n");
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//ManifCarte//FR",
    "BEGIN:VEVENT",
    `UID:${e.id}@manifcarte`,
    `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").slice(0, 15)}Z`,
  ];
  if (e.time) {
    const [h, m] = e.time.split(":");
    lines.push(`DTSTART;TZID=Europe/Paris:${d}T${h}${m}00`);
    lines.push(`DURATION:PT2H`);
  } else {
    lines.push(`DTSTART;VALUE=DATE:${d}`);
  }
  lines.push(
    `SUMMARY:${esc(e.title)}`,
    `LOCATION:${esc(placeLabel(e))}`,
    `GEO:${e.lat};${e.lon}`,
    `DESCRIPTION:${esc(e.headline + "\n" + pageUrl)}`,
    `URL:${pageUrl}`,
    "END:VEVENT",
    "END:VCALENDAR",
  );
  return lines.join("\r\n");
}

// --- Restrictions --------------------------------------------------------------------

export const RESTRICTION_LABEL: Record<RestrictionType, string> = {
  transport: "Transports perturbés",
  circulation: "Circulation restreinte",
  etablissement: "Établissement fermé",
  arrete: "Arrêté / interdiction",
  commerce: "Commerces fermés",
  autre: "Autre perturbation",
};

export type RestrictionStatus = "active" | "upcoming" | "past";

export const RESTRICTION_STATUS_LABEL: Record<RestrictionStatus, string> = {
  active: "En cours",
  upcoming: "À venir",
  past: "Terminée",
};

export function restrictionStatus(r: Restriction, today = todayParis()): RestrictionStatus {
  if (r.end < today) return "past";
  return r.start > today ? "upcoming" : "active";
}

/** « le 13 oct. » ou « du 13 au 16 oct. ». */
export function formatRange(start: string, end: string): string {
  if (start === end) return `le ${formatShort(start)}`;
  const [s, e] = [formatShort(start), formatShort(end)];
  const sameMonth = start.slice(0, 7) === end.slice(0, 7);
  return `du ${sameMonth ? s.split(" ")[0] : s} au ${e}`;
}

/** Restrictions de la même ville qui touchent la date d'une mobilisation (± 1 jour). */
export function restrictionsFor(e: ManifEvent, all: Restriction[] = []): Restriction[] {
  const from = addDays(e.date, -1);
  const to = addDays(e.date, 1);
  return all.filter((r) => r.city === e.city && r.start <= to && r.end >= from);
}

// --- Contributions (formulaires GitHub) ------------------------------------------------

export const REPO_URL: string =
  (import.meta.env.PUBLIC_REPO_URL as string | undefined) || "https://github.com/Matheal/manifcarte";

export type IssueTemplate = "1-ajouter-manif.yml" | "2-signaler-restriction.yml" | "3-supprimer.yml";

/** Lien vers un formulaire GitHub pré-rempli (les clés sont les « id » des champs). */
export function issueUrl(template: IssueTemplate, fields: Record<string, string> = {}): string {
  const p = new URLSearchParams({ template, ...fields });
  return `${REPO_URL}/issues/new?${p.toString()}`;
}

/** Date AAAA-MM-JJ -> JJ/MM/AAAA (format des formulaires). */
export function frDate(day: string): string {
  const [y, m, d] = day.split("-");
  return `${d}/${m}/${y}`;
}

/** Lien de dons (Ko-fi, Liberapay…), défini par la variable GitHub DONATE_URL. Vide = pas de dons. */
export const DONATE_URL: string = (import.meta.env.PUBLIC_DONATE_URL as string | undefined)?.trim() || "";
