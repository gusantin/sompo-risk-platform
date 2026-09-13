import "server-only";

export function isPresentationDeployment() {
  return process.env.NODE_ENV === "production" || process.env.VERCEL === "1";
}

export function backendUrl(): string | null {
  const configured = process.env.SOMPO_BACKEND_URL?.trim();
  return configured ? configured.replace(/\/$/, "") : isPresentationDeployment() ? null : "http://127.0.0.1:5000";
}
