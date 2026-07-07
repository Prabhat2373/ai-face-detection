import type { logger } from "../utils/logger.js";
export type RegisteredFaceProfile = {
    label: string;
    descriptors: number[][];
    updatedAt: string;
    sampleCount: number;
};
export type FaceMatch = {
    label: string;
    score: number;
    confidence: number;
    sampleCount: number;
};
export declare class FaceRegistryService {
    private readonly matchThreshold;
    private readonly log;
    private readonly filePath;
    private faces;
    constructor(snapshotPath: string, matchThreshold: number, log: typeof logger);
    load(): Promise<void>;
    list(): RegisteredFaceProfile[];
    get count(): number;
    clear(): Promise<void>;
    remove(label: string): Promise<boolean>;
    register(label: string, descriptors: Float32Array[]): Promise<RegisteredFaceProfile>;
    match(descriptor: Float32Array): FaceMatch | null;
    private save;
}
