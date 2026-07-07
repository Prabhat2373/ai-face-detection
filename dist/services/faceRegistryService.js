import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { compareDescriptors } from "../utils/faceDescriptor.js";
export class FaceRegistryService {
    matchThreshold;
    log;
    filePath;
    faces = new Map();
    constructor(snapshotPath, matchThreshold, log) {
        this.matchThreshold = matchThreshold;
        this.log = log;
        this.filePath = join(snapshotPath, "known-faces.json");
    }
    async load() {
        try {
            const raw = await readFile(this.filePath, "utf8");
            const parsed = JSON.parse(raw);
            const faces = Array.isArray(parsed.faces) ? parsed.faces : [];
            this.faces = new Map(faces
                .filter((face) => typeof face?.label === "string")
                .map((face) => [
                face.label,
                {
                    label: face.label,
                    descriptors: Array.isArray(face.descriptors)
                        ? face.descriptors.filter(Array.isArray)
                        : [],
                    updatedAt: typeof face.updatedAt === "string"
                        ? face.updatedAt
                        : new Date().toISOString(),
                    sampleCount: Number(face.sampleCount) || face.descriptors.length,
                },
            ]));
            this.log.info({ faces: this.faces.size }, "Loaded face registry");
        }
        catch (error) {
            const normalized = error instanceof Error ? error : new Error(String(error));
            const code = error?.code;
            if (code === "ENOENT") {
                this.faces = new Map();
                return;
            }
            this.log.warn({ err: normalized }, "Face registry load skipped");
            this.faces = new Map();
        }
    }
    list() {
        return [...this.faces.values()].sort((left, right) => left.label.localeCompare(right.label));
    }
    get count() {
        return this.faces.size;
    }
    async clear() {
        this.faces.clear();
        await this.save();
    }
    async remove(label) {
        const deleted = this.faces.delete(label);
        if (deleted) {
            await this.save();
        }
        return deleted;
    }
    async register(label, descriptors) {
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
    match(descriptor) {
        let best = null;
        for (const face of this.faces.values()) {
            const scores = face.descriptors
                .map((sample) => compareDescriptors(descriptor, Float32Array.from(sample)))
                .sort((left, right) => right - left);
            const topScores = scores.slice(0, 3);
            if (!topScores.length) {
                continue;
            }
            const averageScore = topScores.reduce((sum, value) => sum + value, 0) / topScores.length;
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
    async save() {
        const payload = {
            version: 1,
            faces: this.list(),
        };
        await mkdir(dirname(this.filePath), { recursive: true });
        await writeFile(this.filePath, JSON.stringify(payload, null, 2));
    }
}
//# sourceMappingURL=faceRegistryService.js.map