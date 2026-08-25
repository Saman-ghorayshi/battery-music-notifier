#!/usr/bin/env python3
"""Generic async TCP forwarder: listen 0.0.0.0:LPORT -> forward TARGET:TPORT.

Built so WSL guests can reach a Windows-localhost proxy (v2rayN binds
127.0.0.1 only). Pure stdlib.

    python tools/tcp_forward.py <listen_port> <target_host> <target_port>
"""
import asyncio
import sys


async def pipe(r, w):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def handle(client_r, client_w, target_host, target_port):
    try:
        up_r, up_w = await asyncio.open_connection(target_host, target_port)
    except Exception as e:
        print(f"[forward] upstream connect failed: {e}", flush=True)
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))


async def main():
    lport, thost, tport = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, thost, tport), "0.0.0.0", lport)
    print(f"forwarding 0.0.0.0:{lport} -> {thost}:{tport}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
