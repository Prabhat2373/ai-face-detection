import { EventEmitter } from "node:events";
import type { DetectedFace, DetectionSnapshot, DetectorWorkerData } from "./types.js";
import type { logger } from "../utils/logger.js";
type DetectorClientEvents = {
    ready: [];
    detection: [DetectionSnapshot, DetectedFace[]];
    result: [DetectedFace[]];
    error: [Error];
    state: [string];
};
export declare interface DetectorWorkerClient {
    on<K extends keyof DetectorClientEvents>(event: K, listener: (...args: DetectorClientEvents[K]) => void): this;
    emit<K extends keyof DetectorClientEvents>(event: K, ...args: DetectorClientEvents[K]): boolean;
}
export declare class DetectorWorkerClient extends EventEmitter {
    private readonly log;
    private readonly worker;
    private busy;
    private ready;
    private frameId;
    private droppedFrames;
    private processedFrames;
    private lastWorkerState?;
    constructor(workerData: DetectorWorkerData, log: typeof logger);
    get status(): {
        ready: boolean;
        busy: boolean;
        droppedFrames: number;
        processedFrames: number;
        lastWorkerState: string | undefined;
    };
    detect(frame: Buffer, capturedAt?: Date): boolean;
    shutdown(): Promise<void>;
    private handleMessage;
}
export {};
