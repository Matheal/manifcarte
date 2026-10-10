// Carte interactive (page d'accueil).
import type { GeoJSONSource, MapGeoJSONFeature, Popup } from "maplibre-gl";
import { eventCardHtml, reliabilityHtml, statusBadge } from "../lib/render";
import {
  type Dataset,
  type ManifEvent,
  escapeHtml,
  eventPath,
  formatAgo,
  formatTime,
  placeLabel,
  relativeDay,
  statusOf,
  todayParis,
} from "../lib/shared";
import { type Filters, applyFilters, loadData, readFilters, writeFilters } from "./filters";
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

/** Le style sombre dessine les pistes d'aéroport en noir épais : on les masque. */
function tidyBaseStyle(): void {
  if (!isDark()) return;
  for (const layer of map.getStyle().layers) {
    if (layer.id.includes("aeroway")) map.setLayoutProperty(layer.id, "visibility", "none");
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
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 5, 10, 7, 15, 10],
      "circle-stroke-width": ["match", ["get", "level"], 3, 3, 2, 2.5, 1.5],
      "circle-stroke-color": colors.surface,
      "circle-opacity": ["case", ["==", ["get", "status"], "past"], 0.75, 1],
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
  summaryEl.innerHTML =
    filters.scope === "world"
      ? `<b>${worldN}</b> mobilisations détectées dans le monde`
      : `<b>${todayN}</b> aujourd'hui · <b>${upcomingN}</b> à venir en France` +
        (worldN ? ` <span class="muted">· ${worldN} dans le monde</span>` : "");
  listTitleEl.textContent = inView.length
    ? `${inView.length} mobilisation${inView.length > 1 ? "s" : ""} dans cette zone de la carte`
    : "";
  const shown = inView.slice(0, 80);
  listEl.innerHTML = shown.length
    ? shown.map((e) => eventCardHtml(e, BASE, today)).join("") +
      (inView.length > shown.length
        ? `<p class="small muted">… et ${inView.length - shown.length} autres : zoome pour affiner.</p>`
        : "")
    : `<div class="empty"><p><b>Aucune mobilisation ici</b> avec ces filtres.</p><p class="small">Dézoome, change de période ou essaie « Tout ».</p></div>`;
}

listEl.addEventListener("click", (ev) => {
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
  const extra = filters.causes.size + (filters.minLevel > 1 ? 1 : 0);
  document.getElementById("filter-count")!.textContent = extra ? `(${extra})` : "";
}

function refresh(): void {
  today = todayParis();
  visible = applyFilters(all, filters, today);
  writeFilters(filters);
  syncControls();
  (map.getSource("events") as GeoJSONSource | undefined)?.setData(toGeoJSON(visible));
  renderList();
}

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
for (const layer of ["clusters", "points"]) {
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
  });
});

// --- Démarrage ---------------------------------------------------------------------

async function start(): Promise<void> {
  try {
    const data = await loadData();
    all = data.events;
    byId = new Map(all.map((e) => [e.id, e]));
    updatedEl.textContent = `Mise à jour automatique ${formatAgo(data.generated_at)} · ${data.count.fr} en France, ${data.count.world} dans le monde`;
  } catch (err) {
    errorEl.hidden = false;
    errorEl.textContent = "Impossible de charger les mobilisations pour le moment. Réessaie dans quelques minutes.";
    console.error(err);
  }
  // La liste s'affiche sans attendre le fond de carte.
  refresh();
  // Lien direct vers une manif : ?manif=<id>
  const target = new URLSearchParams(location.search).get("manif");
  const ready = () => {
    addLayers();
    refresh();
    requestAnimationFrame(pulse);
    const e = target ? byId.get(target) : undefined;
    if (e) select(e, true);
  };
  if (map.isStyleLoaded()) ready();
  else map.once("load", ready);
}

map.on("error", (ev) => console.warn("Carte :", ev.error?.message));
start();
