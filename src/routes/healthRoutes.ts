import { Router } from "express";

export const healthRoutes = Router();

healthRoutes.get("/health", (_req, res) => {
  res.json({
    ok: true,
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
  });
});
