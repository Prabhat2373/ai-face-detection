import express from "express";
import cors from "cors";
import helmet from "helmet";
import { pinoHttp } from "pino-http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { env } from "./config/env.js";
import { faceRoutes } from "./routes/faceRoutes.js";
import { detectionRoutes } from "./routes/detectionRoutes.js";
import { healthRoutes } from "./routes/healthRoutes.js";
import { faceDetectionService } from "./services/faceDetectionService.js";
import { logger } from "./utils/logger.js";
const app = express();
app.use(helmet({
    contentSecurityPolicy: {
        directives: {
            defaultSrc: ["'self'"],
            scriptSrc: ["'self'"],
            scriptSrcElem: ["'self'"],
            styleSrc: ["'self'", "'unsafe-inline'"],
            imgSrc: ["'self'", "data:", "blob:"],
            connectSrc: ["'self'"],
            mediaSrc: ["'self'", "blob:"],
            objectSrc: ["'none'"],
        },
    },
    crossOriginResourcePolicy: { policy: "cross-origin" },
}));
app.use(cors());
app.use(express.json({ limit: "1mb" }));
app.use(pinoHttp({ logger }));
app.use(express.static(join(process.cwd(), "public"), { fallthrough: true }));
app.use("/snapshots", express.static(join(process.cwd(), env.SNAPSHOT_PATH), {
    fallthrough: false,
    immutable: true,
    maxAge: "1h",
    setHeaders(res) {
        res.setHeader("Cross-Origin-Resource-Policy", "cross-origin");
    },
}));
app.use(healthRoutes);
app.use(faceRoutes);
app.use(detectionRoutes);
app.get("/favicon.ico", (_req, res) => {
    res.status(204).end();
});
app.get("/", async (_req, res, next) => {
    try {
        const html = await readFile(join(process.cwd(), "index.html"), "utf8");
        res.type("html").send(html);
    }
    catch (error) {
        next(error);
    }
});
const errorHandler = (error, _req, res, _next) => {
    const normalized = error instanceof Error ? error : new Error(String(error));
    logger.error({ err: normalized }, "Unhandled request error");
    res.status(500).json({
        error: "Internal Server Error",
        message: normalized.message,
    });
};
app.use(errorHandler);
const server = app.listen(env.PORT, () => {
    logger.info({ port: env.PORT }, "Face detection API listening");
});
async function shutdown(signal) {
    logger.info({ signal }, "Graceful shutdown started");
    server.close(async (error) => {
        if (error) {
            logger.error({ err: error }, "HTTP server close failed");
            process.exitCode = 1;
        }
        try {
            await faceDetectionService.stop();
            logger.info("Graceful shutdown complete");
            process.exit();
        }
        catch (shutdownError) {
            logger.error({ err: shutdownError }, "Graceful shutdown failed");
            process.exit(1);
        }
    });
}
process.on("SIGINT", (signal) => {
    void shutdown(signal);
});
process.on("SIGTERM", (signal) => {
    void shutdown(signal);
});
process.on("uncaughtException", (error) => {
    logger.fatal({ err: error }, "Uncaught exception");
    void shutdown("SIGTERM");
});
process.on("unhandledRejection", (reason) => {
    logger.fatal({ err: reason }, "Unhandled rejection");
    void shutdown("SIGTERM");
});
//# sourceMappingURL=server.js.map