export type RouteQuestion = { id?: string; vraag: string; reden?: string; opties: Record<string, unknown> };

const OPTION_LABELS: Record<string, Record<string, string>> = {
  kasseien: { graag: "Graag kasseien", vermijd: "Liever geen kasseien" },
  heuvels: { zoek: "Graag heuvels", vlak: "Liever vlak" },
  ondergrond: { verhard: "Liever verhard", onverhard: "Graag onverhard" },
  fietspaden: { belangrijk: "Liefst op fietspaden" },
  oversteken: { vermijd: "Liever weinig oversteken" },
  stil: { belangrijk: "Liefst rustige wegen" },
  knooppunten: { graag: "Graag via knooppunten" },
};

export function optionLabel(question: RouteQuestion, option: string): string {
  // De engine geeft soms een leesbaar label mee (startplaats, plek_afstand); dat wint altijd.
  const value = question.opties[option] as { label?: unknown } | undefined;
  if (typeof value?.label === "string" && value.label) return value.label;
  if (option === "ok") return "Maakt me niet uit";
  const label = question.id ? OPTION_LABELS[question.id]?.[option] : undefined;
  if (label) return label;
  const text = option.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** De reden van de engine leesbaar: hoofdletter, zonder het technische staartje "; …voorkeur onbekend". */
export function reasonText(reden?: string | null): string {
  const text = (reden || "").replace(/;\s*[^;]*onbekend\.?\s*$/i, "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

const TOPICS: Record<string, string> = { startplaats: "Plaats", ondergrond: "Ondergrond", heuvels: "Heuvels", fietspaden: "Fietspaden", oversteken: "Oversteken", stil: "Rustige wegen", kasseien: "Kasseien", knooppunten: "Knooppunten", plek_afstand: "Afstand" };

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
