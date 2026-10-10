// Chargement de MapLibre depuis public/vendor (voir copy-maplibre.mjs).
import type * as ML from "maplibre-gl";
import { withBase } from "../lib/shared";

export type MapLibre = typeof ML;

export function loadMapLibre(): Promise<MapLibre> {
  const base = import.meta.env.BASE_URL;
  if (!document.querySelector("link[data-maplibre]")) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = withBase(base, "vendor/maplibre/maplibre-gl.css");
    link.dataset.maplibre = "";
    document.head.append(link);
  }
  // Import natif du navigateur (Vite ne doit pas réécrire cette URL, en dev comme en prod).
  const nativeImport = new Function("u", "return import(u)") as (u: string) => Promise<MapLibre>;
  return nativeImport(new URL(withBase(base, "vendor/maplibre/maplibre-gl.mjs"), location.href).href);
}

export const MAP_STYLES = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

export function isDark(): boolean {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
