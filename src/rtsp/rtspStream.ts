import { spawn, type ChildProcessByStdio } from "node:child_process";
import { EventEmitter } from "node:events";
import type { Readable } from "node:stream";
import { JpegFrameExtractor } from "./jpegFrameExtractor.js";
import type { AppEnv } from "../config/env.js";
import type { logger } from "../utils/logger.js";

type RtspStreamEvents = {
  frame: [Buffer];
  started: [];
  stopped: [number | null, NodeJS.Signals | null];
  error: [Error];
  state: [string];
};

export declare interface RtspStream {
  on<K extends keyof RtspStreamEvents>(
    event: K,
    listener: (...args: RtspStreamEvents[K]) => void,
  ): this;
  emit<K extends keyof RtspStreamEvents>(
    event: K,
    ...args: RtspStreamEvents[K]
  ): boolean;
}

export class RtspStream extends EventEmitter {
  private ffmpeg?: ChildProcessByStdio<null, Readable, Readable>;
  private readonly extractor: JpegFrameExtractor;
  private lastState?: string;

  public constructor(
    private readonly config: Pick<
      AppEnv,
      "FFMPEG_PATH" | "STREAM_FRAME_RATE" | "MAX_FRAME_BYTES"
    > & {
      rtspUrl: string;
      rtspUsername?: string | null;
      rtspPassword?: string | null;
    },
    private readonly log: typeof logger,
  ) {
    super();
    this.extractor = new JpegFrameExtractor(config.MAX_FRAME_BYTES);
    this.extractor.on("frame", (frame) => this.emit("frame", frame));
    this.extractor.on("warning", (error) => this.log.warn({ err: error }, error.message));
  }

  public get running(): boolean {
    return Boolean(this.ffmpeg && !this.ffmpeg.killed);
  }

  public get status() {
    return {
      running: this.running,
      lastState: this.lastState,
    };
  }

  public start(): void {
    if (this.running) {
      return;
    }

    const streamUrl = this.buildRtspUrl();
    const args = [
      "-hide_banner",
      "-loglevel",
      "warning",
      "-rtsp_transport",
      "tcp",
      "-i",
      streamUrl,
      "-an",
      "-vf",
      `fps=${this.config.STREAM_FRAME_RATE}`,
      "-q:v",
      "4",
      "-f",
      "image2pipe",
      "-vcodec",
      "mjpeg",
      "pipe:1",
    ];

    this.lastState = "spawning ffmpeg";
    this.emit("state", this.lastState);
    this.log.info({ args: this.safeArgs(args) }, "Starting FFmpeg RTSP stream");
    this.ffmpeg = spawn(this.config.FFMPEG_PATH, args, {
      stdio: ["ignore", "pipe", "pipe"],
    });

    this.ffmpeg.stdout.on("data", (chunk: Buffer) => this.extractor.push(chunk));
    this.ffmpeg.stderr.on("data", (chunk: Buffer) => {
      const message = chunk.toString("utf8").trim();
      if (message.length > 0) {
        this.lastState = message;
        this.emit("state", message);
        this.log.warn({ ffmpeg: message }, "FFmpeg warning");
      }
    });
    this.ffmpeg.on("error", (error) => this.emit("error", error));
    this.ffmpeg.on("spawn", () => {
      this.lastState = "ffmpeg spawned";
      this.emit("state", this.lastState);
      this.emit("started");
    });
    this.ffmpeg.on("close", (code, signal) => {
      this.extractor.reset();
      this.ffmpeg = undefined;
      this.lastState = `ffmpeg closed (${code ?? "null"}, ${signal ?? "null"})`;
      this.emit("state", this.lastState);
      this.emit("stopped", code, signal);
    });
  }

  public async stop(timeoutMs = 5_000): Promise<void> {
    const ffmpeg = this.ffmpeg;
    if (!ffmpeg) {
      return;
    }

    await new Promise<void>((resolve) => {
      const timeout = setTimeout(() => {
        if (!ffmpeg.killed) {
          ffmpeg.kill("SIGKILL");
        }
      }, timeoutMs);

      ffmpeg.once("close", () => {
        clearTimeout(timeout);
        resolve();
      });

      ffmpeg.kill("SIGTERM");
    });
  }

  private safeArgs(args: string[]): string[] {
    const rawUrl = this.config.rtspUrl;
    const authenticatedUrl = this.buildRtspUrl();
    return args.map((arg) =>
      arg === rawUrl || arg === authenticatedUrl ? "[RTSP_URL]" : arg,
    );
  }

  private buildRtspUrl(): string {
    try {
      const url = new URL(this.config.rtspUrl);
      const username = this.config.rtspUsername?.trim();
      const password = this.config.rtspPassword?.trim();

      if (username) {
        url.username = encodeURIComponent(username);
      }
      if (password) {
        url.password = encodeURIComponent(password);
      }

      return url.toString();
    } catch {
      return this.config.rtspUrl;
    }
  }
}
