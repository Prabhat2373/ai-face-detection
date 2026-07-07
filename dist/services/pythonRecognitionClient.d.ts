import type { DetectedFace } from "../detector/types.js";
type PythonMatch = {
    label: string;
    score: number;
    confidence: number;
    sampleCount: number;
} | null;
type PythonFace = {
    confidence: number;
    box: {
        x: number;
        y: number;
        width: number;
        height: number;
    };
    match: PythonMatch;
};
type PythonRecognizeResponse = {
    faces: PythonFace[];
    snapshot?: {
        path: string;
        timestamp: string;
        confidence: number;
    } | null;
    state?: string;
};
type PythonRegisterResponse = {
    label: string;
    sampleCount: number;
    updatedAt: string;
};
type PythonFaceListResponse = {
    faces: Array<{
        label: string;
        sampleCount: number;
        updatedAt: string;
    }>;
};
export declare class PythonRecognitionClient {
    private readonly baseUrl;
    constructor(baseUrl: string);
    health(): Promise<boolean>;
    recognize(frame: Buffer): Promise<DetectedFace[]>;
    recognizeWithMeta(frame: Buffer): Promise<PythonRecognizeResponse>;
    register(label: string, frame: Buffer): Promise<PythonRegisterResponse>;
    listFaces(): Promise<PythonFaceListResponse["faces"]>;
    removeFace(label: string): Promise<boolean>;
    clearFaces(): Promise<void>;
    private get;
    private post;
    private toError;
}
export {};
