export type DetectorWorkerRequest = {
    type: "detect";
    frameId: number;
    capturedAt: string;
    jpeg: ArrayBuffer;
} | {
    type: "shutdown";
};
export type DetectorWorkerResponse = {
    type: "state";
    value: string;
} | {
    type: "ready";
} | {
    type: "result";
    frameId: number;
    processedAt: string;
    faces: DetectedFace[];
    snapshot?: DetectionSnapshot;
} | {
    type: "error";
    frameId?: number;
    message: string;
    stack?: string;
};
export type DetectedFace = {
    confidence: number;
    box: {
        x: number;
        y: number;
        width: number;
        height: number;
    };
    match?: {
        label: string;
        score: number;
        confidence: number;
        sampleCount: number;
    } | null;
};
export type DetectionSnapshot = {
    path: string;
    timestamp: string;
    confidence: number;
};
export type DetectorWorkerData = {
    threshold: number;
    snapshotPath: string;
    cooldownMs: number;
};
