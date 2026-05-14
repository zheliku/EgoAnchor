import asyncio
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect("nats://127.0.0.1:4222")

    reply = await nc.request(
        "egoanchor.command.reset_tracking",
        b'{"request_id":"demo-001","anchor_id":"main"}',
        timeout=1
    )

    print("reply:", reply.data.decode())
    await nc.close()

asyncio.run(main())
