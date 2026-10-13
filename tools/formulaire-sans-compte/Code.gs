/**
 * Relais du formulaire « sans compte » de ManifCarte.
 *
 * Le site envoie le formulaire ici ; ce script crée un ticket GitHub avec l'étiquette
 * « anonyme ». Ces tickets ne sont JAMAIS appliqués automatiquement : il faut que
 * l'équipe ajoute l'étiquette « approuvé ».
 *
 * Installation : voir LISEZMOI.md dans ce dossier.
 */
const REPO = "Matheal/manifcarte";
const TYPES = ["ajout-manif", "restriction", "suppression", "publication"];
const MAX_PER_HOUR = 30; // garde-fou anti-spam global

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    // Pot de miel : un champ invisible que seuls les robots remplissent.
    if (data.website) return reply({ ok: true });
    if (TYPES.indexOf(data.type) === -1) return reply({ ok: false, error: "Type de signalement inconnu." });
    // Un humain met plus de 3 secondes à remplir le formulaire.
    if (!(Number(data.elapsed) > 3000)) return reply({ ok: false, error: "Envoi trop rapide, réessaie." });

    const cache = CacheService.getScriptCache();
    const count = Number(cache.get("count") || 0);
    if (count >= MAX_PER_HOUR) {
      return reply({ ok: false, error: "Beaucoup de signalements en ce moment : réessaie dans une heure." });
    }
    cache.put("count", String(count + 1), 3600);

    const title = String(data.title || "Signalement").slice(0, 120);
    const body = String(data.body || "").slice(0, 6000) + "\n\n---\n_Envoyé sans compte depuis le site ManifCarte._";
    const token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
    const res = UrlFetchApp.fetch("https://api.github.com/repos/" + REPO + "/issues", {
      method: "post",
      contentType: "application/json",
      muteHttpExceptions: true,
      headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json" },
      payload: JSON.stringify({ title: title, body: body, labels: [data.type, "anonyme"] }),
    });
    if (res.getResponseCode() >= 300) return reply({ ok: false, error: "Le serveur a refusé l'envoi. Réessaie plus tard." });
    return reply({ ok: true, number: JSON.parse(res.getContentText()).number });
  } catch (err) {
    return reply({ ok: false, error: "Erreur inattendue. Réessaie plus tard." });
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
