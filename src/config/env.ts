import dotenv from "dotenv";
import { z } from "zod";

dotenv.config();

const envSchema = z.object({
  NODE_ENV: z.string().default("development"),
  PORT: z.coerce.number().int().positive().default(3000),
  SNAPSHOT_PATH: z.string().min(1).default("./snapshots"),
  DETECTION_THRESHOLD: z.coerce.number().min(0).max(1).default(0.75),
  MATCH_THRESHOLD: z.coerce.number().min(0).max(1).default(0.45),
  RECOGNITION_BACKEND: z.enum(["node", "python"]).default("node"),
  PYTHON_RECOGNIZER_URL: z.string().url().default("http://localhost:5055"),
  PYTHON_DB_PATH: z.string().default("/app/data/app.db"),
  DEFAULT_TENANT_ID: z.string().default("default"),
  LICENSE_FILE: z.string().default("./data/license.json"),
  LICENSE_SECRET: z.string().optional().default(""),
  ALLOW_UNLICENSED_SETUP: z.coerce.boolean().default(true),
  AUTO_START_DETECTION: z.coerce.boolean().default(true),
  AGENT_VERSION: z.string().default("0.1.0"),
  AUTO_UPDATE_URL: z.string().url().optional(),
  AUTO_UPDATE_INTERVAL_MS: z.coerce.number().int().positive().default(60_000),
  LOG_LEVEL: z.string().default("info"),
  FFMPEG_PATH: z.string().default("ffmpeg"),
  STREAM_FRAME_RATE: z.coerce.number().positive().default(10),
  FRAME_RATE: z.coerce.number().positive().default(2),
  DETECTION_COOLDOWN_MS: z.coerce.number().int().positive().default(10_000),
  MAX_FRAME_BYTES: z.coerce.number().int().positive().default(6 * 1024 * 1024),
});

export const env = envSchema.parse(process.env);

export type AppEnv = typeof env;
