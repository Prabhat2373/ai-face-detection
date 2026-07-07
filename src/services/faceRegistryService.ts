import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { compareDescriptors } from "../utils/faceDescriptor.js";
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

type SerializedRegistry = {
  version: 1;
  faces: RegisteredFaceProfile[];
};

export class FaceRegistryService {
  private readonly filePath: string;
  private faces = new Map<string, RegisteredFaceProfile>();

  public constructor(
    snapshotPath: string,
    private readonly matchThreshold: number,
    private readonly log: typeof logger,
  ) {
    this.filePath = join(snapshotPath, "known-faces.json");
  }

  public async load(): Promise<void> {
    try {
      const raw = await readFile(this.filePath, "utf8");
      const parsed = JSON.parse(raw) as SerializedRegistry;
      const faces = Array.isArray(parsed.faces) ? parsed.faces : [];
      this.faces = new Map(
        faces
          .filter((face) => typeof face?.label === "string")
          .map((face) => [
            face.label,
            {
              label: face.label,
              descriptors: Array.isArray(face.descriptors)
                ? face.descriptors.filter(Array.isArray)
                : [],
              updatedAt:
                typeof face.updatedAt === "string"
                  ? face.updatedAt
                  : new Date().toISOString(),
              sampleCount: Number(face.sampleCount) || face.descriptors.length,
            },
          ]),
      );
      this.log.info({ faces: this.faces.size }, "Loaded face registry");
    } catch (error) {
      const normalized = error instanceof Error ? error : new Error(String(error));
      const code = (error as NodeJS.ErrnoException | undefined)?.code;
      if (code === "ENOENT") {
        this.faces = new Map();
        return;
      }

      this.log.warn({ err: normalized }, "Face registry load skipped");
      this.faces = new Map();
    }
  }

  public list(): RegisteredFaceProfile[] {
    return [...this.faces.values()].sort((left, right) =>
      left.label.localeCompare(right.label),
    );
  }

  public get count(): number {
    return this.faces.size;
  }

  public async clear(): Promise<void> {
    this.faces.clear();
    await this.save();
  }

  public async remove(label: string): Promise<boolean> {
    const deleted = this.faces.delete(label);
    if (deleted) {
      await this.save();
    }
    return deleted;
  }

  public async register(
    label: string,
    descriptors: Float32Array[],
  ): Promise<RegisteredFaceProfile> {
    const normalized = descriptors
      .map((descriptor) => Array.from(descriptor))
      .filter((descriptor) => descriptor.length > 0);

    if (!normalized.length) {
      throw new Error("No face descriptors were collected");
    }

    const current = this.faces.get(label) ?? {
      label,
      descriptors: [],
      updatedAt: new Date().toISOString(),
      sampleCount: 0,
    };

    current.descriptors.push(...normalized);
    current.updatedAt = new Date().toISOString();
    current.sampleCount = current.descriptors.length;

    this.faces.set(label, current);
    await this.save();
    return current;
  }

  public match(descriptor: Float32Array): FaceMatch | null {
    let best: FaceMatch | null = null;

    for (const face of this.faces.values()) {
      const scores = face.descriptors
        .map((sample) => compareDescriptors(descriptor, Float32Array.from(sample)))
        .sort((left, right) => right - left);
      const topScores = scores.slice(0, 3);
      if (!topScores.length) {
        continue;
      }

      const averageScore =
        topScores.reduce((sum, value) => sum + value, 0) / topScores.length;
      const bestScore = topScores[0] ?? -1;
      const candidateScore = Math.max(bestScore, averageScore);

      if (!best || candidateScore > best.score) {
        best = {
          label: face.label,
          score: candidateScore,
          confidence: candidateScore,
          sampleCount: face.sampleCount,
        };
      }
    }

    if (!best || best.score < this.matchThreshold) {
      return null;
    }

    return best;
  }

  private async save(): Promise<void> {
    const payload: SerializedRegistry = {
      version: 1,
      faces: this.list(),
    };

    await mkdir(dirname(this.filePath), { recursive: true });
    await writeFile(this.filePath, JSON.stringify(payload, null, 2));
  }
}
