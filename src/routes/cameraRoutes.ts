import { Router } from "express";
import { z } from "zod";
import { faceDetectionService } from "../services/faceDetectionService.js";
import { asyncHandler } from "../utils/asyncHandler.js";

export const cameraRoutes = Router();

const cameraSchema = z.object({
  id: z.string().trim().min(1).optional(),
  name: z.string().trim().min(1).max(120),
  cameraRole: z.enum(["general", "check_in", "check_out"]).optional(),
  rtspUrl: z.string().trim().min(1),
  rtspUsername: z.string().trim().max(120).optional().nullable(),
  rtspPassword: z.string().trim().max(120).optional().nullable(),
  enabled: z.boolean().optional(),
});

cameraRoutes.get(
  "/cameras",
  asyncHandler(async (_req, res) => {
    res.json({
      cameras: await faceDetectionService.listCameras(),
    });
  }),
);

cameraRoutes.get(
  "/cameras/:cameraId",
  asyncHandler(async (req, res) => {
    const camera = await faceDetectionService.getCamera(String(req.params.cameraId ?? ""));
    if (!camera) {
      res.status(404).json({ error: "Camera not found" });
      return;
    }
    res.json({ camera });
  }),
);

cameraRoutes.post(
  "/cameras",
  asyncHandler(async (req, res) => {
    const parsed = cameraSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({
        error: "Invalid request body",
        issues: parsed.error.flatten(),
      });
      return;
    }

    const camera = await faceDetectionService.addCamera(parsed.data);
    res.status(201).json({ ok: true, camera });
  }),
);

cameraRoutes.put(
  "/cameras/:cameraId",
  asyncHandler(async (req, res) => {
    const parsed = cameraSchema.omit({ id: true }).safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({
        error: "Invalid request body",
        issues: parsed.error.flatten(),
      });
      return;
    }

    const camera = await faceDetectionService.updateCamera(String(req.params.cameraId ?? ""), parsed.data);
    res.json({ ok: true, camera });
  }),
);

cameraRoutes.delete(
  "/cameras/:cameraId",
  asyncHandler(async (req, res) => {
    const removed = await faceDetectionService.deleteCamera(String(req.params.cameraId ?? ""));
    res.json({ ok: true, removed });
  }),
);
