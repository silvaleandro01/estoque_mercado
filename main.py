from fastapi import FastAPI, Depends, Header, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from database import Estoque, criar_banco, FuncionarioCreate, Setor, SetorCreate
from estoque import *
from vendas import criar_venda, vendas_do_dia
from schemas_vendas import VendaInput
from funcionarios import *
from setor import criar_setor, listar_setores, buscar_setor, atualizar_setor, deletar_setor
from logs import listar_logs

from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str = ""

class PasswordResetRequest(BaseModel):
    funcionario_id: int
    nova_senha: str

class SalarioUpdate(BaseModel):
    funcionario_id: int
    valor: float

class FolhaFecharRequest(BaseModel):
    mes: int
    ano: int

from estoque import EstoqueUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_banco()
    yield


app = FastAPI(lifespan=lifespan)

origins = ["*", "null"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_funcionario(authorization: str = Header(...)):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token inválido")

    token = authorization.split(" ")[1]
    return validar_funcionario_por_token(token)

@app.post("/login")
def login_rota(dados: LoginRequest):
    return autenticar_funcionario(dados.username, dados.password)

@app.post("/funcionarios/definir-senha")
def definir_senha_rota(dados: PasswordResetRequest):
    return definir_nova_senha(dados.funcionario_id, dados.nova_senha)

@app.post("/funcionarios/criar")
def criar(dados: FuncionarioCreate):
    return criar_funcionario(dados)


@app.get("/funcionarios/listar")
def listar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_funcionarios()

@app.get("/funcionarios/buscar/{id}")
def buscar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return buscar_funcionario(id)

@app.put("/funcionarios/atualizar/{id}")
def atualizar(id: int, dados: FuncionarioCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return atualizar_funcionario(id, dados)

@app.delete("/funcionarios/deletar/{id}")
def deletar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return deletar_funcionario(id)

@app.post("/funcionarios/renovar-token/{id}")
def renovar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return renovar_token(id)

@app.post("/estoque/inserir")
def inserir_estoque(estoque: Estoque, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, ["estoque", "gerencia"])
    return criar_estoque(estoque, funcionario.id)

@app.get("/estoque/mostrar")
def mostrar_estoque(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, ["estoque", "gerencia"])
    return mostrar_produtos()

@app.get("/estoque/buscar/{estoque_id}")
def buscar_estoque_route(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, ["estoque", "gerencia"])
    return buscar_estoque(estoque_id)

@app.put("/estoque/atualizar/{estoque_id}")
def atualizar_estoque_route(estoque_id: int, dados: EstoqueUpdate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, ["estoque", "gerencia"])
    return atualizar_estoque(estoque_id, dados, funcionario.id)

@app.delete("/estoque/deletar/{estoque_id}")
def deletar_estoque_route(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, ["estoque", "gerencia"])
    return deletar_estoque(estoque_id)

@app.post("/vendas/inserir")
def inserir_vendas(dados: VendaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, ["vendas", "gerencia"])
    return criar_venda(dados, funcionario.id)

@app.get("/vendas/vendasdodia")
def buscar_vendas(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "gerencia")
    return vendas_do_dia()

@app.post("/pontos/bater")
def bater_ponto(
    data_manual: date = None, 
    hora_manual: datetime = None, 
    funcionario=Depends(get_funcionario)
):
    if funcionario.is_admin:
        raise HTTPException(status_code=400, detail="Admin não bate ponto")
    return registrar_ponto_funcionario(funcionario.id, data_manual, hora_manual)

@app.get("/pontos/status")
def status_ponto(funcionario=Depends(get_funcionario)):
    return obter_status_ponto(funcionario.id)

@app.get("/pontos/meu-relatorio")
def meu_relatorio(mes: int, ano: int, funcionario=Depends(get_funcionario)):
    return relatorio_mensal_funcionario(funcionario.id, mes, ano)

@app.get("/pontos/rh/geral")
def relatorio_geral_rh(mes: int, ano: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return relatorio_geral_pontos_rh(mes, ano)

@app.get("/pontos/rh/funcionario/{id}")
def relatorio_individual_rh(id: int, mes: int, ano: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return relatorio_mensal_funcionario(id, mes, ano)

@app.post("/funcionarios/definir-salario")
def rota_definir_salario(dados: SalarioUpdate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return definir_salario_funcionario(dados.funcionario_id, dados.valor)

@app.get("/funcionarios/salario-historico/{id}")
def rota_historico_salario(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return buscar_historico_salarial(id)

@app.post("/folha/fechar")
def rota_fechar_folha(dados: FolhaFecharRequest, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return fechar_folha_mensal(dados.mes, dados.ano)

@app.get("/folha/meu-holerite")
def rota_meu_holerite(mes: int, ano: int, funcionario=Depends(get_funcionario)):
    res = buscar_holerite_funcionario(funcionario.id, mes, ano)
    return res if res else {}

@app.get("/folha/buscar-funcionario")
def rota_admin_buscar_holerite(funcionario_id: int, mes: int, ano: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    res = buscar_holerite_funcionario(funcionario_id, mes, ano)
    return res if res else {}

@app.post("/folha/assinar/{id}")
def rota_assinar_holerite(id: int, funcionario=Depends(get_funcionario)):
    return assinar_holerite_funcionario(funcionario.id, id)

@app.post("/setores/criar")
def rota_criar_setor(setor: SetorCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return criar_setor(setor)

@app.get("/setores/listar")
def rota_listar_setores(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_setores()

@app.get("/setores/{id}")
def rota_buscar_setor(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return buscar_setor(id)

@app.put("/setores/{id}")
def rota_atualizar_setor(id: int, setor: SetorCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return atualizar_setor(id, setor)

@app.delete("/setores/{id}")
def rota_deletar_setor(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return deletar_setor(id)

@app.get("/logs")
def ver_logs(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_logs()