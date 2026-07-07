export declare const env: {
    NODE_ENV: string;
    PORT: number;
    RTSP_URL: string;
    SNAPSHOT_PATH: string;
    DETECTION_THRESHOLD: number;
    MATCH_THRESHOLD: number;
    RECOGNITION_BACKEND: "node" | "python";
    PYTHON_RECOGNIZER_URL: string;
    LOG_LEVEL: string;
    FFMPEG_PATH: string;
    STREAM_FRAME_RATE: number;
    FRAME_RATE: number;
    DETECTION_COOLDOWN_MS: number;
    MAX_FRAME_BYTES: number;
    RTSP_USERNAME?: string | undefined;
    RTSP_PASSWORD?: string | undefined;
};
export type AppEnv = typeof env;
