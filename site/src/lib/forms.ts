// Formulaires de contribution. Les « label » doivent être identiques aux intitulés des
// formulaires GitHub (.github/ISSUE_TEMPLATE) : le collecteur les lit pour appliquer la contribution.
import { CAUSES } from "./shared";

export type ReportType = "ajout-manif" | "restriction" | "suppression" | "publication";

export interface Field {
  id: string;
  label: string;
  kind: "input" | "textarea" | "select";
  required?: boolean;
  placeholder?: string;
  hint?: string;
  options?: string[];
}

export interface FormDef {
  type: ReportType;
  template: string;
  name: string;
  short: string;
  titlePrefix: string;
  fields: Field[];
}

const VILLE: Field = { id: "ville", label: "Ville", kind: "input", required: true, placeholder: "Nancy" };
const SOURCE: Field = { id: "source", label: "Source (lien)", kind: "input", placeholder: "https://…" };

export const FORMS: Record<ReportType, FormDef> = {
  publication: {
    type: "publication",
    template: "4-signaler-publication.yml",
    name: "Signaler une publication (TikTok, Instagram, X…)",
    short: "Publication",
    titlePrefix: "[Publication]",
    fields: [
      { id: "lien", label: "Lien de la publication", kind: "input", required: true, placeholder: "https://www.tiktok.com/@…/video/…" },
      { id: "plateforme", label: "Plateforme", kind: "select", required: true,
        options: ["TikTok", "Instagram", "X / Twitter", "Snapchat", "Facebook", "Telegram", "YouTube", "Autre"] },
      { id: "texte", label: "Texte de la publication", kind: "textarea", required: true,
        hint: "Recopie ce qu'annonce la publication (date, heure, lieu, revendication), sans nom ni pseudo.",
        placeholder: "BLOCUS LYCÉE POINCARÉ JEUDI 7H30 tout le monde devant l'entrée" },
      { ...VILLE, required: false },
      { id: "date", label: "Date", kind: "input", placeholder: "15/10/2026" },
    ],
  },
  "ajout-manif": {
    type: "ajout-manif",
    template: "1-ajouter-manif.yml",
    name: "Ajouter une mobilisation",
    short: "Mobilisation",
    titlePrefix: "[Ajout]",
    fields: [
      VILLE,
      { id: "date", label: "Date", kind: "input", required: true, placeholder: "13/10/2026" },
      { id: "heure", label: "Heure de début", kind: "input", placeholder: "14h30" },
      { id: "lieu", label: "Lieu précis", kind: "input", placeholder: "place Stanislas" },
      { id: "type", label: "Type de mobilisation", kind: "select", required: true,
        options: ["Manifestation", "Rassemblement", "Blocus", "Grève", "Marche", "Autre"] },
      { id: "cause", label: "Cause principale", kind: "select", options: Object.values(CAUSES) },
      { id: "description", label: "Description", kind: "textarea", hint: "Une ou deux phrases factuelles." },
      SOURCE,
    ],
  },
  restriction: {
    type: "restriction",
    template: "2-signaler-restriction.yml",
    name: "Signaler une restriction",
    short: "Restriction",
    titlePrefix: "[Restriction]",
    fields: [
      { id: "rtype", label: "Type de restriction", kind: "select", required: true,
        options: ["Transports (bus, tram, train)", "Circulation / route fermée", "Établissement fermé ou perturbé",
          "Arrêté / interdiction", "Commerces / services fermés", "Autre"] },
      VILLE,
      { id: "lieu", label: "Lieu précis", kind: "input", placeholder: "place Carnot" },
      { id: "lignes", label: "Lignes de transport concernées", kind: "input", placeholder: "T1, Corol, 2" },
      { id: "debut", label: "Date de début", kind: "input", required: true, placeholder: "13/10/2026" },
      { id: "fin", label: "Date de fin", kind: "input", placeholder: "16/10/2026", hint: "Vide si un seul jour." },
      { id: "description", label: "Description", kind: "textarea", required: true,
        placeholder: "Lignes T1 et 2 déviées par le boulevard Lobau de 10 h à 14 h" },
      SOURCE,
    ],
  },
  suppression: {
    type: "suppression",
    template: "3-supprimer.yml",
    name: "Signaler une erreur",
    short: "Erreur",
    titlePrefix: "[Erreur]",
    fields: [
      { id: "lien", label: "Lien de la fiche ou de l'article", kind: "input", required: true,
        placeholder: "https://matheal.github.io/manifcarte/manif/…" },
      { id: "motif", label: "Motif", kind: "select", required: true,
        options: ["Fausse information", "Mauvaise date", "Mauvais lieu", "Doublon", "Ce n'est pas une mobilisation", "Autre"] },
      { id: "details", label: "Précisions", kind: "textarea", hint: "Si la date ou le lieu est faux, indique la bonne information." },
    ],
  },
};

/** Corps du ticket, au même format que les formulaires GitHub (« ### Intitulé » + valeur). */
export function issueBody(def: FormDef, values: Record<string, string>): string {
  return def.fields
    .map((f) => `### ${f.label}\n\n${(values[f.id] || "").trim() || "_No response_"}`)
    .join("\n\n");
}
