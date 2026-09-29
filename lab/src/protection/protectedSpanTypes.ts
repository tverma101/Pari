import type { ProtectedSpanType } from "../core/types.js";

/**
 * Human-readable descriptions for each protected span type.
 */
export const SPAN_TYPE_LABELS: Record<ProtectedSpanType, string> = {
  quote: "Quoted text",
  entity_name: "Named entity (person, place, organization)",
  number: "Numeric value",
  date: "Date",
  percentage: "Percentage value",
  currency: "Currency amount",
  url: "URL",
  email: "Email address",
  citation: "Academic citation",
  course_code: "Course code (e.g., PSY-150)",
  title: "Work title",
  acronym: "Acronym or all-caps term",
  other: "Other protected span",
};

/**
 * Risk level for each span type — how dangerous it is to modify.
 */
export const SPAN_RISK_LEVEL: Record<ProtectedSpanType, "critical" | "high" | "medium" | "low"> = {
  quote: "critical",
  entity_name: "high",
  number: "high",
  date: "critical",
  percentage: "high",
  currency: "high",
  url: "critical",
  email: "critical",
  citation: "critical",
  course_code: "high",
  title: "high",
  acronym: "high",
  other: "medium",
};

/**
 * Whether modifying a span of this type would be a hard rejection.
 */
export function isHardRejectionType(type: ProtectedSpanType): boolean {
  return SPAN_RISK_LEVEL[type] === "critical";
}
