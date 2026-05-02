/** IST (Asia/Kolkata) for run logs UI */
const TZ = "Asia/Kolkata";
const LOCALE = "en-IN";

export function formatRunStartedAt(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(LOCALE, {
      timeZone: TZ,
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}

export function formatEventLogTime(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString(LOCALE, {
      timeZone: TZ,
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}
