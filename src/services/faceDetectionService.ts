import { mkdir } from "node:fs/promises";
import { EventEmitter } from "node:events";
import { env, type AppEnv } from "../config/env.js";
import { DetectorWorkerClient } from "../detector/detectorWorkerClient.js";
import type { DetectedFace, DetectionSnapshot } from "../detector/types.js";
import { RtspStream } from "../rtsp/rtspStream.js";
import { buildFaceDescriptor } from "../utils/faceDescriptor.js";
import { AttendanceService } from "./attendanceService.js";
import { FaceRegistryService } from "./faceRegistryService.js";
import { PythonRecognitionClient } from "./pythonRecognitionClient.js";
import { UpdateService } from "./updateService.js";
import { logger } from "../utils/logger.js";

type ServiceState = "idle" | "starting" | "running" | "stopping" | "error";

type CameraConfig = {
  id: string;
  name: string;
  camera_role?: "general" | "check_in" | "check_out";
  rtsp_url: string;
  rtsp_username?: string | null;
  rtsp_password?: string | null;
  enabled: number;
};

type CameraSession = {
  camera: CameraConfig;
  stream: RtspStream;
  pythonBusy: boolean;
  pythonDroppedFrames: number;
  pythonProcessedFrames: number;
  frameModulo: number;
  lastFaces: DetectedFace[];
  lastDetection?: DetectionSnapshot;
};

export class FaceDetectionService {
  private readonly events = new EventEmitter();
  private state: ServiceState = "idle";
  private stream?: RtspStream;
  private detector?: DetectorWorkerClient;
  private readonly registry: FaceRegistryService;
  private readonly attendance: AttendanceService;
  private readonly cameraClient?: PythonRecognitionClient;
  private readonly pythonRecognizer?: PythonRecognitionClient;
  private readonly updater: UpdateService;
  private activeCamera?: CameraConfig;
  private readonly cameraSessions = new Map<string, CameraSession>();
  private attendanceSnapshot: Array<{
    label: string;
    first_appearance: string;
    last_appearance: string;
    appearances: number;
    max_confidence: number;
  }> = [];
  private latestFrame?: Buffer;
  private latestDetectionFrame?: Buffer;
  private startedAt?: string;
  private stoppedAt?: string;
  private lastError?: string;
  private lastWorkerState?: string;
  private lastDetection?: DetectionSnapshot;
  private lastFaces: DetectedFace[] = [];
  private detectionCount = 0;
  private receivedFrames = 0;
  private acceptedFrames = 0;
  private detectionStride = 1;
  private frameModulo = 0;
  private registeredFacesCount = 0;

  public constructor(private readonly config: AppEnv = env) {
    this.registry = new FaceRegistryService(
      this.config.SNAPSHOT_PATH,
      this.config.MATCH_THRESHOLD,
      logger,
    );
    this.attendance = new AttendanceService(
      this.config.SNAPSHOT_PATH,
      logger,
      this.config.DETECTION_COOLDOWN_MS,
    );
    this.cameraClient = this.config.PYTHON_RECOGNIZER_URL
      ? new PythonRecognitionClient(this.config.PYTHON_RECOGNIZER_URL)
      : undefined;
    this.pythonRecognizer =
      this.config.RECOGNITION_BACKEND === "python"
        ? new PythonRecognitionClient(this.config.PYTHON_RECOGNIZER_URL)
        : undefined;
    this.updater = new UpdateService(this.config, logger);
  }

  public getStatus() {
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
        detector:
          this.detector?.status ??
          (this.pythonRecognizer
            ? {
                ready: this.lastWorkerState !== "python recognizer unavailable",
                busy: [...this.cameraSessions.values()].some((session) => session.pythonBusy),
                droppedFrames: [...this.cameraSessions.values()].reduce((total, session) => total + session.pythonDroppedFrames, 0),
                processedFrames: [...this.cameraSessions.values()].reduce((total, session) => total + session.pythonProcessedFrames, 0),
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
        pythonRecognizerUrl:
          this.config.RECOGNITION_BACKEND === "python"
            ? this.config.PYTHON_RECOGNIZER_URL
            : undefined,
      },
      stream: this.stream?.status ?? null,
      lastFaces: this.lastFaces,
      registeredFaces: this.registeredFacesCount,
      attendance: this.pythonRecognizer ? this.attendanceSnapshot : this.attendance.list(),
      cameras: [...this.cameraSessions.values()].map((session) => ({
        id: session.camera.id,
        name: session.camera.name,
        role: session.camera.camera_role ?? "general",
        stream: session.stream.status,
        busy: session.pythonBusy,
        processedFrames: session.pythonProcessedFrames,
        droppedFrames: session.pythonDroppedFrames,
        lastFaces: session.lastFaces,
        lastDetection: session.lastDetection,
      })),
      update: this.updater.getStatus(),
    };
  }

