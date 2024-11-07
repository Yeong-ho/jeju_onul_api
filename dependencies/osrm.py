import aiohttp
import os

urls = {
    'car': os.environ['OSRM_JEJU_URL'],
    'atlan': os.environ['ATLAN_WRAPPER_URL'],
}

PARAMS = {
    'geometries': 'polyline',
    'overview': 'false',
    'generate_hints': 'false',
    # 'annotations': 'duration,distance',
    'continue_straight': 'false'
}

async def GetRoutes(profile: str, locations) -> tuple[int, dict]:
    path = 'route/v1/car'

    encoded_locations = ";".join(f"{loc[0]},{loc[1]}" for loc in locations)
    encoded_params = "&".join((f"{k}={v}") for k, v in PARAMS.items())

    url = f"{urls[profile]}/{path}/{encoded_locations}?{encoded_params}"

    async with aiohttp.ClientSession() as session:
        response = await session.get(url)

        json = await response.json()
        status = response.status

        if status != 200:
            print(status, json)

        return status, json
