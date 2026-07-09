import { setInterval, clearInterval } from "node:timers";
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

export class UpdateService {
  private readonly status: UpdateStatus;
  private timer?: ReturnType<typeof setInterval>;

  public constructor(
    private readonly config: Pick<AppEnv, "AGENT_VERSION" | "AUTO_UPDATE_URL" | "AUTO_UPDATE_INTERVAL_MS">,
    private readonly log: typeof logger,
  ) {
    this.status = {
      enabled: Boolean(config.AUTO_UPDATE_URL),
      currentVersion: config.AGENT_VERSION,
      updateAvailable: false,
    };
  }

  public start(): void {
    if (!this.config.AUTO_UPDATE_URL || this.timer) {
      return;
    }

    void this.checkOnce();
    this.timer = setInterval(() => {
      void this.checkOnce();
    }, this.config.AUTO_UPDATE_INTERVAL_MS);
  }

  public stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
  }

  public getStatus(): UpdateStatus {
    return { ...this.status };
  }

  public async checkOnce(): Promise<UpdateStatus> {
    if (!this.config.AUTO_UPDATE_URL) {
      this.status.enabled = false;
      return this.getStatus();
    }

    try {
      const response = await fetch(this.config.AUTO_UPDATE_URL);
      if (!response.ok) {
        throw new Error(`Update check failed with HTTP ${response.status}`);
      }
      const payload = (await response.json()) as { version?: string };
      this.status.enabled = true;
      this.status.latestVersion = payload.version;
      this.status.updateAvailable = Boolean(
        payload.version && compareVersions(payload.version, this.config.AGENT_VERSION) > 0,
      );
      this.status.lastCheckedAt = new Date().toISOString();
      this.status.lastError = undefined;
    } catch (error) {
      this.status.lastError = error instanceof Error ? error.message : String(error);
      this.status.lastCheckedAt = new Date().toISOString();
      this.log.warn({ err: error }, "Update check failed");
    }

    return this.getStatus();
  }
}

function compareVersions(left: string, right: string): number {
  const leftParts = left.split(".").map((part) => Number(part) || 0);
  const rightParts = right.split(".").map((part) => Number(part) || 0);
  const maxLength = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < maxLength; index += 1) {
    const difference = (leftParts[index] ?? 0) - (rightParts[index] ?? 0);
    if (difference !== 0) {
      return difference;
    }
  }
  return 0;
}
