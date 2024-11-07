from fastapi import APIRouter

import env

router = APIRouter(
    prefix='',
    tags=['maintain'],
    dependencies=[],
    responses={},
)

@router.get('/version')
def version() -> str:
    return env.VERSION