  public onFrame(listener: (frame: Buffer) => void): () => void {
    this.events.on("frame", listener);
    return () => this.events.off("frame", listener);
  }

  public getLatestFrame(): Buffer | undefined {
    return this.latestFrame;
  }

  public async listRegisteredFaces() {
    if (this.pythonRecognizer) {
      const faces = await this.pythonRecognizer.listFaces();
      this.registeredFacesCount = faces.length;
      return faces;
    }
    return this.registry.list();
  }

  public async listCameras() {
    if (!this.cameraClient) {
      return [];
    }
    return this.cameraClient.listCameras();
  }

  public async getCamera(cameraId: string) {
    if (!this.cameraClient) {
      return null;
    }
    return this.cameraClient.getCamera(cameraId);
  }

  public async addCamera(camera: {
    id?: string;
    name: string;
    cameraRole?: "general" | "check_in" | "check_out";
    rtspUrl: string;
    rtspUsername?: string | null;
    rtspPassword?: string | null;
    enabled?: boolean;
  }) {
    if (!this.cameraClient) {
      throw new Error("Camera management requires the Python backend.");
    }
    return this.cameraClient.addCamera(camera);
  }

  public async updateCamera(
    cameraId: string,
    camera: {
      name: string;
      cameraRole?: "general" | "check_in" | "check_out";
      rtspUrl: string;
      rtspUsername?: string | null;
      rtspPassword?: string | null;
      enabled?: boolean;
    },
  ) {
    if (!this.cameraClient) {
      throw new Error("Camera management requires the Python backend.");
    }
    return this.cameraClient.updateCamera(cameraId, camera);
  }

  public async deleteCamera(cameraId: string): Promise<boolean> {
    if (!this.cameraClient) {
      return false;
    }
    return this.cameraClient.deleteCamera(cameraId);
  }

  public async removeRegisteredFace(label: string): Promise<boolean> {
    if (this.pythonRecognizer) {
      const removed = await this.pythonRecognizer.removeFace(label);
      const faces = await this.pythonRecognizer.listFaces();
      this.registeredFacesCount = faces.length;
      return removed;
    }
    return this.registry.remove(label);
  }

