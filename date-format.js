const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const newYorkClock = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", year: "numeric", month: "short", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short",
});

function timeParts(value) {
  if (value === null || value === undefined || value === "") return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return Object.fromEntries(newYorkClock.formatToParts(date).map(({ type, value }) => [type, value]));
}

export function formatTime(value, includeZone = true) {
  const parts = timeParts(value);
  return parts ? `${parts.hour}:${parts.minute}${includeZone ? ` ${parts.timeZoneName}` : ""}` : "—";
}

export function formatDate(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return "—";
  return `${String(date.getDate()).padStart(2, "0")}/${months[date.getMonth()]}/${date.getFullYear()}`;
}

export function formatDateTime(value) {
  const parts = timeParts(value);
  return parts ? `${parts.day}/${parts.month}/${parts.year}, ${parts.hour}:${parts.minute} ${parts.timeZoneName}` : "—";
}

export function parseDateInput(value) {
  const match = /^(\d{2})\/([a-z]{3})\/(\d{4})$/i.exec(value.trim());
  if (!match) return null;
  const month = months.findIndex((name) => name.toLowerCase() === match[2].toLowerCase());
  const iso = `${match[3]}-${String(month + 1).padStart(2, "0")}-${match[1]}`;
  const date = new Date(`${iso}T00:00:00`);
  return month >= 0 && !Number.isNaN(date.getTime()) && date.getMonth() === month && date.getDate() === Number(match[1]) ? iso : null;
}

export function validateDateInputs(form) {
  for (const input of form.querySelectorAll("[data-date-input]")) {
    input.setCustomValidity(input.value && !parseDateInput(input.value) ? "Enter a valid date as dd/mmm/yyyy, for example 05/Sep/2026." : "");
  }
  return form.reportValidity();
}

if (typeof document !== "undefined") {
  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-date-input]")) event.target.setCustomValidity("");
  });
}
