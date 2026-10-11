// Carte interactive (page d'accueil).
import type { GeoJSONSource, MapGeoJSONFeature, Popup } from "maplibre-gl";
import { RESTRICTION_ICON } from "../lib/icons";
import { eventCardHtml, reliabilityHtml, restrictionCardHtml, statusBadge } from "../lib/render";
import {
  type Dataset,
  type ManifEvent,
  type Restriction,
  type RestrictionType,
  RESTRICTION_STATUS_LABEL,
  addDays,
  escapeHtml,
  formatRange,
  issueUrl,
  restrictionStatus,
  strip,
  withBase,
  eventPath,
  formatAgo,
  formatTime,
  placeLabel,
  relativeDay,
  statusOf,
  todayParis,
} from "../lib/shared";
import { type Filters, applyFilters, hiddenPastCount, loadData, readFilters, writeFilters } from "./filters";
import { MAP_STYLES as STYLES, isDark, loadMapLibre } from "./maplib";

const maplibregl = await loadMapLibre();

const BASE = import.meta.env.BASE_URL;
const root = document.querySelector<HTMLElement>(".map-app")!;
const focus = JSON.parse(root.dataset.focus!) as Dataset["focus"];
const listEl = document.getElementById("list")!;
const summaryEl = document.getElementById("summary")!;
const listTitleEl = document.getElementById("list-title")!;
const updatedEl = document.getElementById("updated")!;
const errorEl = document.getElementById("map-error")!;
const panel = document.querySelector<HTMLElement>(".panel")!;
const handle = document.querySelector<HTMLButtonElement>(".sheet-handle")!;

const VIEWS = {
  focus: { center: [focus.lon, focus.lat] as [number, number], zoom: focus.zoom },
  france: { center: [2.4, 46.6] as [number, number], zoom: 4.8 },
  world: { center: [10, 25] as [number, number], zoom: 1.4 },
};

function css(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

let all: ManifEvent[] = [];
let visible: ManifEvent[] = [];
let filters: Filters = readFilters();
let byId = new Map<string, ManifEvent>();
let popup: Popup | null = null;
let today = todayParis();
let allRestrictions: Restriction[] = [];
let visibleRestrictions: Restriction[] = [];
let restrictionsById = new Map<string, Restriction>();
let showRestrictions = true;

// Liens directs : ?manif=<id> ou ?r=<id> (lus avant que les filtres ne réécrivent l'URL).
const initialParams = new URLSearchParams(location.search);
const targetEvent = initialParams.get("manif");
const targetRestriction = initialParams.get("r");

const map = new maplibregl.Map({
  container: "map",
  style: isDark() ? STYLES.dark : STYLES.light,
  center: VIEWS.focus.center,
  zoom: VIEWS.focus.zoom,
  attributionControl: { compact: true },
  maxZoom: 17,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(
  new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: false }, trackUserLocation: false }),
  "top-right",
);
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

// --- Données -> GeoJSON ----------------------------------------------------------

/** Écarte légèrement les points superposés (même ville, jours différents). */
function spread(events: ManifEvent[]): Map<string, [number, number]> {
  const groups = new Map<string, ManifEvent[]>();
  for (const e of events) {
    const k = `${e.lat.toFixed(4)},${e.lon.toFixed(4)}`;
    (groups.get(k) ?? groups.set(k, []).get(k)!).push(e);
  }
  const pos = new Map<string, [number, number]>();
  for (const group of groups.values()) {
    group.forEach((e, i) => {
      if (i === 0) return pos.set(e.id, [e.lon, e.lat]);
      // Spirale : ~130 m par pas autour du point d'origine.
      const angle = i * 2.4;
      const r = 0.0012 * Math.sqrt(i);
      pos.set(e.id, [e.lon + (r * Math.cos(angle)) / Math.cos((e.lat * Math.PI) / 180), e.lat + r * Math.sin(angle)]);
    });
  }
  return pos;
}

function toGeoJSON(events: ManifEvent[]): GeoJSON.FeatureCollection {
  const pos = spread(events);
  return {
    type: "FeatureCollection",
    features: events.map((e) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: pos.get(e.id)! },
      properties: {
        id: e.id,
        status: statusOf(e, today),
        scope: e.scope,
        level: e.reliability.level,
        // Les mobilisations les plus récentes ressortent davantage.
        weight: e.scope === "fr" && statusOf(e, today) !== "past" ? 1 : 0,
      },
    })),
  };
}

