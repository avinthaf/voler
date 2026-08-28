import envPaths from "env-paths";
import { mkdirSync, writeFileSync, readFileSync, readdirSync, unlinkSync } from "fs";
import { join } from "path";

const paths = envPaths("voler", { suffix: "" });
const sessionsDir = join(paths.data, "sessions");

export interface Message {
  role: string;
  content: string;
}

export interface Session {
  id: string;
  name: string;
  createdAt: string;
  messages: Message[];
}

export function ensureStorageDir() {
  mkdirSync(sessionsDir, { recursive: true });
}

export function generateSessionId(): string {
  const now = new Date();
  const timestamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const random = Math.random().toString(36).slice(2, 6);
  return `${timestamp}_${random}`;
}

export function generateSessionName(firstMessage: string): string {
  return firstMessage
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, "")
    .trim()
    .split(/\s+/)
    .slice(0, 6)
    .join("-");
}

export function saveSession(id: string, name: string, messages: Message[]) {
  const session: Session = { id, name, createdAt: new Date().toISOString(), messages };
  const file = join(sessionsDir, `${id}.json`);
  writeFileSync(file, JSON.stringify(session, null, 2));
}

export function listSessions(): { id: string; name: string }[] {
  ensureStorageDir();
  return readdirSync(sessionsDir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => {
      const raw = JSON.parse(readFileSync(join(sessionsDir, f), "utf-8"));
      return { id: raw.id ?? f.replace(".json", ""), name: raw.name ?? "Unnamed" };
    })
    .sort((a, b) => b.id.localeCompare(a.id));
}

export function loadSession(id: string): Session {
  const file = join(sessionsDir, `${id}.json`);
  return JSON.parse(readFileSync(file, "utf-8"));
}

export function deleteSession(id: string) {
  const file = join(sessionsDir, `${id}.json`);
  unlinkSync(file);
}

export function clearSessions() {
  const files = readdirSync(sessionsDir).filter((f) => f.endsWith(".json"));
  files.forEach((f) => unlinkSync(join(sessionsDir, f)));
  return files.length;
}
