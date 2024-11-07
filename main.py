from fastapi import FastAPI

from routers.maintain import router as maintain_router
from routers.v1.jeju_onul import router as jeju_onul_v1_router
from routers.v2.jeju_onul import router as jeju_onul_v2_router

import env

app = FastAPI(
    title='Roouty Dynamic Engine',
    version=env.VERSION
)

app.include_router(maintain_router)
app.include_router(jeju_onul_v1_router,prefix='/v1')
app.include_router(jeju_onul_v2_router,prefix='/v2')