/** Restrictions visibles selon la période choisie et la recherche. */
function filterRestrictions(): Restriction[] {
  if (!showRestrictions || filters.scope === "world") return [];
  const from =
    filters.period === "7d" ? addDays(today, -7) : filters.period === "30d" ? addDays(today, -30) : null;
  const q = strip(filters.q.trim().toLowerCase());
  return allRestrictions.filter((r) => {
    if (filters.period === "upcoming" && r.end < today) return false;
    if (from && r.end < from) return false;
    if (q && !strip(`${r.city} ${r.place ?? ""} ${r.description} ${r.type_label}`.toLowerCase()).includes(q))
      return false;
    return true;
  });
}

function restrictionsGeoJSON(list: Restriction[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: list.map((r) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [r.lon, r.lat] },
      properties: {
        id: r.id,
        icon: `r-${r.type}-${restrictionStatus(r, today)}`,
        // Au centre d'une commune, l'icône est décalée pour ne pas cacher les manifs.
        shifted: r.geo_precision === "commune" ? 1 : 0,
        rank: { active: 2, upcoming: 1, past: 0 }[restrictionStatus(r, today)],
      },
    })),
  };
}

/** Dessine les pictogrammes des restrictions (pastille + icône blanche) pour MapLibre. */
function addRestrictionIcons(): void {
  const size = 64; // affiché en 32 px (pixelRatio 2)
  const palette = {
    active: { bg: css("--restriction"), fg: "#ffffff" },
    upcoming: { bg: css("--surface"), fg: css("--restriction") },
    past: { bg: css("--surface-2"), fg: css("--past") },
  };
  for (const type of Object.keys(RESTRICTION_ICON) as RestrictionType[]) {
    for (const [state, c] of Object.entries(palette)) {
      const name = `r-${type}-${state}`;
      if (map.hasImage(name)) map.removeImage(name);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      const ctx = canvas.getContext("2d")!;
      ctx.beginPath();
      ctx.roundRect(4, 4, size - 8, size - 8, 14);
      ctx.fillStyle = c.bg;
      ctx.shadowColor = "rgba(0,0,0,0.25)";
      ctx.shadowBlur = 6;
      ctx.fill();
      ctx.shadowColor = "transparent";
      ctx.lineWidth = 4;
      ctx.strokeStyle = state === "upcoming" ? palette.active.bg : "#ffffff";
      ctx.stroke();
      ctx.save();
      ctx.translate(14, 14);
      ctx.scale(36 / 24, 36 / 24);
      ctx.fillStyle = c.fg;
      ctx.fill(new Path2D(RESTRICTION_ICON[type]), "evenodd");
      ctx.restore();
      map.addImage(name, ctx.getImageData(0, 0, size, size), { pixelRatio: 2 });
    }
  }
}

/** Le style sombre dessine pistes d'aéroport et voies ferrées en noir épais : on les adoucit. */
function tidyBaseStyle(): void {
  if (!isDark()) return;
  for (const layer of map.getStyle().layers) {
    if (layer.id.includes("aeroway")) map.setLayoutProperty(layer.id, "visibility", "none");
    else if (layer.type === "line" && /rail|transit/.test(layer.id)) map.setPaintProperty(layer.id, "line-color", "#3b3a44");
  }
}

