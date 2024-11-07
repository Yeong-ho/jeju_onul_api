import os

VERSION: str = os.getenv('VERSION')

for env in [VERSION]:
    if env is None:
        raise KeyError(f'Environment Variable "{env}" not found')
