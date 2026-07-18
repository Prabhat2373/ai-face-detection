import { Router } from "express";
import { z } from "zod";
import { asyncHandler } from "../utils/asyncHandler.js";
import { env } from "../config/env.js";
import { inspectLicense, saveInstalledLicense, verifyLicenseBlob, type LicenseBlob } from "../utils/license.js";

export const licenseRoutes = Router();

const licenseSchema = z.object({
  payload: z.object({
    tenantId: z.string().min(1),
    companyName: z.string().min(1),
    plan: z.string().min(1),
    cloudSyncEnabled: z.boolean(),
    issuedAt: z.string().min(1),
    expiresAt: z.string().nullable(),
    machineId: z.string().nullable(),
  }),
  signature: z.string().min(1),
  algorithm: z.literal("HS256"),
});

licenseRoutes.get(
  "/license/status",
  asyncHandler(async (_req, res) => {
    const status = await inspectLicense();
    res.json({ status });
  }),
);

licenseRoutes.post(
  "/license/activate",
  asyncHandler(async (req, res) => {
    const parsed = licenseSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "Invalid license payload", issues: parsed.error.flatten() });
      return;
    }
    if (!env.LICENSE_SECRET) {
      res.status(500).json({ error: "LICENSE_SECRET is not configured on the server" });
      return;
    }
    if (!verifyLicenseBlob(parsed.data as LicenseBlob, env.LICENSE_SECRET)) {
      res.status(400).json({ error: "License signature is invalid" });
      return;
    }
    const filePath = await saveInstalledLicense(parsed.data as LicenseBlob);
    res.json({ ok: true, filePath, license: parsed.data });
  }),
);
