import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { Worker } from "node:worker_threads";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type {
  DetectedFace,
  DetectionSnapshot,
  DetectorWorkerData,
  DetectorWorkerRequest,
  DetectorWorkerResponse,
} from "./types.js";
import type { logger } from "../utils/logger.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const tsWorkerPath = join(__dirname, "../workers/faceDetectorWorker.ts");
const jsWorkerPath = join(__dirname, "../workers/faceDetectorWorker.js");
const workerPath = existsSync(tsWorkerPath) ? tsWorkerPath : jsWorkerPath;

type DetectorClientEvents = {
  ready: [];
  detection: [DetectionSnapshot, DetectedFace[]];
  result: [DetectedFace[]];
  error: [Error];
  state: [string];
};

export declare interface DetectorWorkerClient {
  on<K extends keyof DetectorClientEvents>(
    event: K,
    listener: (...args: DetectorClientEvents[K]) => void,
  ): this;
  emit<K extends keyof DetectorClientEvents>(
    event: K,
    ...args: DetectorClientEvents[K]
  ): boolean;
}

export class DetectorWorkerClient extends EventEmitter {
  private readonly worker: Worker;
  private busy = false;
  private ready = false;
  private frameId = 0;
  private droppedFrames = 0;
  private processedFrames = 0;
  private lastWorkerState?: string;

  public constructor(workerData: DetectorWorkerData, private readonly log: typeof logger) {
    super();
    this.worker = new Worker(workerPath, {
      workerData,
    });

    this.worker.on("message", (message: DetectorWorkerResponse) => this.handleMessage(message));
    this.worker.on("messageerror", (error) => {
      this.emit("error", error instanceof Error ? error : new Error(String(error)));
    });
    this.worker.on("error", (error) => this.emit("error", error));
    this.worker.on("exit", (code) => {
      this.ready = false;
      if (code !== 0) {
        this.emit("error", new Error(`Detector worker exited with code ${code}`));
      }
    });
  }

  public get status() {
    return {
      ready: this.ready,
      busy: this.busy,
      droppedFrames: this.droppedFrames,
      processedFrames: this.processedFrames,
      lastWorkerState: this.lastWorkerState,
    };
  }

  public detect(frame: Buffer, capturedAt = new Date()): boolean {
    if (!this.ready || this.busy) {
      this.droppedFrames += 1;
      return false;
    }

    this.busy = true;
    const frameId = ++this.frameId;
    const jpeg = new ArrayBuffer(frame.byteLength);
    new Uint8Array(jpeg).set(frame);
    const request: DetectorWorkerRequest = {
      type: "detect",
      frameId,
      capturedAt: capturedAt.toISOString(),
      jpeg,
    };

    this.worker.postMessage(request, [request.jpeg]);
    return true;
  }

  public async shutdown(): Promise<void> {
    this.worker.postMessage({ type: "shutdown" } satisfies DetectorWorkerRequest);
    await this.worker.terminate();
  }

  private handleMessage(message: DetectorWorkerResponse): void {
    if (message.type === "state") {
      this.lastWorkerState = message.value;
      this.emit("state", message.value);
      return;
    }

    if (message.type === "ready") {
      this.ready = true;
      this.emit("ready");
      return;
    }

    if (message.type === "error") {
      this.busy = false;
      const error = new Error(message.message);
      error.stack = message.stack;
      this.emit("error", error);
      return;
    }

    this.busy = false;
    this.processedFrames += 1;
    this.emit("result", message.faces);

    if (message.snapshot) {
      this.log.info(
        {
          timestamp: message.snapshot.timestamp,
          confidence: message.snapshot.confidence,
          snapshot: message.snapshot.path,
        },
        "Face detected",
      );
      this.emit("detection", message.snapshot, message.faces);
    }
  }
}
