import type { AppEnv } from "../config/env.js";
import type { logger } from "../utils/logger.js";
type UpdateStatus = {
    enabled: boolean;
    currentVersion: string;
    latestVersion?: string;
    updateAvailable: boolean;
    lastCheckedAt?: string;
    lastError?: string;
};
export declare class UpdateService {
    private readonly config;
    private readonly log;
    private readonly status;
    private timer?;
    constructor(config: Pick<AppEnv, "AGENT_VERSION" | "AUTO_UPDATE_URL" | "AUTO_UPDATE_INTERVAL_MS">, log: typeof logger);
    start(): void;
    stop(): void;
    getStatus(): UpdateStatus;
    checkOnce(): Promise<UpdateStatus>;
}
export {};
