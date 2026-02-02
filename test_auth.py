import asyncio
from copilot import CopilotClient

async def main():
    client = CopilotClient()
    try:
        await client.start()
        status = await client.get_auth_status()
        print(f"Status Type: {type(status)}")
        print(f"Status: {status}")
    finally:
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
