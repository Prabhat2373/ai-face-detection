import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { Worker } from "node:worker_threads";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const tsWorkerPath = join(__dirname, "../workers/faceDetectorWorker.ts");
const jsWorkerPath = join(__dirname, "../workers/faceDetectorWorker.js");
const workerPath = existsSync(tsWorkerPath) ? tsWorkerPath : jsWorkerPath;
export class DetectorWorkerClient extends EventEmitter {
    log;
    worker;
    busy = false;
    ready = false;
    frameId = 0;
    droppedFrames = 0;
    processedFrames = 0;
    lastWorkerState;
    constructor(workerData, log) {
        super();
        this.log = log;
        this.worker = new Worker(workerPath, {
            workerData,
        });
        this.worker.on("message", (message) => this.handleMessage(message));
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
    get status() {
        return {
            ready: this.ready,
            busy: this.busy,
            droppedFrames: this.droppedFrames,
            processedFrames: this.processedFrames,
            lastWorkerState: this.lastWorkerState,
        };
    }
    detect(frame, capturedAt = new Date()) {
        if (!this.ready || this.busy) {
            this.droppedFrames += 1;
            return false;
        }
        this.busy = true;
        const frameId = ++this.frameId;
        const jpeg = new ArrayBuffer(frame.byteLength);
        new Uint8Array(jpeg).set(frame);
        const request = {
            type: "detect",
            frameId,
            capturedAt: capturedAt.toISOString(),
            jpeg,
        };
        this.worker.postMessage(request, [request.jpeg]);
        return true;
    }
    async shutdown() {
        this.worker.postMessage({ type: "shutdown" });
        await this.worker.terminate();
    }
    handleMessage(message) {
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
            this.log.info({
                timestamp: message.snapshot.timestamp,
                confidence: message.snapshot.confidence,
                snapshot: message.snapshot.path,
            }, "Face detected");
            this.emit("detection", message.snapshot, message.faces);
        }
    }
}
//# sourceMappingURL=detectorWorkerClient.js.map