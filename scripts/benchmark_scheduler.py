"""Offline scheduler capacity benchmark.

This measures latest-frame scheduling overhead without requiring cameras or
network access. It is intentionally separate from model accuracy benchmarks.
"""
from __future__ import annotations

import argparse
import time
from collections import deque


def run(camera_count: int, seconds: float, budget_fps: int) -> dict[str, float | int]:
    queues = [deque(maxlen=1) for _ in range(camera_count)]
    processed = dropped = 0
    started = time.perf_counter()
    deadline = started + seconds
    interval = 1.0 / max(1, budget_fps)
    next_tick = started
    camera = 0
    while time.perf_counter() < deadline:
        now = time.perf_counter()
        if now < next_tick:
            time.sleep(min(0.002, next_tick - now))
            continue
        queues[camera].append(now)
        if len(queues[camera]) > 1:
            dropped += 1
        if queues[camera]:
            queues[camera].popleft()
            processed += 1
        camera = (camera + 1) % camera_count
        next_tick += interval / camera_count
    elapsed = max(0.001, time.perf_counter() - started)
    return {
        "cameras": camera_count,
        "seconds": round(elapsed, 2),
        "processedFrames": processed,
        "droppedFrames": dropped,
        "schedulerFps": round(processed / elapsed, 2),
        "maxQueueDepth": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--budget-fps", type=int, default=6)
    args = parser.parse_args()
    for cameras in (1, 5, 10, 25, 50, 100):
        print(run(cameras, args.seconds, args.budget_fps))


if __name__ == "__main__":
    main()
