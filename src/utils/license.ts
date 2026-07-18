import { createHmac } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { env } from "../config/env.js";

export type LicensePayload = {
  tenantId: string;
  companyName: string;
  plan: string;
  cloudSyncEnabled: boolean;
  issuedAt: string;
  expiresAt: string | null;
  machineId: string | null;
};

export type LicenseBlob = {
  payload: LicensePayload;
  signature: string;
  algorithm: string;
};

export type LicenseStatus =
  | { valid: true; installed: true; license: LicenseBlob; filePath: string }
  | { valid: false; installed: false; reason: string; filePath: string }
  | { valid: false; installed: true; reason: string; filePath: string };

const fallbackLicensePath = resolve(process.cwd(), "data", "license.json");

export function getLicensePath(): string {
  return resolve(process.cwd(), env.LICENSE_FILE || fallbackLicensePath);
}

export function signLicensePayload(secret: string, payload: LicensePayload): string {
  const body = canonicalJson(payload);
  return createHmac("sha256", secret).update(body).digest("base64url");
}

export function verifyLicenseBlob(blob: unknown, secret: string): blob is LicenseBlob {
  if (!blob || typeof blob !== "object") return false;
  const candidate = blob as Partial<LicenseBlob>;
  if (!candidate.payload || !candidate.signature || candidate.algorithm !== "HS256") return false;
  const signature = signLicensePayload(secret, candidate.payload as LicensePayload);
  return signature === candidate.signature;
}

export async function readInstalledLicense(): Promise<LicenseBlob | null> {
  const filePath = getLicensePath();
  try {
    const raw = await readFile(filePath, "utf8");
    return JSON.parse(raw) as LicenseBlob;
  } catch {
    return null;
  }
}

export async function saveInstalledLicense(blob: LicenseBlob): Promise<string> {
  const filePath = getLicensePath();
  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(blob, null, 2)}\n`, "utf8");
  return filePath;
}

export async function inspectLicense(): Promise<LicenseStatus> {
  const filePath = getLicensePath();
  const raw = await readInstalledLicense();
  if (!raw) {
    return { valid: false, installed: false, reason: "No license file found", filePath };
  }
  if (!env.LICENSE_SECRET) {
    return { valid: false, installed: true, reason: "LICENSE_SECRET is not configured", filePath };
  }
  if (!verifyLicenseBlob(raw, env.LICENSE_SECRET)) {
    return { valid: false, installed: true, reason: "License signature is invalid", filePath };
  }
  return { valid: true, installed: true, license: raw, filePath };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((entry) => canonicalJson(entry)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b));
    return `{${entries.map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
