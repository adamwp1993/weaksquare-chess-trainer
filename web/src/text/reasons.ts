// The mistake reasons (§7.3) as the Coach and the Progress tab word them, lower case for use inside a sentence.
export const REASON_LABEL: Record<string, string> = {
  didntLook: "didn't look",
  missedResource: "missed a resource",
  miscalculated: "miscalculated",
  unknownPattern: "unknown pattern",
  rushed: "rushed",
  misclick: "misclick",
};

/** "70% didn't look, 20% miscalculated" (FR-10.38), or "—" with none tagged. */
export function reasonMix(r: Record<string, number>): string {
  const total = Object.values(r).reduce((a, b) => a + b, 0);
  if (!total) return "—";
  return Object.entries(r)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${Math.round((100 * n) / total)}% ${REASON_LABEL[k] ?? k}`)
    .join(", ");
}
