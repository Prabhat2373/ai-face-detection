import { mkdir } from "node:fs/promises";
import { EventEmitter } from "node:events";
import { env } from "../config/env.js";
import { DetectorWorkerClient } from "../detector/detectorWorkerClient.js";
import { RtspStream } from "../rtsp/rtspStream.js";
import { buildFaceDescriptor } from "../utils/faceDescriptor.js";
import { AttendanceService } from "./attendanceService.js";
import { FaceRegistryService } from "./faceRegistryService.js";
import { PythonRecognitionClient } from "./pythonRecognitionClient.js";
import { UpdateService } from "./updateService.js";
import { logger } from "../utils/logger.js";
export class FaceDetectionService {
    config;
    events = new EventEmitter();
    state = "idle";
    stream;
    detector;
    registry;
    attendance;
    pythonRecognizer;
    updater;
    activeCamera;
    attendanceSnapshot = [];
    latestFrame;
    latestDetectionFrame;
    startedAt;
    stoppedAt;
    lastError;
    lastWorkerState;
    lastDetection;
    lastFaces = [];
    detectionCount = 0;
    receivedFrames = 0;
    acceptedFrames = 0;
    detectionStride = 1;
    frameModulo = 0;
    registeredFacesCount = 0;
    pythonBusy = false;
    pythonDroppedFrames = 0;
    pythonProcessedFrames = 0;
    constructor(config = env) {
        this.config = config;
        this.registry = new FaceRegistryService(this.config.SNAPSHOT_PATH, this.config.MATCH_THRESHOLD, logger);
        this.attendance = new AttendanceService(this.config.SNAPSHOT_PATH, logger, this.config.DETECTION_COOLDOWN_MS);
        this.pythonRecognizer =
            this.config.RECOGNITION_BACKEND === "python"
                ? new PythonRecognitionClient(this.config.PYTHON_RECOGNIZER_URL)
                : undefined;
        this.updater = new UpdateService(this.config, logger);
    }
    getStatus() {
        return {
            state: this.state,
            startedAt: this.startedAt,
            stoppedAt: this.stoppedAt,
            lastError: this.lastError,
            lastWorkerState: this.lastWorkerState,
            lastDetection: this.lastDetection,
            detectionCount: this.detectionCount,
            frames: {
                received: this.receivedFrames,
                accepted: this.acceptedFrames,
                detector: this.detector?.status ??
                    (this.pythonRecognizer
                        ? {
                            ready: this.lastWorkerState !== "python recognizer unavailable",
                            busy: this.pythonBusy,
                            droppedFrames: this.pythonDroppedFrames,
                            processedFrames: this.pythonProcessedFrames,
                            lastWorkerState: this.lastWorkerState,
                        }
                        : null),
            },
            config: {
                snapshotPath: this.config.SNAPSHOT_PATH,
                detectionThreshold: this.config.DETECTION_THRESHOLD,
                matchThreshold: this.config.MATCH_THRESHOLD,
                frameRate: this.config.FRAME_RATE,
                streamFrameRate: this.config.STREAM_FRAME_RATE,
                cooldownMs: this.config.DETECTION_COOLDOWN_MS,
                recognitionBackend: this.config.RECOGNITION_BACKEND,
                pythonRecognizerUrl: this.config.RECOGNITION_BACKEND === "python"
                    ? this.config.PYTHON_RECOGNIZER_URL
                    : undefined,
            },
            stream: this.stream?.status ?? null,
            lastFaces: this.lastFaces,
            registeredFaces: this.registeredFacesCount,
            attendance: this.pythonRecognizer ? this.attendanceSnapshot : this.attendance.list(),
            update: this.updater.getStatus(),
        };
    }
    onFrame(listener) {
        this.events.on("frame", listener);
        return () => this.events.off("frame", listener);
    }
    getLatestFrame() {
        return this.latestFrame;
    }
    async listRegisteredFaces() {
        if (this.pythonRecognizer) {
            const faces = await this.pythonRecognizer.listFaces();
            this.registeredFacesCount = faces.length;
            return faces;
        }
        return this.registry.list();
    }
    async listCameras() {
        if (!this.pythonRecognizer) {
            return [];
        }
        return this.pythonRecognizer.listCameras();
    }
    async getCamera(cameraId) {
        if (!this.pythonRecognizer) {
            return null;
        }
        return this.pythonRecognizer.getCamera(cameraId);
    }
    async addCamera(camera) {
        if (!this.pythonRecognizer) {
            throw new Error("Camera management requires the Python backend.");
        }
        return this.pythonRecognizer.addCamera(camera);
    }
    async updateCamera(cameraId, camera) {
        if (!this.pythonRecognizer) {
            throw new Error("Camera management requires the Python backend.");
        }
        return this.pythonRecognizer.updateCamera(cameraId, camera);
    }
    async deleteCamera(cameraId) {
        if (!this.pythonRecognizer) {
            return false;
        }
        return this.pythonRecognizer.deleteCamera(cameraId);
    }
    async removeRegisteredFace(label) {
        if (this.pythonRecognizer) {
            const removed = await this.pythonRecognizer.removeFace(label);
            const faces = await this.pythonRecognizer.listFaces();
            this.registeredFacesCount = faces.length;
            return removed;
        }
        return this.registry.remove(label);
    }
    async clearRegisteredFaces() {
        if (this.pythonRecognizer) {
            await this.pythonRecognizer.clearFaces();
            this.registeredFacesCount = 0;
            await this.attendance.load();
            return;
        }
        await this.registry.clear();
        this.registeredFacesCount = this.registry.count;
        await this.attendance.load();
    }
    async exportAttendanceCsv() {
        if (this.pythonRecognizer) {
            return this.pythonRecognizer.exportAttendanceCsv();
        }
        return this.attendance.exportCsv();
    }
    getUpdateStatus() {
        return this.updater.getStatus();
    }
    async checkForUpdate() {
        return this.updater.checkOnce();
    }
    async registerFace(label) {
        if (this.pythonRecognizer) {
            const frame = this.latestDetectionFrame ?? this.latestFrame;
            if (!frame) {
                throw new Error("No camera frame is available yet.");
            }
            const registered = await this.pythonRecognizer.register(label, frame);
            this.registeredFacesCount += 1;
            return registered;
        }
        const deadline = Date.now() + 2500;
        const samples = [];
        const seenFrames = new Set();
        const collect = (faces) => {
            const frame = this.latestDetectionFrame ?? this.latestFrame;
            if (!frame || !faces.length) {
                return;
            }
            const primary = faces[0];
            if (!primary) {
                return;
            }
            const signature = `${Math.round(primary.box.x)}:${Math.round(primary.box.y)}:${Math.round(primary.box.width)}:${Math.round(primary.box.height)}`;
            const signatureHash = hashSignature(signature);
            if (seenFrames.has(signatureHash)) {
                return;
            }
            const descriptor = buildFaceDescriptor(frame, primary.box);
            if (!descriptor) {
                return;
            }
            seenFrames.add(signatureHash);
            samples.push(descriptor);
        };
        collect(this.lastFaces);
        if (samples.length < 3) {
            await new Promise((resolve, reject) => {
                const timer = setInterval(() => {
                    collect(this.lastFaces);
                    if (samples.length >= 3) {
                        cleanup();
                        resolve();
                    }
                    else if (Date.now() >= deadline) {
                        cleanup();
                        if (!samples.length) {
                            reject(new Error("No face found in the current frame."));
                        }
                        else {
                            resolve();
                        }
                    }
                }, 120);
                const cleanup = () => clearInterval(timer);
            });
        }
        if (!samples.length) {
            throw new Error("No face found in the current frame.");
        }
        const profile = await this.registry.register(label, samples);
        return {
            label: profile.label,
            sampleCount: profile.sampleCount,
            updatedAt: profile.updatedAt,
        };
    }
    async start(cameraId, cameraRole) {
        if (this.state === "running" || this.state === "starting") {
            return;
        }
        this.state = "starting";
        this.lastError = undefined;
        await mkdir(this.config.SNAPSHOT_PATH, { recursive: true });
        await this.registry.load();
        if (this.pythonRecognizer) {
            try {
                this.registeredFacesCount = (await this.pythonRecognizer.listFaces()).length;
                const camera = await this.resolveCamera(cameraId, cameraRole);
                this.activeCamera = camera;
                this.attendanceSnapshot = await this.pythonRecognizer.listAttendance();
                this.updater.start();
            }
            catch (error) {
                this.registeredFacesCount = 0;
                this.lastWorkerState = "python recognizer unavailable";
                logger.warn({ err: error }, "Python recognizer list request failed during startup");
                throw error;
            }
        }
        else {
            await this.attendance.load();
            await this.attendance.ensureFile();
            this.registeredFacesCount = this.registry.count;
            throw new Error("Camera DB mode requires the Python recognizer service.");
        }
        this.detectionStride = Math.max(1, Math.round(this.config.STREAM_FRAME_RATE / this.config.FRAME_RATE));
        this.frameModulo = 0;
        this.stream = new RtspStream({
            FFMPEG_PATH: this.config.FFMPEG_PATH,
            STREAM_FRAME_RATE: this.config.STREAM_FRAME_RATE,
            MAX_FRAME_BYTES: this.config.MAX_FRAME_BYTES,
            rtspUrl: this.activeCamera.rtsp_url,
            rtspUsername: this.activeCamera.rtsp_username,
            rtspPassword: this.activeCamera.rtsp_password,
        }, logger);
        this.stream.on("started", () => {
            this.state = "running";
            this.startedAt = new Date().toISOString();
            this.stoppedAt = undefined;
            logger.info("RTSP stream started");
        });
        this.stream.on("stopped", (code, signal) => {
            logger.info({ code, signal }, "RTSP stream stopped");
            if (this.state !== "stopping") {
                this.state = code === 0 || signal === "SIGTERM" ? "idle" : "error";
            }
        });
        this.stream.on("error", (error) => this.handleError(error));
        this.stream.on("frame", (frame) => {
            this.latestFrame = frame;
            this.events.emit("frame", frame);
            this.receivedFrames += 1;
            this.frameModulo = (this.frameModulo + 1) % this.detectionStride;
            if (this.frameModulo !== 0) {
                return;
            }
            if (this.pythonRecognizer) {
                if (this.pythonBusy) {
                    this.pythonDroppedFrames += 1;
                    return;
                }
                this.pythonBusy = true;
                this.latestDetectionFrame = Buffer.from(frame);
                this.acceptedFrames += 1;
                void this.handlePythonFrame(frame).finally(() => {
                    this.pythonBusy = false;
                });
                return;
            }
            if (this.detector?.detect(frame)) {
                this.latestDetectionFrame = Buffer.from(frame);
                this.acceptedFrames += 1;
            }
        });
        if (this.pythonRecognizer) {
            await this.waitForPythonRecognizerReady();
        }
        else {
            this.detector = new DetectorWorkerClient({
                threshold: this.config.DETECTION_THRESHOLD,
                snapshotPath: this.config.SNAPSHOT_PATH,
                cooldownMs: this.config.DETECTION_COOLDOWN_MS,
            }, logger);
            this.detector.on("ready", () => {
                logger.info("Detector worker ready");
            });
            this.detector.on("result", (faces) => {
                void this.handleDetectorResult(faces);
            });
            this.detector.on("state", (value) => {
                this.lastWorkerState = value;
                logger.info({ workerState: value }, "Detector worker state");
            });
            this.detector.on("detection", (snapshot, faces) => {
                this.lastDetection = snapshot;
                this.lastFaces = this.annotateFaces(faces);
                this.detectionCount += 1;
            });
            this.detector.on("error", (error) => this.handleError(error));
        }
        this.stream.start();
    }
    async stop() {
        if (this.state === "idle" || this.state === "stopping") {
            return;
        }
        this.state = "stopping";
        const stream = this.stream;
        const detector = this.detector;
        this.stream = undefined;
        this.detector = undefined;
        await stream?.stop();
        await detector?.shutdown();
        this.state = "idle";
        this.stoppedAt = new Date().toISOString();
        this.latestFrame = undefined;
        this.latestDetectionFrame = undefined;
        this.pythonBusy = false;
        this.updater.stop();
        logger.info("Face detection service stopped");
    }
    handleError(error) {
        this.lastError = error.message;
        this.state = "error";
        logger.error({ err: error }, "Face detection service error");
    }
    async handleDetectorResult(faces) {
        const frame = this.latestDetectionFrame ?? this.latestFrame;
        if (this.pythonRecognizer && frame) {
            try {
                this.lastFaces = await this.pythonRecognizer.recognize(frame, this.activeCamera?.camera_role, this.activeCamera?.id);
            }
            catch (error) {
                this.lastError = error instanceof Error ? error.message : String(error);
                this.lastWorkerState = "python recognizer error";
                logger.error({ err: error }, "Python recognizer failed");
                this.lastFaces = this.annotateFaces(faces);
            }
        }
        else {
            this.lastFaces = this.annotateFaces(faces);
        }
        this.events.emit("detection", this.lastFaces);
        for (const face of this.lastFaces) {
            if (face.match?.label) {
                await this.attendance.recordMatch(face.match.label, face.match.confidence, new Date(), this.config.DETECTION_COOLDOWN_MS);
            }
        }
    }
    async handlePythonFrame(frame) {
        try {
            this.lastWorkerState = "python recognizer processing";
            const response = await this.pythonRecognizer?.recognizeWithMeta(frame, this.activeCamera?.camera_role, this.activeCamera?.id);
            if (!response) {
                return;
            }
            this.pythonProcessedFrames += 1;
            this.lastWorkerState = response.state ?? "python recognizer ready";
            this.lastFaces = response.faces.map((face) => ({ ...face }));
            this.events.emit("detection", this.lastFaces);
            if (response.faces.length) {
                this.detectionCount += 1;
            }
            if (response.snapshot) {
                this.lastDetection = response.snapshot;
                logger.info({
                    timestamp: response.snapshot.timestamp,
                    confidence: response.snapshot.confidence,
                    snapshot: response.snapshot.path,
                }, "Face detected");
            }
            for (const face of this.lastFaces) {
                if (face.match?.label && this.pythonRecognizer) {
                    this.attendanceSnapshot = await this.pythonRecognizer.listAttendance();
                }
            }
        }
        catch (error) {
            this.lastError = error instanceof Error ? error.message : String(error);
            this.lastWorkerState = "python recognizer error";
            logger.error({ err: error }, "Python recognition failed");
        }
    }
    async waitForPythonRecognizerReady(timeoutMs = 30_000) {
        if (!this.pythonRecognizer) {
            return;
        }
        const startedAt = Date.now();
        while (Date.now() - startedAt < timeoutMs) {
            if (await this.pythonRecognizer.health()) {
                this.lastWorkerState = "python recognizer ready";
                return;
            }
            this.lastWorkerState = "python recognizer starting";
            await new Promise((resolve) => setTimeout(resolve, 1000));
        }
        this.lastWorkerState = "python recognizer unavailable";
        logger.warn("Python recognizer did not become ready before the timeout");
    }
    annotateFaces(faces) {
        const frame = this.latestDetectionFrame ?? this.latestFrame;
        if (!frame || !faces.length) {
            return faces;
        }
        return faces.map((face) => {
            const descriptor = buildFaceDescriptor(frame, face.box);
            const match = descriptor ? this.registry.match(descriptor) : null;
            return {
                ...face,
                match: match
                    ? {
                        label: match.label,
                        score: match.score,
                        confidence: match.confidence,
                        sampleCount: match.sampleCount,
                    }
                    : null,
            };
        });
    }
    async resolveCamera(cameraId, cameraRole) {
        if (!this.pythonRecognizer) {
            throw new Error("Python recognizer service is required for camera lookup.");
        }
        if (cameraRole) {
            const cameras = await this.pythonRecognizer.listCameras();
            const roleCamera = cameras.find((camera) => camera.enabled && camera.camera_role === cameraRole);
            if (!roleCamera) {
                throw new Error(`No enabled camera found for role: ${cameraRole}`);
            }
            return roleCamera;
        }
        if (cameraId) {
            const camera = await this.pythonRecognizer.getCamera(cameraId);
            if (!camera) {
                throw new Error(`Camera not found: ${cameraId}`);
            }
            if (!camera.enabled) {
                throw new Error(`Camera is disabled: ${cameraId}`);
            }
            return camera;
        }
        const cameras = await this.pythonRecognizer.listCameras();
        const active = cameras.find((camera) => Boolean(camera.enabled));
        if (!active) {
            throw new Error("No enabled cameras were found in the database.");
        }
        return active;
    }
}
export const faceDetectionService = new FaceDetectionService();
function hashSignature(value) {
    let hash = 0;
    for (let index = 0; index < value.length; index += 1) {
        hash = (hash * 31 + value.charCodeAt(index)) | 0;
    }
    return hash;
}
//# sourceMappingURL=faceDetectionService.js.map