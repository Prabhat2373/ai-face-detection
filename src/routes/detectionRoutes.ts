import { Router } from "express";
import { z } from "zod";
import { env } from "../config/env.js";
import { faceDetectionService } from "../services/faceDetectionService.js";
import { RtspStream } from "../rtsp/rtspStream.js";
import { logger } from "../utils/logger.js";
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

async function resolvePreviewCamera(cameraId?: string, cameraRole?: "general" | "check_in" | "check_out") {
  if (cameraRole) {
    const cameras = await faceDetectionService.listCameras();
    const camera = cameras.find((item) => item.enabled && item.camera_role === cameraRole);
    if (!camera) {
      throw new Error(`No enabled camera found for role: ${cameraRole}`);
    }
    return camera;
  }

  if (cameraId) {
    const camera = await faceDetectionService.getCamera(cameraId);
    if (!camera) {
      throw new Error(`Camera not found: ${cameraId}`);
    }
    if (!camera.enabled) {
      throw new Error(`Camera is disabled: ${cameraId}`);
    }
    return camera;
  }

  const cameras = await faceDetectionService.listCameras();
  const active = cameras.find((item) => item.enabled);
  if (!active) {
    throw new Error("No enabled cameras were found in the database.");
  }
  return active;
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
  const cameraId = typeof req.query.cameraId === "string" ? req.query.cameraId : undefined;
  const cameraRole =
    req.query.cameraRole === "check_in" ||
    req.query.cameraRole === "check_out" ||
    req.query.cameraRole === "general"
      ? req.query.cameraRole
      : undefined;

  let stream: RtspStream | undefined;
  let closed = false;

  res.status(200);
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("Expires", "0");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("Content-Type", "multipart/x-mixed-replace; boundary=frame");

  const shutdown = async () => {
    if (closed) {
      return;
    }
    closed = true;
    try {
      await stream?.stop();
    } catch {
      // ignore shutdown errors
    }
    if (!res.writableEnded) {
      res.end();
    }
  };

  void (async () => {
    try {
      const camera = await resolvePreviewCamera(cameraId, cameraRole);
      stream = new RtspStream(
        {
          FFMPEG_PATH: env.FFMPEG_PATH,
          STREAM_FRAME_RATE: env.STREAM_FRAME_RATE,
          MAX_FRAME_BYTES: env.MAX_FRAME_BYTES,
          rtspUrl: camera.rtsp_url,
          rtspUsername: camera.rtsp_username,
          rtspPassword: camera.rtsp_password,
        },
        logger,
      );

      stream.on("frame", (frame) => {
        if (res.writableEnded || closed) {
          return;
        }
        res.write(formatBoundary(frame));
        res.write(frame);
        res.write("\r\n");
      });

      stream.on("error", (error) => {
        logger.warn({ err: error, cameraId: camera.id }, "Preview stream error");
        void shutdown();
      });

      stream.start();
    } catch (error) {
      logger.warn({ err: error }, "Failed to start preview stream");
      res.status(404).json({
        error: error instanceof Error ? error.message : "Unable to start preview stream",
      });
    }
  })();

  req.on("close", () => {
    void shutdown();
  });
});
