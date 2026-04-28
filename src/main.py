from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.database import criar_banco
from routes.funcionarios import router as funcionarios_router, rh_router
from routes.estoque import router as estoque_router
from routes.vendas import router as vendas_router
from routes.setores import router as setores_router
from routes.logs import router as logs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_banco()  # pragma: no cover
    yield  # pragma: no cover


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(funcionarios_router)
app.include_router(rh_router)
app.include_router(estoque_router)
app.include_router(vendas_router)
app.include_router(setores_router)
app.include_router(logs_router)
