import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
export class AttendanceService {
    log;
    cooldownMs;
    filePath;
    rootPath;
    records = new Map();
    constructor(snapshotPath, log, cooldownMs = 10_000) {
        this.log = log;
        this.cooldownMs = cooldownMs;
        this.filePath = join(snapshotPath, "attendance.csv");
        this.rootPath = join(process.cwd(), "attendance.csv");
    }
    async load() {
        try {
            const raw = await readFile(this.filePath, "utf8");
            const lines = raw.split(/\r?\n/).filter(Boolean);
            this.records.clear();
            for (const line of lines.slice(1)) {
                const [name, firstAppearance, lastAppearance, appearances, maxConfidence] = line.split(",");
                if (!name) {
                    continue;
                }
                this.records.set(name, {
                    name,
                    firstAppearance: firstAppearance || "",
                    lastAppearance: lastAppearance || "",
                    appearances: Number(appearances) || 0,
                    maxConfidence: Number(maxConfidence) || 0,
                });
            }
        }
        catch (error) {
            const code = error?.code;
            if (code === "ENOENT") {
                this.records.clear();
                return;
            }
            this.log.warn({ err: error }, "Attendance CSV load skipped");
            this.records.clear();
        }
    }
    recordMatch(label, confidence, timestamp = new Date(), cooldownMs = this.cooldownMs) {
        const iso = timestamp.toISOString();
        const current = this.records.get(label) ??
            {
                name: label,
                firstAppearance: iso,
                lastAppearance: iso,
                appearances: 0,
                maxConfidence: 0,
            };
        if (!current.firstAppearance) {
            current.firstAppearance = iso;
        }
        const previousLast = current.lastAppearance ? Date.parse(current.lastAppearance) : Number.NaN;
        const nowMs = timestamp.getTime();
        if (!current.appearances || Number.isNaN(previousLast) || nowMs - previousLast >= cooldownMs) {
            current.appearances += 1;
        }
        current.lastAppearance = iso;
        current.maxConfidence = Math.max(current.maxConfidence, confidence);
        this.records.set(label, current);
        void this.save().catch((error) => this.log.error({ err: error }, "Attendance save failed"));
        return current;
    }
    list() {
        return [...this.records.values()].sort((left, right) => left.name.localeCompare(right.name));
    }
    async exportCsv() {
        await this.save();
        return this.filePath;
    }
    async ensureFile() {
        await this.save();
    }
    async save() {
        await mkdir(dirname(this.filePath), { recursive: true });
        const rows = [
            ["name", "firstAppearance", "lastAppearance", "appearances", "maxConfidence"],
            ...this.list().map((record) => [
                record.name,
                record.firstAppearance,
                record.lastAppearance,
                String(record.appearances),
                String(record.maxConfidence),
            ]),
        ];
        const csv = rows.map((row) => row.map(escapeCsv).join(",")).join("\n");
        await writeFile(this.filePath, csv);
        await writeFile(this.rootPath, csv);
    }
}
function escapeCsv(value) {
    if (/["\n,]/.test(value)) {
        return `"${value.replaceAll('"', '""')}"`;
    }
    return value;
}
//# sourceMappingURL=attendanceService.js.map