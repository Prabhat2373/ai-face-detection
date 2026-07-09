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
type PythonAttendanceResponse = {
    attendance: Array<{
        label: string;
        first_appearance: string;
        last_appearance: string;
        first_camera_role?: string;
        last_camera_role?: string;
        appearances: number;
        max_confidence: number;
    }>;
};
type PythonCamera = {
    id: string;
    name: string;
    camera_role: "general" | "check_in" | "check_out";
    rtsp_url: string;
    rtsp_username?: string | null;
    rtsp_password?: string | null;
    enabled: number;
    created_at: string;
    updated_at: string;
};
export declare class PythonRecognitionClient {
    private readonly baseUrl;
    constructor(baseUrl: string);
    health(): Promise<boolean>;
    recognize(frame: Buffer, cameraRole?: "general" | "check_in" | "check_out", cameraId?: string | null): Promise<DetectedFace[]>;
    recognizeWithMeta(frame: Buffer, cameraRole?: "general" | "check_in" | "check_out", cameraId?: string | null): Promise<PythonRecognizeResponse>;
    register(label: string, frame: Buffer, cameraRole?: "general" | "check_in" | "check_out", cameraId?: string | null): Promise<PythonRegisterResponse>;
    listFaces(): Promise<PythonFaceListResponse["faces"]>;
    removeFace(label: string): Promise<boolean>;
    clearFaces(): Promise<void>;
    listCameras(): Promise<PythonCamera[]>;
    getCamera(cameraId: string): Promise<PythonCamera | null>;
    addCamera(camera: {
        id?: string;
        name: string;
        cameraRole?: "general" | "check_in" | "check_out";
        rtspUrl: string;
        rtspUsername?: string | null;
        rtspPassword?: string | null;
        enabled?: boolean;
    }): Promise<PythonCamera>;
    updateCamera(cameraId: string, camera: {
        name: string;
        cameraRole?: "general" | "check_in" | "check_out";
        rtspUrl: string;
        rtspUsername?: string | null;
        rtspPassword?: string | null;
        enabled?: boolean;
    }): Promise<PythonCamera>;
    deleteCamera(cameraId: string): Promise<boolean>;
    listAttendance(): Promise<PythonAttendanceResponse["attendance"]>;
    exportAttendanceCsv(): Promise<string>;
    private get;
    private post;
    private put;
    private toError;
}
export {};
