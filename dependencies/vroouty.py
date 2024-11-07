import aiohttp
import os

BASE_URL = os.environ['VROOUTY_URL']

async def Post(request: dict) -> tuple[int, dict]:
    async with aiohttp.ClientSession() as session:
        response = await session.post(BASE_URL, json=request, headers={'Content-Type':'application/json'})

        json = await response.json()
        status = response.status

        if status != 200:
            print(status, json)

        return status, json
