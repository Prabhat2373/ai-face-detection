import { type AppEnv } from "../config/env.js";
import type { DetectedFace, DetectionSnapshot } from "../detector/types.js";
type ServiceState = "idle" | "starting" | "running" | "stopping" | "error";
export declare class FaceDetectionService {
    private readonly config;
    private readonly events;
    private state;
    private stream?;
    private detector?;
    private readonly registry;
    private readonly attendance;
    private readonly pythonRecognizer?;
    private latestFrame?;
    private latestDetectionFrame?;
    private startedAt?;
    private stoppedAt?;
    private lastError?;
    private lastWorkerState?;
    private lastDetection?;
    private lastFaces;
    private detectionCount;
    private receivedFrames;
    private acceptedFrames;
    private detectionStride;
    private frameModulo;
    private registeredFacesCount;
    private pythonBusy;
    private pythonDroppedFrames;
    private pythonProcessedFrames;
    constructor(config?: AppEnv);
    getStatus(): {
        state: ServiceState;
        startedAt: string | undefined;
        stoppedAt: string | undefined;
        lastError: string | undefined;
        lastWorkerState: string | undefined;
        lastDetection: DetectionSnapshot | undefined;
        detectionCount: number;
        frames: {
            received: number;
            accepted: number;
            detector: {
                ready: boolean;
                busy: boolean;
                droppedFrames: number;
                processedFrames: number;
                lastWorkerState: string | undefined;
            } | null;
        };
        config: {
            snapshotPath: string;
            detectionThreshold: number;
            matchThreshold: number;
            frameRate: number;
            streamFrameRate: number;
            cooldownMs: number;
            recognitionBackend: "node" | "python";
            pythonRecognizerUrl: string | undefined;
        };
        stream: {
            running: boolean;
            lastState: string | undefined;
        } | null;
        lastFaces: DetectedFace[];
        registeredFaces: number;
        attendance: import("./attendanceService.js").AttendanceRecord[];
    };
    onFrame(listener: (frame: Buffer) => void): () => void;
    getLatestFrame(): Buffer | undefined;
    listRegisteredFaces(): Promise<{
        label: string;
        sampleCount: number;
        updatedAt: string;
    }[]>;
    removeRegisteredFace(label: string): Promise<boolean>;
    clearRegisteredFaces(): Promise<void>;
    exportAttendanceCsv(): Promise<string>;
    registerFace(label: string): Promise<{
        label: string;
        sampleCount: number;
        updatedAt: string;
    }>;
    start(): Promise<void>;
    stop(): Promise<void>;
    private handleError;
    private handleDetectorResult;
    private handlePythonFrame;
    private waitForPythonRecognizerReady;
    private annotateFaces;
}
export declare const faceDetectionService: FaceDetectionService;
export {};
