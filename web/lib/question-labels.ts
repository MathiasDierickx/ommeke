export type RouteQuestion = { id?: string; vraag: string; reden?: string; opties: Record<string, unknown> };

const OPTION_LABELS: Record<string, Record<string, string>> = {
  kasseien: { graag: "Graag kasseien", vermijd: "Liever geen kasseien" },
  heuvels: { zoek: "Graag heuvels", vlak: "Liever vlak" },
  ondergrond: { verhard: "Liever verhard", onverhard: "Graag onverhard" },
  fietspaden: { belangrijk: "Liefst op fietspaden" },
  oversteken: { vermijd: "Liever weinig oversteken" },
};

export function optionLabel(question: RouteQuestion, option: string): string {
  if (question.id === "startplaats") {
    const value = question.opties[option] as { label?: unknown } | undefined;
    if (typeof value?.label === "string") return value.label;
  }
  if (option === "ok") return "Maakt niet uit";
  const label = question.id ? OPTION_LABELS[question.id]?.[option] : undefined;
  if (label) return label;
  const text = option.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
