import { EventEmitter } from "node:events";
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
    on<K extends keyof RtspStreamEvents>(event: K, listener: (...args: RtspStreamEvents[K]) => void): this;
    emit<K extends keyof RtspStreamEvents>(event: K, ...args: RtspStreamEvents[K]): boolean;
}
export declare class RtspStream extends EventEmitter {
    private readonly config;
    private readonly log;
    private ffmpeg?;
    private readonly extractor;
    private lastState?;
    constructor(config: Pick<AppEnv, "RTSP_URL" | "FFMPEG_PATH" | "STREAM_FRAME_RATE" | "MAX_FRAME_BYTES">, log: typeof logger);
    get running(): boolean;
    get status(): {
        running: boolean;
        lastState: string | undefined;
    };
    start(): void;
    stop(timeoutMs?: number): Promise<void>;
    private safeArgs;
    private buildRtspUrl;
}
export {};
