import asyncio
from nats.aio.client import Client as NATS

SUBJECT = "egoanchor.command.reset_tracking"

async def main():
    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")

    async def handle_reset(msg):
        text = msg.data.decode("utf-8")
        print("[Python] received:", text)

        # 以后这里替换成 pipeline.reset_tracking_state()
        reply = '{"accepted":true,"applied":true,"message":"reset from python ok"}'
        await msg.respond(reply.encode("utf-8"))

    await nc.subscribe(SUBJECT, cb=handle_reset)
    print(f"[Python] listening: {SUBJECT}")

    while True:
        await asyncio.sleep(1)

asyncio.run(main())