  public async clearRegisteredFaces(): Promise<void> {
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

  public async exportAttendanceCsv(): Promise<string> {
    if (this.pythonRecognizer) {
      return this.pythonRecognizer.exportAttendanceCsv();
    }
    return this.attendance.exportCsv();
  }

  public getUpdateStatus() {
    return this.updater.getStatus();
  }

  public async checkForUpdate() {
    return this.updater.checkOnce();
  }

  public async registerFace(label: string): Promise<{
    label: string;
    sampleCount: number;
    updatedAt: string;
  }> {
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
    const samples: Float32Array[] = [];
    const seenFrames = new Set<number>();

    const collect = (faces: DetectedFace[]) => {
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
      await new Promise<void>((resolve, reject) => {
        const timer = setInterval(() => {
          collect(this.lastFaces);
          if (samples.length >= 3) {
            cleanup();
            resolve();
          } else if (Date.now() >= deadline) {
            cleanup();
            if (!samples.length) {
              reject(new Error("No face found in the current frame."));
            } else {
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

  public async start(cameraId?: string, cameraRole?: "general" | "check_in" | "check_out"): Promise<void> {
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
        this.attendanceSnapshot = await this.pythonRecognizer.listAttendance();
        this.updater.start();
        await this.startCameraSessions(cameraId, cameraRole);
      } catch (error) {
        this.registeredFacesCount = 0;
        this.lastWorkerState = "python recognizer unavailable";
        logger.warn({ err: error }, "Python recognizer list request failed during startup");
        throw error;
      }
    } else {
      await this.attendance.load();
      await this.attendance.ensureFile();
      this.registeredFacesCount = this.registry.count;
      throw new Error("Camera DB mode requires the Python recognizer service.");
    }

    this.detectionStride = Math.max(
      1,
      Math.round(this.config.STREAM_FRAME_RATE / this.config.FRAME_RATE),
    );
    this.frameModulo = 0;

    if (!this.pythonRecognizer) {
      this.stream = undefined;
      this.detector = new DetectorWorkerClient(
        {
          threshold: this.config.DETECTION_THRESHOLD,
          snapshotPath: this.config.SNAPSHOT_PATH,
          cooldownMs: this.config.DETECTION_COOLDOWN_MS,
        },
        logger,
      );

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
  }

  public async stop(): Promise<void> {
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
    await this.stopCameraSessions();

    this.state = "idle";
    this.stoppedAt = new Date().toISOString();
    this.latestFrame = undefined;
    this.latestDetectionFrame = undefined;
    this.updater.stop();
    logger.info("Face detection service stopped");
  }

  private handleError(error: Error): void {
    this.lastError = error.message;
    this.state = "error";
    logger.error({ err: error }, "Face detection service error");
  }

  private async handleDetectorResult(faces: DetectedFace[]): Promise<void> {
    const frame = this.latestDetectionFrame ?? this.latestFrame;
    if (this.pythonRecognizer && frame) {
      try {
        this.lastFaces = await this.pythonRecognizer.recognize(
          frame,
          this.activeCamera?.camera_role,
          this.activeCamera?.id,
        );
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : String(error);
        this.lastWorkerState = "python recognizer error";
        logger.error({ err: error }, "Python recognizer failed");
        this.lastFaces = this.annotateFaces(faces);
      }
    } else {
      this.lastFaces = this.annotateFaces(faces);
    }

    this.events.emit("detection", this.lastFaces);
    for (const face of this.lastFaces) {
      if (face.match?.label) {
        await this.attendance.recordMatch(
          face.match.label,
          face.match.confidence,
          new Date(),
          this.config.DETECTION_COOLDOWN_MS,
        );
      }
    }
  }

  private async handlePythonFrame(frame: Buffer, camera: CameraConfig, session: CameraSession): Promise<void> {
    try {
      this.lastWorkerState = "python recognizer processing";
      const response = await this.pythonRecognizer?.recognizeWithMeta(
        frame,
        camera.camera_role,
        camera.id,
      );
      if (!response) {
        return;
      }

      session.pythonProcessedFrames += 1;
      this.lastWorkerState = response.state ?? "python recognizer ready";
      session.lastFaces = response.faces.map((face) => ({ ...face }));
      this.lastFaces = session.lastFaces;
      this.events.emit("detection", this.lastFaces);

      if (response.faces.length) {
        this.detectionCount += 1;
      }

      if (response.snapshot) {
        this.lastDetection = response.snapshot;
        session.lastDetection = response.snapshot;
        logger.info(
          {
            timestamp: response.snapshot.timestamp,
            confidence: response.snapshot.confidence,
            snapshot: response.snapshot.path,
            cameraId: camera.id,
            cameraRole: camera.camera_role,
          },
          "Face detected",
        );
      }

      for (const face of this.lastFaces) {
        if (face.match?.label && this.pythonRecognizer) {
          this.attendanceSnapshot = await this.pythonRecognizer.listAttendance();
        }
      }
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      this.lastWorkerState = "python recognizer error";
      logger.error({ err: error }, "Python recognition failed");
    }
  }

  private async waitForPythonRecognizerReady(timeoutMs = 30_000): Promise<void> {
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

  private async startCameraSessions(
    cameraId?: string,
    cameraRole?: "general" | "check_in" | "check_out",
  ): Promise<void> {
    if (!this.pythonRecognizer) {
      return;
    }

    const cameras = await this.resolveCameras(cameraId, cameraRole);
    await this.stopCameraSessions();

    for (const camera of cameras) {
      const stream = new RtspStream(
        {
          FFMPEG_PATH: this.config.FFMPEG_PATH,
          STREAM_FRAME_RATE: this.config.STREAM_FRAME_RATE,
          MAX_FRAME_BYTES: this.config.MAX_FRAME_BYTES,
          rtspUrl: camera.rtsp_url,
          rtspUsername: camera.rtsp_username,
          rtspPassword: camera.rtsp_password,
        },
        logger,
      );

      const session: CameraSession = {
        camera,
        stream,
        pythonBusy: false,
        pythonDroppedFrames: 0,
        pythonProcessedFrames: 0,
        frameModulo: 0,
        lastFaces: [],
      };

      stream.on("started", () => {
        this.state = "running";
        this.startedAt = new Date().toISOString();
        this.stoppedAt = undefined;
        logger.info({ cameraId: camera.id, cameraRole: camera.camera_role }, "Camera stream started");
      });

      stream.on("stopped", (code, signal) => {
        logger.info({ code, signal, cameraId: camera.id }, "Camera stream stopped");
        this.cameraSessions.delete(camera.id);
        if (this.state !== "stopping" && this.cameraSessions.size === 0) {
          this.state = code === 0 || signal === "SIGTERM" ? "idle" : "error";
        }
      });

      stream.on("error", (error) => this.handleError(error));
      stream.on("frame", (frame) => {
        this.latestFrame = frame;
        this.events.emit("frame", frame);
        this.receivedFrames += 1;

        session.frameModulo = (session.frameModulo + 1) % this.detectionStride;
        if (session.frameModulo !== 0) {
          return;
        }

        if (!this.pythonRecognizer) {
          return;
        }

        if (session.pythonBusy) {
          session.pythonDroppedFrames += 1;
          return;
        }

        session.pythonBusy = true;
        this.latestDetectionFrame = Buffer.from(frame);
        this.acceptedFrames += 1;
        void this.handlePythonFrame(frame, camera, session).finally(() => {
          session.pythonBusy = false;
        });
      });

      this.cameraSessions.set(camera.id, session);
      stream.start();
    }

    if (this.cameraSessions.size === 0) {
      throw new Error("No enabled cameras were found in the database.");
    }

    await this.waitForPythonRecognizerReady();
  }

  private async stopCameraSessions(): Promise<void> {
    const sessions = [...this.cameraSessions.values()];
    this.cameraSessions.clear();
    await Promise.allSettled(sessions.map((session) => session.stream.stop()));
  }

  private annotateFaces(faces: DetectedFace[]): DetectedFace[] {
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

  private async resolveCamera(
    cameraId?: string,
    cameraRole?: "general" | "check_in" | "check_out",
  ): Promise<CameraConfig> {
    if (!this.cameraClient) {
      throw new Error("Python recognizer service is required for camera lookup.");
    }

    if (cameraRole) {
      const cameras = await this.cameraClient.listCameras();
      const roleCamera = cameras.find((camera) => camera.enabled && camera.camera_role === cameraRole);
      if (!roleCamera) {
        throw new Error(`No enabled camera found for role: ${cameraRole}`);
      }
      return roleCamera as CameraConfig;
    }

    if (cameraId) {
      const camera = await this.cameraClient.getCamera(cameraId);
      if (!camera) {
        throw new Error(`Camera not found: ${cameraId}`);
      }
      if (!camera.enabled) {
        throw new Error(`Camera is disabled: ${cameraId}`);
      }
      return camera as CameraConfig;
    }

    const cameras = await this.cameraClient.listCameras();
    const active = cameras.find((camera) => Boolean(camera.enabled));
    if (!active) {
      throw new Error("No enabled cameras were found in the database.");
    }
    return active as CameraConfig;
  }

  private async resolveCameras(
    cameraId?: string,
    cameraRole?: "general" | "check_in" | "check_out",
  ): Promise<CameraConfig[]> {
    if (!this.cameraClient) {
      throw new Error("Python recognizer service is required for camera lookup.");
    }

    const cameras = await this.cameraClient.listCameras();
    const enabled = cameras.filter((camera) => camera.enabled);

    if (cameraRole) {
      const roleMatches = enabled.filter((camera) => camera.camera_role === cameraRole);
      if (roleMatches.length) {
        return roleMatches as CameraConfig[];
      }
    }

    if (cameraId) {
      const selected = enabled.find((camera) => camera.id === cameraId);
      if (!selected) {
        throw new Error(`Camera not found or disabled: ${cameraId}`);
      }
      return [selected as CameraConfig];
    }

    return enabled as CameraConfig[];
  }

}

export const faceDetectionService = new FaceDetectionService();

function hashSignature(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return hash;
}
