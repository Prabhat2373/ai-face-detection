import dotenv from "dotenv";
import { z } from "zod";

dotenv.config();

const envSchema = z.object({
  NODE_ENV: z.string().default("development"),
  PORT: z.coerce.number().int().positive().default(3000),
  RTSP_URL: z.string().min(1, "RTSP_URL is required"),
  RTSP_USERNAME: z.string().optional(),
  RTSP_PASSWORD: z.string().optional(),
  SNAPSHOT_PATH: z.string().min(1).default("./snapshots"),
  DETECTION_THRESHOLD: z.coerce.number().min(0).max(1).default(0.75),
  MATCH_THRESHOLD: z.coerce.number().min(0).max(1).default(0.45),
  RECOGNITION_BACKEND: z.enum(["node", "python"]).default("node"),
  PYTHON_RECOGNIZER_URL: z.string().url().default("http://localhost:5055"),
  LOG_LEVEL: z.string().default("info"),
  FFMPEG_PATH: z.string().default("ffmpeg"),
  STREAM_FRAME_RATE: z.coerce.number().positive().default(10),
  FRAME_RATE: z.coerce.number().positive().default(2),
  DETECTION_COOLDOWN_MS: z.coerce.number().int().positive().default(10_000),
  MAX_FRAME_BYTES: z.coerce.number().int().positive().default(6 * 1024 * 1024),
});

export const env = envSchema.parse(process.env);

export type AppEnv = typeof env;
