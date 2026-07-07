import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { logger } from "../utils/logger.js";

export type AttendanceRecord = {
  name: string;
  firstAppearance: string;
  lastAppearance: string;
  appearances: number;
  maxConfidence: number;
};

export class AttendanceService {
  private readonly filePath: string;
  private readonly rootPath: string;
  private records = new Map<string, AttendanceRecord>();

  public constructor(
    snapshotPath: string,
    private readonly log: typeof logger,
    private readonly cooldownMs = 10_000,
  ) {
    this.filePath = join(snapshotPath, "attendance.csv");
    this.rootPath = join(process.cwd(), "attendance.csv");
  }

  public async load(): Promise<void> {
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
    } catch (error) {
      const code = (error as NodeJS.ErrnoException | undefined)?.code;
      if (code === "ENOENT") {
        this.records.clear();
        return;
      }
      this.log.warn({ err: error }, "Attendance CSV load skipped");
      this.records.clear();
    }
  }

  public recordMatch(
    label: string,
    confidence: number,
    timestamp = new Date(),
    cooldownMs = this.cooldownMs,
  ): AttendanceRecord {
    const iso = timestamp.toISOString();
    const current =
      this.records.get(label) ??
      ({
        name: label,
        firstAppearance: iso,
        lastAppearance: iso,
        appearances: 0,
        maxConfidence: 0,
      } satisfies AttendanceRecord);

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

  public list(): AttendanceRecord[] {
    return [...this.records.values()].sort((left, right) =>
      left.name.localeCompare(right.name),
    );
  }

  public async exportCsv(): Promise<string> {
    await this.save();
    return this.filePath;
  }

  public async ensureFile(): Promise<void> {
    await this.save();
  }

  private async save(): Promise<void> {
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

function escapeCsv(value: string): string {
  if (/["\n,]/.test(value)) {
    return `"${value.replaceAll('"', '""')}"`;
  }
  return value;
}
