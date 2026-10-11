// Pictogrammes des restrictions (chemins SVG 24×24, remplissage « evenodd »).
import type { RestrictionType } from "./shared";

export const RESTRICTION_ICON: Record<RestrictionType, string> = {
  // Bus
  transport:
    "M6 2.5h12A2.5 2.5 0 0 1 20.5 5v11a2.5 2.5 0 0 1-1.5 2.3V20a1 1 0 0 1-1 1h-1.2a1 1 0 0 1-1-1v-1.2H8.2V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-1.7A2.5 2.5 0 0 1 3.5 16V5A2.5 2.5 0 0 1 6 2.5ZM6 6v5.5h12V6H6Zm1.8 7.6a1.4 1.4 0 1 0 0 2.8 1.4 1.4 0 0 0 0-2.8Zm8.4 0a1.4 1.4 0 1 0 0 2.8 1.4 1.4 0 0 0 0-2.8Z",
  // Cône de chantier
  circulation:
    "M10.4 2.5h3.2l1.1 4.2H9.3l1.1-4.2Zm-1.6 6.2h6.4l1.1 4.2H7.7l1.1-4.2Zm-1.6 6.2h9.6l1.1 4.1H6.1l1.1-4.1ZM3 20h18v2H3v-2Z",
  // Bâtiment scolaire (toque)
  etablissement:
    "M12 3 1.5 8.5 12 14l8.5-4.5V16H22V8.5L12 3ZM5.5 12.6v3.9c0 1.9 2.9 3.5 6.5 3.5s6.5-1.6 6.5-3.5v-3.9L12 16l-6.5-3.4Z",
  // Sens interdit
  arrete: "M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20ZM6 10.6v2.8h12v-2.8H6Z",
  // Boutique
  commerce:
    "M4.2 3h15.6l1.7 5.6a3 3 0 0 1-2 3.3V21h-15v-9.1a3 3 0 0 1-2-3.3L4.2 3ZM7 14v5h4v-5H7Zm6 0v3h4v-3h-4Z",
  // Triangle d'alerte
  autre: "M12 2.5 1.5 21h21L12 2.5Zm-1.2 6.5h2.4v6h-2.4V9Zm0 7.5h2.4V19h-2.4v-2.5Z",
};

export function restrictionIconSvg(type: RestrictionType, size = 18): string {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="${RESTRICTION_ICON[type]}"/></svg>`;
}
