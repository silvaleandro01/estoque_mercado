from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# carregar variáveis de ambiente
load_dotenv()

# imports do sistema
from database import Estoque, criar_banco, FuncionarioCreate, Setor, SetorCreate
from estoque import *
from vendas import criar_venda, vendas_do_dia
from schemas_vendas import VendaInput
from funcionarios import *
from setor import criar_setor, listar_setores, buscar_setor, atualizar_setor, deletar_setor
from logs import listar_logs

# 🔹 IMPORTANTE (faltava isso)
from estoque import EstoqueUpdate


# inicializa banco ao subir o sistema
@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_banco()
    yield


app = FastAPI(lifespan=lifespan)

# Configuração de CORS para permitir requisições do frontend
origins = ["*"]  # Em produção, especifique os domínios permitidos

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# valida token do funcionário
def get_funcionario(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token inválido")

    token = authorization.split(" ")[1]
    return validar_funcionario_por_token(token)


# criar funcionário
@app.post("/funcionarios/criar")
def criar(dados: FuncionarioCreate):
    return criar_funcionario(dados)


# listar funcionários (apenas RH)
@app.get("/funcionarios/listar")
def listar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_funcionarios()


# buscar funcionário por id
@app.get("/funcionarios/buscar/{id}")
def buscar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return buscar_funcionario(id)


# atualizar funcionário
@app.put("/funcionarios/atualizar/{id}")
def atualizar(id: int, dados: FuncionarioCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return atualizar_funcionario(id, dados)


# deletar funcionário
@app.delete("/funcionarios/deletar/{id}")
def deletar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return deletar_funcionario(id)


# renovar token (RH)
@app.post("/rh/renovar-token/{id}")
def renovar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return renovar_token(id)


# inserir produto no estoque
@app.post("/estoque/inserir")
def inserir_estoque(estoque: Estoque, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return criar_estoque(estoque, funcionario.id)


# listar estoque
@app.get("/estoque/mostrar")
def mostrar_estoque(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return mostrar_produtos()


# buscar produto
@app.get("/estoque/buscar/{estoque_id}")
def buscar_estoque_route(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return buscar_estoque(estoque_id)


# atualizar produto
@app.put("/estoque/atualizar/{estoque_id}")
def atualizar_estoque_route(estoque_id: int, dados: EstoqueUpdate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return atualizar_estoque(estoque_id, dados, funcionario.id)


# deletar produto
@app.delete("/estoque/deletar/{estoque_id}")
def deletar_estoque_route(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return deletar_estoque(estoque_id)


# registrar venda
@app.post("/vendas/inserir")
def inserir_vendas(dados: VendaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return criar_venda(dados, funcionario.id)


# vendas do dia
@app.get("/vendas/vendasdodia")
def buscar_vendas(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return vendas_do_dia()


# criar setor (apenas RH)
@app.post("/setores/criar")
def rota_criar_setor(setor: SetorCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return criar_setor(setor)


# listar setores
@app.get("/setores/listar")
def rota_listar_setores(funcionario=Depends(get_funcionario)):
    return listar_setores()


# buscar setor por id
@app.get("/setores/{id}")
def rota_buscar_setor(id: int, funcionario=Depends(get_funcionario)):
    return buscar_setor(id)


# atualizar setor (apenas RH)
@app.put("/setores/{id}")
def rota_atualizar_setor(id: int, setor: SetorCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return atualizar_setor(id, setor)


# deletar setor (apenas RH)
@app.delete("/setores/{id}")
def rota_deletar_setor(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return deletar_setor(id)


# visualizar logs (apenas RH)
@app.get("/logs")
def ver_logs(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_logs()