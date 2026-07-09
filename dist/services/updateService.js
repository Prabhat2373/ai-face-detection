import { setInterval, clearInterval } from "node:timers";
export class UpdateService {
    config;
    log;
    status;
    timer;
    constructor(config, log) {
        this.config = config;
        this.log = log;
        this.status = {
            enabled: Boolean(config.AUTO_UPDATE_URL),
            currentVersion: config.AGENT_VERSION,
            updateAvailable: false,
        };
    }
    start() {
        if (!this.config.AUTO_UPDATE_URL || this.timer) {
            return;
        }
        void this.checkOnce();
        this.timer = setInterval(() => {
            void this.checkOnce();
        }, this.config.AUTO_UPDATE_INTERVAL_MS);
    }
    stop() {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = undefined;
        }
    }
    getStatus() {
        return { ...this.status };
    }
    async checkOnce() {
        if (!this.config.AUTO_UPDATE_URL) {
            this.status.enabled = false;
            return this.getStatus();
        }
        try {
            const response = await fetch(this.config.AUTO_UPDATE_URL);
            if (!response.ok) {
                throw new Error(`Update check failed with HTTP ${response.status}`);
            }
            const payload = (await response.json());
            this.status.enabled = true;
            this.status.latestVersion = payload.version;
            this.status.updateAvailable = Boolean(payload.version && compareVersions(payload.version, this.config.AGENT_VERSION) > 0);
            this.status.lastCheckedAt = new Date().toISOString();
            this.status.lastError = undefined;
        }
        catch (error) {
            this.status.lastError = error instanceof Error ? error.message : String(error);
            this.status.lastCheckedAt = new Date().toISOString();
            this.log.warn({ err: error }, "Update check failed");
        }
        return this.getStatus();
    }
}
function compareVersions(left, right) {
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
//# sourceMappingURL=updateService.js.map