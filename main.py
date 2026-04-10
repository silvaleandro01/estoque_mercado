from fastapi import FastAPI, Depends, Header, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from database import Estoque, criar_banco, FuncionarioCreate, Setor, SetorCreate
from estoque import *
from vendas import criar_venda, vendas_do_dia, obter_estatisticas_dashboard, criar_despesa, cancelar_venda_logica, listar_vendas_detalhado
from schemas_vendas import VendaInput, CompraInput, DespesaInput
from funcionarios import *
from setor import criar_setor, listar_setores, buscar_setor, atualizar_setor, deletar_setor
from logs import listar_logs
from comunicados import ComunicadoCreate, criar_comunicado, listar_comunicados, contar_nao_lidos, marcar_como_lido
from solicitacoes import SolicitacaoCompraCreate, SolicitacaoCompraUpdate, criar_solicitacao, listar_solicitacoes, responder_solicitacao

from pydantic import BaseModel, Field

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

class HierarquiaRequest(BaseModel):
    funcionario_id: int
    bate_ponto: bool
    cargo_confianca: bool
    cargo: str

from estoque import EstoqueUpdate, encaminhar_compra, recusar_compra


@asynccontextmanager
async def lifespan(app: FastAPI):
    criar_banco()
    yield


app = FastAPI(lifespan=lifespan)

origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
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
def criar(dados: FuncionarioCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    if not funcionario.is_admin:
        dados.is_admin = False
    return criar_funcionario(dados)


@app.get("/funcionarios/listar")
def listar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "equipe")
    return listar_funcionarios(funcionario)

@app.get("/funcionarios/buscar/{id}")
def buscar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return buscar_funcionario(id)

@app.put("/funcionarios/atualizar/{id}")
def atualizar(id: int, dados: FuncionarioCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    if not funcionario.is_admin:
        dados.is_admin = False
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
    verificar_permissao(funcionario, "estoque_inserir")
    return criar_estoque(estoque, funcionario.id)

@app.get("/estoque/mostrar")
def mostrar_estoque(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque_ver")
    return mostrar_produtos()

@app.get("/estoque/buscar/{estoque_id}")
def buscar_estoque_route(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque_ver")
    return buscar_estoque(estoque_id)

@app.put("/estoque/atualizar/{estoque_id}")
def atualizar_estoque_route(estoque_id: int, dados: EstoqueUpdate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque_editar")
    return atualizar_estoque(estoque_id, dados, funcionario.id)

@app.delete("/estoque/deletar/{estoque_id}")
def deletar_estoque_route(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque_editar")
    return deletar_estoque(estoque_id)

@app.post("/vendas/inserir")
def inserir_vendas(dados: VendaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return criar_venda(dados, funcionario.id)

@app.get("/vendas/vendasdodia")
def buscar_vendas(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas_dia")
    res = vendas_do_dia()
    res["lista"] = listar_vendas_detalhado()
    return res

@app.delete("/vendas/cancelar/{id}")
def delete_venda(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas_cancelar")
    return cancelar_venda_logica(id, funcionario.id)

@app.post("/compras/registrar")
def post_compras_registrar(dados: CompraInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_inserir")
    return registrar_compra(dados, funcionario.id, "gerente" in funcionario.cargo.lower())

@app.post("/compras/encaminhar/{id}")
def post_compras_encaminhar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_encaminhar")
    return encaminhar_compra(id, funcionario.id)

@app.post("/compras/autorizar/{id}")
def post_compras_autorizar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_gerenciar")
    return autorizar_compra(id, funcionario.id)

@app.post("/compras/recusar/{id}")
def post_compras_recusar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_gerenciar")
    return recusar_compra(id, funcionario.id)

@app.post("/compras/cancelar/{id}")
def post_compras_cancelar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_cancelar")
    return cancelar_compra(id, funcionario.id)

@app.get("/compras/listar")
def get_compras_lista(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_ver")
    return listar_todas_compras()

@app.get("/compras/comprasdodia")
def get_compras_dia(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "compras_dia")
    return listar_compras_do_dia()

@app.post("/despesas/inserir")
def inserir_despesa(dados: DespesaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return criar_despesa(dados, funcionario.id)

@app.get("/vendas/dashboard-stats")
def dashboard_stats(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas_dia")
    return obter_estatisticas_dashboard()

@app.post("/pontos/bater")
def bater_ponto(
    data_manual: date = None, 
    hora_manual: datetime = None, 
    funcionario=Depends(get_funcionario)
):
    if funcionario.is_admin or "diretor" in funcionario.cargo.lower():
        raise HTTPException(
            status_code=400, 
            detail="Registro de ponto negado."
        )
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
    verificar_permissao(funcionario, "movimentacao")
    return listar_logs()

@app.post("/funcionarios/configurar-hierarquia")
def rota_configurar_hierarquia(dados: HierarquiaRequest, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "hierarquia")
    return configurar_hierarquia_funcionario(dados.funcionario_id, dados)

@app.post("/solicitacoes/criar")
def rota_criar_solicitacao(dados: SolicitacaoCompraCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "solicitacoes_criar")
    return criar_solicitacao(dados, funcionario.id)

@app.get("/solicitacoes/listar")
def rota_listar_solicitacoes(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "solicitacoes_ver")
    return listar_solicitacoes(funcionario)

@app.post("/solicitacoes/responder/{sol_id}")
def rota_responder_solicitacao(sol_id: int, dados: SolicitacaoCompraUpdate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "solicitacoes_responder")
    return responder_solicitacao(sol_id, dados, funcionario.id)

@app.post("/comunicados/criar")
def rota_criar_comunicado(dados: ComunicadoCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "comunicados_escrever")
    return criar_comunicado(dados, funcionario.id)

@app.get("/comunicados/listar")
def rota_listar_comunicados(funcionario=Depends(get_funcionario)):
    return listar_comunicados(funcionario.id)

@app.get("/comunicados/nao-lidos")
def rota_nao_lidos(funcionario=Depends(get_funcionario)):
    return contar_nao_lidos(funcionario.id)

@app.post("/comunicados/marcar-lido/{destinatario_id}")
def rota_marcar_lido(destinatario_id: int, funcionario=Depends(get_funcionario)):
    return marcar_como_lido(destinatario_id, funcionario.id)