import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.database import criar_banco
from routes.funcionarios import router as funcionarios_router, rh_router
from routes.estoque import router as estoque_router
from routes.vendas import router as vendas_router
from routes.setores import router as setores_router
from routes.logs import router as logs_router
from routes.compras import router as compras_router
from routes.despesas import router as despesas_router

_DEFAULT_ORIGINS = "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8080,http://localhost:8080"
ALLOWED_ORIGINS = [
    origem.strip()
    for origem in os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origem.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_banco()  # pragma: no cover
    yield  # pragma: no cover


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(funcionarios_router)
app.include_router(rh_router)
app.include_router(estoque_router)
app.include_router(vendas_router)
app.include_router(setores_router)
app.include_router(logs_router)
app.include_router(compras_router)
app.include_router(despesas_router)