function addLayers(): void {
  tidyBaseStyle();
  if (map.getSource("events")) return;
  const colors = {
    today: css("--today"),
    upcoming: css("--upcoming"),
    past: css("--past"),
    world: css("--world"),
    text: css("--text"),
    surface: css("--surface"),
  };
  map.addSource("events", {
    type: "geojson",
    data: toGeoJSON(visible),
    cluster: true,
    clusterRadius: 42,
    clusterMaxZoom: 11,
    clusterProperties: { active: ["+", ["get", "weight"]] },
  });
  map.addLayer({
    id: "clusters",
    type: "circle",
    source: "events",
    filter: ["has", "point_count"],
    paint: {
      "circle-color": ["case", [">", ["get", "active"], 0], colors.upcoming, colors.past],
      "circle-opacity": 0.92,
      "circle-radius": ["step", ["get", "point_count"], 15, 10, 19, 50, 24, 200, 30],
      "circle-stroke-width": 3,
      "circle-stroke-color": colors.surface,
    },
  });
  map.addLayer({
    id: "cluster-count",
    type: "symbol",
    source: "events",
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["get", "point_count_abbreviated"],
      "text-font": ["Noto Sans Bold"],
      "text-size": 12,
      "text-allow-overlap": true,
    },
    paint: { "text-color": "#ffffff" },
  });
  map.addLayer({
    id: "today-halo",
    type: "circle",
    source: "events",
    filter: ["all", ["!", ["has", "point_count"]], ["==", ["get", "status"], "today"], ["==", ["get", "scope"], "fr"]],
    paint: {
      "circle-color": colors.today,
      "circle-radius": 14,
      "circle-opacity": 0.25,
      "circle-blur": 0.4,
    },
  });
  map.addLayer({
    id: "points",
    type: "circle",
    source: "events",
    filter: ["!", ["has", "point_count"]],
    // Aujourd'hui et à venir sont dessinés par-dessus les mobilisations passées.
    layout: { "circle-sort-key": ["match", ["get", "status"], "today", 2, "upcoming", 1, 0] },
    paint: {
      // Le monde (détection GDELT, moins précise) garde sa propre couleur.
      "circle-color": [
        "case",
        ["==", ["get", "scope"], "world"],
        colors.world,
        ["==", ["get", "status"], "today"],
        colors.today,
        ["==", ["get", "status"], "upcoming"],
        colors.upcoming,
        colors.past,
      ],
      // Aujourd'hui et à venir : points plus gros que les mobilisations passées.
      "circle-radius": [
        "interpolate", ["linear"], ["zoom"],
        3, ["case", ["==", ["get", "status"], "past"], 5, 7],
        10, ["case", ["==", ["get", "status"], "past"], 7, 10],
        15, ["case", ["==", ["get", "status"], "past"], 10, 13],
      ],
      "circle-stroke-width": ["match", ["get", "level"], 3, 3, 2, 2.5, 1.5],
      "circle-stroke-color": colors.surface,
      "circle-opacity": ["case", ["==", ["get", "status"], "past"], 0.75, 1],
    },
  });
  // Restrictions (bus déviés, arrêtés…) : pictogrammes au-dessus des points.
  addRestrictionIcons();
  map.addSource("restrictions", { type: "geojson", data: restrictionsGeoJSON(visibleRestrictions) });
  map.addLayer({
    id: "restrictions",
    type: "symbol",
    source: "restrictions",
    layout: {
      "icon-image": ["get", "icon"],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 5, 0.7, 11, 1],
      "icon-allow-overlap": true,
      "icon-offset": ["case", ["==", ["get", "shifted"], 1], ["literal", [0, -30]], ["literal", [0, 0]]],
      "symbol-sort-key": ["get", "rank"],
    },
  });
  // Sélection
  map.addLayer({
    id: "selected",
    type: "circle",
    source: "events",
    filter: ["==", ["get", "id"], ""],
    paint: {
      "circle-color": "rgba(0,0,0,0)",
      "circle-radius": 14,
      "circle-stroke-width": 3,
      "circle-stroke-color": colors.text,
    },
  });
}

// Pulsation douce des mobilisations du jour.
const pulseStart = performance.now();
function pulse(now: number): void {
  if (map.getLayer("today-halo") && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const t = ((now - pulseStart) % 1800) / 1800;
    map.setPaintProperty("today-halo", "circle-radius", 9 + t * 16);
    map.setPaintProperty("today-halo", "circle-opacity", 0.35 * (1 - t));
  }
  requestAnimationFrame(pulse);
}

// --- Panneau ---------------------------------------------------------------------

function popupHtml(e: ManifEvent): string {
  const when = [statusOf(e, today) === "today" ? "" : relativeDay(e.date, today), formatTime(e.time)]
    .filter(Boolean)
    .join(" · ");
  return `<div class="popup">
    <div class="meta">${statusBadge(e, today)}<span>${escapeHtml(when)}</span></div>
    <h3>${escapeHtml(e.title)}</h3>
    <div class="meta">${escapeHtml(placeLabel(e))}</div>
    <p>${escapeHtml(e.summary || e.headline)}</p>
    <div class="meta">${reliabilityHtml(e)}<span>${e.source_count} source${e.source_count > 1 ? "s" : ""}</span></div>
    <a class="more" href="${eventPath(BASE, e.id)}">Voir la fiche →</a>
  </div>`;
}

