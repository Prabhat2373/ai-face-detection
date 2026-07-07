import type { logger } from "../utils/logger.js";
export type AttendanceRecord = {
    name: string;
    firstAppearance: string;
    lastAppearance: string;
    appearances: number;
    maxConfidence: number;
};
export declare class AttendanceService {
    private readonly log;
    private readonly cooldownMs;
    private readonly filePath;
    private readonly rootPath;
    private records;
    constructor(snapshotPath: string, log: typeof logger, cooldownMs?: number);
    load(): Promise<void>;
    recordMatch(label: string, confidence: number, timestamp?: Date, cooldownMs?: number): AttendanceRecord;
    list(): AttendanceRecord[];
    exportCsv(): Promise<string>;
    ensureFile(): Promise<void>;
    private save;
}
