import { Router } from "express";
import { faceDetectionService } from "../services/faceDetectionService.js";
import { asyncHandler } from "../utils/asyncHandler.js";

export const updateRoutes = Router();

updateRoutes.get(
  "/update/status",
  asyncHandler(async (_req, res) => {
    const status = faceDetectionService.getUpdateStatus?.() ?? null;
    res.json({ status });
  }),
);

updateRoutes.post(
  "/update/check",
  asyncHandler(async (_req, res) => {
    const status = await faceDetectionService.checkForUpdate?.();
    res.json({ status: status ?? null });
  }),
);