function restrictionPopupHtml(r: Restriction): string {
  const st = restrictionStatus(r, today);
  const page = `${location.origin}${withBase(BASE, "perturbations/")}#${r.id}`;
  return `<div class="popup">
    <div class="meta"><span class="badge r-${st}">${RESTRICTION_STATUS_LABEL[st]}</span><span>${escapeHtml(formatRange(r.start, r.end))}</span></div>
    <h3>${escapeHtml(r.type_label)}</h3>
    <div class="meta">${escapeHtml(r.place ? `${r.place}, ${r.city}` : r.city)}</div>
    <p>${escapeHtml(r.description)}</p>
    ${r.lines.length ? `<div class="lines">${r.lines.map((l) => `<span class="line">${escapeHtml(l)}</span>`).join("")}</div>` : ""}
    <div class="meta" style="margin-top:6px">${r.verified ? '<span class="badge verified">✓ Vérifiée</span>' : '<span class="badge">Détectée par IA</span>'}</div>
    <a class="more" href="${withBase(BASE, "perturbations/")}#${r.id}">Détails et sources →</a>
    <a class="more report" href="${escapeHtml(issueUrl("3-supprimer.yml", { lien: page, title: `[Erreur] ${r.type_label} à ${r.city}` }))}" target="_blank" rel="noopener">Signaler une erreur</a>
  </div>`;
}

function selectRestriction(r: Restriction, fly: boolean): void {
  popup?.remove();
  setSelected("");
  popup = new maplibregl.Popup({ offset: r.geo_precision === "commune" ? [0, -46] : 18, maxWidth: "300px", focusAfterOpen: false })
    .setLngLat([r.lon, r.lat])
    .setHTML(restrictionPopupHtml(r))
    .addTo(map);
  if (fly) map.flyTo({ center: [r.lon, r.lat], zoom: Math.max(map.getZoom(), 13), speed: 1.4 });
}

function select(e: ManifEvent, fly: boolean): void {
  popup?.remove();
  const pos = spread(visible).get(e.id) ?? [e.lon, e.lat];
  popup = new maplibregl.Popup({ offset: 14, maxWidth: "300px", focusAfterOpen: false })
    .setLngLat(pos)
    .setHTML(popupHtml(e))
    .addTo(map);
  popup.on("close", () => setSelected(""));
  setSelected(e.id);
  if (fly) map.flyTo({ center: pos, zoom: Math.max(map.getZoom(), e.scope === "world" ? 9 : 13), speed: 1.4 });
}

function setSelected(id: string): void {
  if (map.getLayer("selected")) map.setFilter("selected", ["==", ["get", "id"], id]);
  listEl.querySelectorAll(".event-card.active").forEach((n) => n.classList.remove("active"));
  if (id) listEl.querySelector(`[data-id="${CSS.escape(id)}"]`)?.classList.add("active");
}

function renderList(): void {
  const b = map.getBounds();
  const inView = visible.filter((e) => b.contains([e.lon, e.lat]));
  const fr = visible.filter((e) => e.scope === "fr");
  const todayN = fr.filter((e) => statusOf(e, today) === "today").length;
  const upcomingN = fr.filter((e) => statusOf(e, today) === "upcoming").length;
  const worldN = visible.length - fr.length;
  const activeR = visibleRestrictions.filter((r) => restrictionStatus(r, today) !== "past").length;
  summaryEl.innerHTML =
    filters.scope === "world"
      ? `<b>${worldN}</b> mobilisations détectées dans le monde`
      : `<b>${todayN}</b> aujourd'hui · <b>${upcomingN}</b> à venir en France` +
        (activeR ? ` · <b>${activeR}</b> perturbation${activeR > 1 ? "s" : ""}` : "") +
        (worldN ? ` <span class="muted">· ${worldN} dans le monde</span>` : "");
  const hidden = hiddenPastCount(all, filters, today);
  const showPast = hidden
    ? ` · <button class="link-btn" type="button" data-show-past>${hidden} passée${hidden > 1 ? "s" : ""} masquée${hidden > 1 ? "s" : ""} · afficher</button>`
    : "";
  listTitleEl.innerHTML = inView.length
    ? `${inView.length} mobilisation${inView.length > 1 ? "s" : ""} dans cette zone${showPast}`
    : showPast.replace(" · ", "");
  const shown = inView.slice(0, 80);
  // Perturbations visibles dans la zone, en tête de liste (en cours et à venir d'abord).
  const rank = { active: 0, upcoming: 1, past: 2 };
  const rInView = visibleRestrictions
    .filter((r) => b.contains([r.lon, r.lat]))
    .sort((a, c) => rank[restrictionStatus(a, today)] - rank[restrictionStatus(c, today)]);
  const rHtml = rInView.length
    ? `<p class="list-subtitle small muted">${rInView.length} perturbation${rInView.length > 1 ? "s" : ""} dans cette zone</p>` +
      rInView.slice(0, 6).map((r) => restrictionCardHtml(r, BASE, today, { compact: true })).join("") +
      (rInView.length > 6 ? `<a class="small" href="${withBase(BASE, "perturbations/")}">Voir les ${rInView.length} perturbations →</a>` : "") +
      `<p class="list-subtitle small muted">Mobilisations</p>`
    : "";
  listEl.innerHTML = rHtml + (shown.length
    ? shown.map((e) => eventCardHtml(e, BASE, today)).join("") +
      (inView.length > shown.length
        ? `<p class="small muted">… et ${inView.length - shown.length} autres : zoome pour affiner.</p>`
        : "")
    : filters.period === "upcoming"
      ? `<div class="empty"><p><b>Aucune mobilisation annoncée ici</b> pour aujourd'hui ou les jours à venir.</p>
          <p class="small">Dézoome pour voir ailleurs, ou affiche les mobilisations récentes.</p>
          <button class="btn" type="button" data-show-past>Voir les 7 derniers jours</button></div>`
      : `<div class="empty"><p><b>Aucune mobilisation ici</b> avec ces filtres.</p><p class="small">Dézoome, change de période ou essaie « Tout l'historique ».</p></div>`);
}

