export type RouteQuestion = { id?: string; vraag: string; reden?: string; opties: Record<string, unknown> };

// Vangnet voor oudere routes waarvan de opties nog geen `label` van de engine hebben.
const GENERIC: Record<string, string> = { graag: "Graag", belangrijk: "Ja, belangrijk", vermijd: "Liever niet", zoek: "Graag", ja: "Ja", nee: "Nee" };

export function optionLabel(question: RouteQuestion, option: string): string {
  // Het label van de engine wint altijd.
  const value = question.opties[option] as { label?: unknown } | undefined;
  if (typeof value?.label === "string" && value.label) return value.label;
  if (option === "ok") return "Maakt me niet uit";
  const label = GENERIC[option];
  if (label) return label;
  const text = option.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** De reden van de engine leesbaar: hoofdletter, zonder het technische staartje "; …voorkeur onbekend". */
export function reasonText(reden?: string | null): string {
  const text = (reden || "").replace(/;\s*[^;]*onbekend\.?\s*$/i, "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

const TOPICS: Record<string, string> = { startplaats: "Plaats", ondergrond: "Ondergrond", heuvels: "Heuvels", fietspaden: "Fietspaden", oversteken: "Oversteken", stil: "Rustige wegen", kasseien: "Kasseien", knooppunten: "Knooppunten", plek_afstand: "Afstand", speeltuin: "Speeltuin", toilet: "Toilet" };

/** Kort onderwerp voor het overzicht, zodat "Maakt me niet uit" zegt waarover het gaat. */
export function questionTopic(question: RouteQuestion): string {
  return (question.id && TOPICS[question.id]) || "";
}

/** Toon de reden alleen als ze iets toevoegt aan de vraag zelf. */
export function reasonAddsInfo(question: RouteQuestion): boolean {
  const reason = reasonText(question.reden).toLowerCase();
  if (!reason || question.vraag.toLowerCase().includes(reason.slice(0, 30))) return false;
  // Herhaalt de reden alleen getallen die al in de vraag staan, dan voegt ze niets toe.
  const numbers = reason.match(/\d+(?:[.,]\d+)?/g) ?? [];
  return !numbers.length || numbers.some(n => !question.vraag.includes(n));
}
