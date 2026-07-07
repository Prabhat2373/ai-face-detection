import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { JpegFrameExtractor } from "./jpegFrameExtractor.js";
export class RtspStream extends EventEmitter {
    config;
    log;
    ffmpeg;
    extractor;
    lastState;
    constructor(config, log) {
        super();
        this.config = config;
        this.log = log;
        this.extractor = new JpegFrameExtractor(config.MAX_FRAME_BYTES);
        this.extractor.on("frame", (frame) => this.emit("frame", frame));
        this.extractor.on("warning", (error) => this.log.warn({ err: error }, error.message));
    }
    get running() {
        return Boolean(this.ffmpeg && !this.ffmpeg.killed);
    }
    get status() {
        return {
            running: this.running,
            lastState: this.lastState,
        };
    }
    start() {
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
        this.ffmpeg.stdout.on("data", (chunk) => this.extractor.push(chunk));
        this.ffmpeg.stderr.on("data", (chunk) => {
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
    async stop(timeoutMs = 5_000) {
        const ffmpeg = this.ffmpeg;
        if (!ffmpeg) {
            return;
        }
        await new Promise((resolve) => {
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
    safeArgs(args) {
        const rawUrl = this.config.RTSP_URL;
        const authenticatedUrl = this.buildRtspUrl();
        return args.map((arg) => arg === rawUrl || arg === authenticatedUrl ? "[RTSP_URL]" : arg);
    }
    buildRtspUrl() {
        try {
            const url = new URL(this.config.RTSP_URL);
            const username = process.env.RTSP_USERNAME?.trim();
            const password = process.env.RTSP_PASSWORD?.trim();
            if (username) {
                url.username = encodeURIComponent(username);
            }
            if (password) {
                url.password = encodeURIComponent(password);
            }
            return url.toString();
        }
        catch {
            return this.config.RTSP_URL;
        }
    }
}
//# sourceMappingURL=rtspStream.js.map