listEl.addEventListener("click", (ev) => {
  const rcard = (ev.target as HTMLElement).closest<HTMLAnchorElement>(".restriction-card");
  if (rcard && !(ev.metaKey || ev.ctrlKey || ev.shiftKey)) {
    const r = restrictionsById.get(rcard.dataset.rid!);
    if (r) {
      ev.preventDefault();
      selectRestriction(r, true);
      panel.classList.remove("open");
      handle.setAttribute("aria-expanded", "false");
    }
    return;
  }
  const card = (ev.target as HTMLElement).closest<HTMLAnchorElement>(".event-card");
  if (!card || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
  // 1er clic : on montre sur la carte. Le lien « Voir la fiche » est dans la bulle.
  if (!card.classList.contains("active")) {
    ev.preventDefault();
    const e = byId.get(card.dataset.id!);
    if (e) {
      select(e, true);
      panel.classList.remove("open");
      handle.setAttribute("aria-expanded", "false");
    }
  }
});

// « Afficher les passées » : on passe à la période « + 7 jours passés ».
document.querySelector(".panel")!.addEventListener("click", (ev) => {
  if (!(ev.target as HTMLElement).closest("[data-show-past]")) return;
  filters.period = "7d";
  refresh();
});

handle.addEventListener("click", () => {
  const open = panel.classList.toggle("open");
  handle.setAttribute("aria-expanded", String(open));
});

// --- Filtres ---------------------------------------------------------------------

function syncControls(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-period]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.period === filters.period)),
  );
  document.querySelectorAll<HTMLButtonElement>("[data-scope]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.scope === filters.scope)),
  );
  document.querySelectorAll<HTMLButtonElement>("[data-cause]").forEach((b) =>
    b.setAttribute("aria-pressed", String(filters.causes.has(b.dataset.cause!))),
  );
  (document.getElementById("level") as HTMLSelectElement).value = String(filters.minLevel);
  (document.getElementById("q") as HTMLInputElement).value = filters.q;
  document.getElementById("toggle-r")?.setAttribute("aria-pressed", String(showRestrictions));
  const extra = filters.causes.size + (filters.minLevel > 1 ? 1 : 0);
  document.getElementById("filter-count")!.textContent = extra ? `(${extra})` : "";
}

function refresh(): void {
  today = todayParis();
  visible = applyFilters(all, filters, today);
  writeFilters(filters);
  syncControls();
  visibleRestrictions = filterRestrictions();
  (map.getSource("events") as GeoJSONSource | undefined)?.setData(toGeoJSON(visible));
  (map.getSource("restrictions") as GeoJSONSource | undefined)?.setData(restrictionsGeoJSON(visibleRestrictions));
  renderList();
}

document.getElementById("toggle-r")?.addEventListener("click", () => {
  showRestrictions = !showRestrictions;
  refresh();
});

