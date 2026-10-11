// Génération HTML des cartes d'événements (utilisée au build ET dans le navigateur).
import { restrictionIconSvg } from "./icons";
import {
  type ManifEvent,
  type Restriction,
  RESTRICTION_STATUS_LABEL,
  formatRange,
  issueUrl,
  restrictionStatus,
  withBase,
  SIGNAL_LABEL,
  STATUS_LABEL,
  escapeHtml,
  eventPath,
  formatTime,
  placeLabel,
  relativeDay,
  statusOf,
  todayParis,
} from "./shared";

const PIN =
  '<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true" style="vertical-align:-2px;margin-right:3px"><path fill="currentColor" d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5Z"/></svg>';

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

export function reliabilityHtml(e: ManifEvent): string {
  return `<span class="reliability" data-level="${e.reliability.level}" title="Fiabilité : ${escapeHtml(
    e.reliability.label,
  )}"><span class="bars"><i></i><i></i><i></i></span>${escapeHtml(e.reliability.label)}</span>`;
}

export function statusBadge(e: ManifEvent, today = todayParis()): string {
  const s = statusOf(e, today);
  return `<span class="badge ${s}"><span class="dot"></span>${STATUS_LABEL[s]}</span>`;
}

export function eventCardHtml(e: ManifEvent, base: string, today = todayParis()): string {
  const [, m, d] = e.date.split("-");
  const status = statusOf(e, today);
  const when = [status === "today" ? "" : relativeDay(e.date, today), formatTime(e.time)].filter(Boolean).join(" · ");
  const extra: string[] = [];
  if (e.verified) extra.push(`<span class="badge verified">✓ Vérifiée</span>`);
  if (e.scope === "world") extra.push(`<span class="badge world">Monde</span>`);
  for (const sig of ["dementi", "non_verifie", "annulee"]) {
    if (e.signals.includes(sig)) extra.push(`<span class="badge warn">${SIGNAL_LABEL[sig]}</span>`);
  }
  if (e.signals.includes("tensions")) extra.push(`<span class="badge warn">Tensions signalées</span>`);
  if (e.signals.includes("blocus") && e.kind !== "Blocus") extra.push(`<span class="badge">Blocus</span>`);
  return `<a class="event-card" href="${eventPath(base, e.id)}" data-status="${status}" data-id="${e.id}">
  <div class="date-tile" aria-hidden="true"><b>${Number(d)}</b><span>${MONTHS[Number(m) - 1]}</span></div>
  <div>
    <h3>${escapeHtml(e.title)}</h3>
    <div class="meta">${statusBadge(e, today)}<span>${escapeHtml(when)}</span>${extra.join("")}</div>
    <div class="meta" style="margin-top:4px"><span class="place">${PIN}${escapeHtml(placeLabel(e))}</span>${reliabilityHtml(e)}</div>
    <p class="headline">${escapeHtml(e.summary || e.headline)}</p>
  </div>
</a>`;
}

/** Carte d'une restriction (page Perturbations, fiches, panneau de la carte). */
export function restrictionCardHtml(
  r: Restriction,
  base: string,
  today = todayParis(),
  opts: { compact?: boolean; siteUrl?: string } = {},
): string {
  const status = restrictionStatus(r, today);
  const lines = r.lines.length
    ? `<div class="lines">${r.lines.map((l) => `<span class="line">${escapeHtml(l)}</span>`).join("")}</div>`
    : "";
  const origin = r.verified
    ? `<span class="badge verified">✓ Vérifiée</span>`
    : `<span class="badge">Détectée par IA</span>`;
  const where = r.place ? `${r.place}, ${r.city}` : r.city;
  const head = `<div class="r-icon r-${status}">${restrictionIconSvg(r.type, 20)}</div>
    <div class="r-body">
      <div class="r-title"><b>${escapeHtml(r.type_label)}</b> · ${escapeHtml(where)}</div>
      <div class="meta"><span class="badge r-${status}">${RESTRICTION_STATUS_LABEL[status]}</span><span>${escapeHtml(formatRange(r.start, r.end))}</span>${opts.compact ? "" : origin}</div>
      <p class="r-desc">${escapeHtml(r.description)}</p>${lines}`;
  if (opts.compact) {
    return `<a class="restriction-card compact" href="${withBase(base, "perturbations/")}#${r.id}" data-rid="${r.id}">${head}</div></a>`;
  }
  const details = r.details.length
    ? `<ul class="r-details">${r.details.map((d) => `<li>${escapeHtml(d)}</li>`).join("")}</ul>`
    : "";
  const sources = r.sources
    .map((src) =>
      src.url
        ? `<a href="${escapeHtml(src.url)}" target="_blank" rel="noopener nofollow">${escapeHtml(src.outlet)}</a>`
        : `<span>${escapeHtml(src.outlet)}</span>`,
    )
    .join(" · ");
  const page = `${opts.siteUrl ?? ""}${withBase(base, "perturbations/")}#${r.id}`;
  return `<article class="restriction-card" id="${r.id}" data-status="${status}">${head}${details}
      <p class="r-sources small muted">Sources : ${sources}</p>
      <div class="r-actions small">
        <a href="${withBase(base)}?r=${encodeURIComponent(r.id)}">Voir sur la carte</a>
        <a href="${escapeHtml(issueUrl("3-supprimer.yml", { lien: page, title: `[Erreur] ${r.type_label} à ${r.city}` }))}" target="_blank" rel="noopener">Signaler une erreur</a>
      </div>
    </div></article>`;
}
