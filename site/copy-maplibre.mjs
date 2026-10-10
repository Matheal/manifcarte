// Copie MapLibre (module + worker + CSS) dans public/vendor : MapLibre 6 charge son
// worker à côté de son propre fichier, il ne doit donc pas être ré-empaqueté par Vite.
import fs from "node:fs";

const from = "node_modules/maplibre-gl/dist";
const to = "public/vendor/maplibre";
fs.mkdirSync(to, { recursive: true });
for (const f of ["maplibre-gl.mjs", "maplibre-gl-shared.mjs", "maplibre-gl-worker.mjs", "maplibre-gl.css", "LICENSE.txt"]) {
  const src = f === "LICENSE.txt" ? "node_modules/maplibre-gl/LICENSE.txt" : `${from}/${f}`;
  fs.copyFileSync(src, `${to}/${f}`);
}
console.log("MapLibre copié dans", to);