document.querySelectorAll<HTMLButtonElement>("[data-period]").forEach((b) =>
  b.addEventListener("click", () => {
    filters.period = b.dataset.period as Filters["period"];
    refresh();
  }),
);
document.querySelectorAll<HTMLButtonElement>("[data-scope]").forEach((b) =>
  b.addEventListener("click", () => {
    filters.scope = b.dataset.scope as Filters["scope"];
    refresh();
    if (filters.scope === "world") flyToView("world");
    if (filters.scope === "fr" && map.getZoom() < 4) flyToView("france");
  }),
);
document.querySelectorAll<HTMLButtonElement>("[data-cause]").forEach((b) =>
  b.addEventListener("click", () => {
    const c = b.dataset.cause!;
    filters.causes.has(c) ? filters.causes.delete(c) : filters.causes.add(c);
    refresh();
  }),
);
document.getElementById("level")!.addEventListener("change", (ev) => {
  filters.minLevel = Number((ev.target as HTMLSelectElement).value) as Filters["minLevel"];
  refresh();
});
let typing: number | undefined;
document.getElementById("q")!.addEventListener("input", (ev) => {
  clearTimeout(typing);
  typing = window.setTimeout(() => {
    filters.q = (ev.target as HTMLInputElement).value;
    refresh();
    // Recherche d'une ville : on recentre sur les résultats.
    if (filters.q && visible.length) {
      const bounds = new maplibregl.LngLatBounds();
      visible.forEach((e) => bounds.extend([e.lon, e.lat]));
      map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 600 });
    }
  }, 250);
});

function flyToView(name: keyof typeof VIEWS): void {
  map.flyTo({ ...VIEWS[name], speed: 1.6 });
}
document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((b) =>
  b.addEventListener("click", () => flyToView(b.dataset.view as keyof typeof VIEWS)),
);

// --- Interactions carte ------------------------------------------------------------

map.on("click", "clusters", async (ev) => {
  const f = ev.features?.[0] as MapGeoJSONFeature | undefined;
  if (!f) return;
  const src = map.getSource("events") as GeoJSONSource;
  const zoom = await src.getClusterExpansionZoom(f.properties.cluster_id);
  map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: zoom + 0.3 });
});
map.on("click", "points", (ev) => {
  const id = ev.features?.[0]?.properties.id;
  const e = id && byId.get(id);
  if (e) select(e, false);
});
map.on("click", "restrictions", (ev) => {
  const id = ev.features?.[0]?.properties.id;
  const r = id && restrictionsById.get(id);
  if (r) selectRestriction(r, false);
});
for (const layer of ["clusters", "points", "restrictions"]) {
  map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
}
map.on("moveend", renderList);

// Changement de thème : nouveau fond de carte, puis on remet nos couches.
window.addEventListener("themechange", () => {
  popup?.remove();
  map.setStyle(isDark() ? STYLES.dark : STYLES.light);
  map.once("style.load", () => {
    addLayers();
    (map.getSource("events") as GeoJSONSource).setData(toGeoJSON(visible));
    (map.getSource("restrictions") as GeoJSONSource).setData(restrictionsGeoJSON(visibleRestrictions));
  });
});

// --- Démarrage ---------------------------------------------------------------------

async function start(): Promise<void> {
  try {
    const data = await loadData();
    all = data.events;
    byId = new Map(all.map((e) => [e.id, e]));
    allRestrictions = data.restrictions ?? [];
    restrictionsById = new Map(allRestrictions.map((r) => [r.id, r]));
    updatedEl.textContent = `Mise à jour automatique ${formatAgo(data.generated_at)} · ${data.count.fr} en France, ${data.count.world} dans le monde`;
  } catch (err) {
    errorEl.hidden = false;
    errorEl.textContent = "Impossible de charger les mobilisations pour le moment. Réessaie dans quelques minutes.";
    console.error(err);
  }
  // La liste s'affiche sans attendre le fond de carte.
  refresh();
  const ready = () => {
    addLayers();
    refresh();
    requestAnimationFrame(pulse);
    const e = targetEvent ? byId.get(targetEvent) : undefined;
    if (e) select(e, true);
    const r = targetRestriction ? restrictionsById.get(targetRestriction) : undefined;
    if (r) {
      // Une restriction passée reste accessible depuis un lien direct.
      if (!visibleRestrictions.includes(r)) {
        filters.period = "all";
        refresh();
      }
      selectRestriction(r, true);
    }
  };
  if (map.isStyleLoaded()) ready();
  else map.once("load", ready);
}

map.on("error", (ev) => console.warn("Carte :", ev.error?.message));
start();
