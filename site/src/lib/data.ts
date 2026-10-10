// Lecture des données au moment du build (côté Node uniquement).
import fs from "node:fs";
import path from "node:path";
import type { Dataset } from "./shared";

const FILE = path.resolve(process.cwd(), "public/data/events.json");

const EMPTY: Dataset = {
  generated_at: new Date(0).toISOString(),
  focus: { name: "Nancy", insee: "54395", lat: 48.6921, lon: 6.1844, zoom: 12 },
  sources: {},
  count: { fr: 0, world: 0 },
  events: [],
};

let cache: Dataset | null = null;

export function loadDataset(): Dataset {
  if (!cache) {
    cache = fs.existsSync(FILE) ? (JSON.parse(fs.readFileSync(FILE, "utf-8")) as Dataset) : EMPTY;
  }
  return cache;
}
