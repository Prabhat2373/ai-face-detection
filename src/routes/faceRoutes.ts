import { Router } from "express";
import { z } from "zod";
import { faceDetectionService } from "../services/faceDetectionService.js";
import { asyncHandler } from "../utils/asyncHandler.js";

export const faceRoutes = Router();

const registerSchema = z.object({
  label: z.string().trim().min(1).max(80),
});

faceRoutes.get("/faces", asyncHandler(async (_req, res) => {
  res.json({
    faces: await faceDetectionService.listRegisteredFaces(),
  });
}));

faceRoutes.get("/attendance", asyncHandler(async (_req, res) => {
  res.json({
    attendance: faceDetectionService.getStatus().attendance,
  });
}));

faceRoutes.get("/attendance.csv", asyncHandler(async (_req, res) => {
  const csv = await faceDetectionService.exportAttendanceCsv();
  res.status(200);
  res.setHeader("Content-Type", "text/csv; charset=utf-8");
  res.setHeader("Content-Disposition", 'attachment; filename="attendance.csv"');
  res.send(csv);
}));

faceRoutes.post(
  "/faces/register",
  asyncHandler(async (req, res) => {
    const parsed = registerSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({
        error: "Invalid request body",
        issues: parsed.error.flatten(),
      });
      return;
    }

    const registered = await faceDetectionService.registerFace(parsed.data.label);
    res.status(201).json({
      ok: true,
      face: registered,
      status: faceDetectionService.getStatus(),
    });
  }),
);

faceRoutes.delete(
  "/faces/:label",
  asyncHandler(async (req, res) => {
    const label = String(req.params.label ?? "").trim();
    if (!label) {
      res.status(400).json({ error: "Label is required" });
      return;
    }
    const removed = await faceDetectionService.removeRegisteredFace(label);
    res.json({ ok: true, removed });
  }),
);

faceRoutes.post(
  "/faces/clear",
  asyncHandler(async (_req, res) => {
    await faceDetectionService.clearRegisteredFaces();
    res.json({ ok: true });
  }),
);
