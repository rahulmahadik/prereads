// Mirrors backend/app/services/reading_age.py::heuristic. Keep the two identical.
export interface ReadingAge {
  label: string;
  min_age: number;
  source: "catalogue" | "estimated";
}

function kind(texts: string[]): "child" | "teen" | "adult" | null {
  const j = texts.map((t) => t.toLowerCase()).join(" | ");
  if (j.includes("young adult") || j.includes("teen")) return "teen";
  if (j.includes("juvenile") || j.includes("child")) return "child";
  if (j.includes("adult")) return "adult";
  return null;
}

const mk = (label: string, min_age: number, source: ReadingAge["source"]): ReadingAge => ({ label, min_age, source });

export function readingAge(audience: string[] = [], subjects: string[] = [], level = 3, pages?: number | null): ReadingAge {
  const aud = kind(audience);
  if (aud === "child") return mk("Children 8–12", 8, "catalogue");
  if (aud === "teen") return mk("Teen", 13, "catalogue");
  if (aud === "adult") return mk("Adult", 18, "catalogue");
  const sub = kind(subjects.filter((s) => !s.toLowerCase().includes("adult") || s.toLowerCase().includes("young adult")));
  if (sub === "child") return mk("Children 8–12", 8, "estimated");
  if (sub === "teen") return mk("Teen", 13, "estimated");
  if (level <= 2) return (pages ?? 0) >= 500 ? mk("Reading age 15+", 15, "estimated") : mk("Reading age 12+", 12, "estimated");
  if (level === 3) return mk("Reading age 15+", 15, "estimated");
  return mk("Adult", 18, "estimated");
}

export const readingAgeText = (a: ReadingAge) => a.label + (a.source === "estimated" ? " · estimated" : "");
