import asyncio
import time

import cv2
import numpy as np
from nats.aio.client import Client as NATS

SUBJECT = "egoanchor.quest.image_jpeg"

last_t = time.perf_counter()
count = 0


async def main():
    global last_t, count

    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")

    async def handle_image(msg):
        global last_t, count

        jpg = np.frombuffer(msg.data, dtype=np.uint8)
        image = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
        if image is None:
            print("[Python] failed to decode image, bytes=", len(msg.data))
            return

        count += 1
        now = time.perf_counter()
        if now - last_t >= 1.0:
            fps = count / (now - last_t)
            print(f"[Python] image fps={fps:.1f}, bytes={len(msg.data)}")
            count = 0
            last_t = now

        cv2.imshow("NATS image stream", image)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            await nc.close()
            cv2.destroyAllWindows()

    await nc.subscribe(SUBJECT, cb=handle_image)
    print(f"[Python] listening: {SUBJECT}")

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        cv2.destroyAllWindows()


asyncio.run(main())
