import { Router } from "express";
import { z } from "zod";
import { faceDetectionService } from "../services/faceDetectionService.js";
import { asyncHandler } from "../utils/asyncHandler.js";

export const detectionRoutes = Router();

const startSchema = z.object({
  cameraId: z.string().trim().min(1).optional(),
  cameraRole: z.enum(["general", "check_in", "check_out"]).optional(),
}).optional();

function formatBoundary(frame: Buffer): Buffer {
  return Buffer.from(
    `--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`,
  );
}

detectionRoutes.get("/status", (_req, res) => {
  res.json(faceDetectionService.getStatus());
});

detectionRoutes.post(
  "/start",
  asyncHandler(async (_req, res) => {
    const parsed = startSchema.safeParse(_req.body);
    await faceDetectionService.start(
      parsed.success ? parsed.data?.cameraId : undefined,
      parsed.success ? parsed.data?.cameraRole : undefined,
    );
    res.status(202).json(faceDetectionService.getStatus());
  }),
);

detectionRoutes.post(
  "/stop",
  asyncHandler(async (_req, res) => {
    await faceDetectionService.stop();
    res.json(faceDetectionService.getStatus());
  }),
);

detectionRoutes.get("/stream.mjpg", (req, res) => {
  const initialFrame = faceDetectionService.getLatestFrame();

  res.status(200);
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("Expires", "0");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("Content-Type", "multipart/x-mixed-replace; boundary=frame");

  if (initialFrame) {
    res.write(formatBoundary(initialFrame));
    res.write(initialFrame);
    res.write("\r\n");
  }

  const unsubscribe = faceDetectionService.onFrame((frame) => {
    if (res.writableEnded) {
      return;
    }

    res.write(formatBoundary(frame));
    res.write(frame);
    res.write("\r\n");
  });

  req.on("close", () => {
    unsubscribe();
    if (!res.writableEnded) {
      res.end();
    }
  });
});
