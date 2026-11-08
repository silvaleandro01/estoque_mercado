# Estoque Mercado

Sistema de gestão de estoque e vendas para mercado, com controle de funcionários, compras, vendas, comunicados e folha de pagamento.

## Tecnologias

- **Backend:** FastAPI + SQLModel + MySQL
- **Frontend:** HTML, CSS, JavaScript (vanilla)
- **Autenticação:** JWT (python-jose) + bcrypt

## Estrutura

```
src/         → código-fonte do backend (Python)
frontend/    → interface web (HTML, CSS, JS)
```

## Instalação

```bash
# 1. Criar e ativar ambiente virtual
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Linux/Mac

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Configurar variáveis de ambiente
cp .env.exemplo .env
# edite o arquivo .env com suas credenciais

# 4. Iniciar o servidor
iniciar.bat                # Windows
cd src && uvicorn main:app --reload  # Linux/Mac
```

> **Produção:** defina `AMBIENTE=producao` no `.env` para desativar `/docs`, `/redoc` e `/openapi.json`. Essas rotas ficam abertas sem autenticação e expõem toda a estrutura da API; em desenvolvimento (padrão) elas continuam disponíveis.

## Testes

A suíte usa `pytest` com SQLite em memória (não precisa de MySQL rodando
nem de `.env` configurado).

```bash
# com o venv já ativado (ver Instalação acima)
pip install -r requirements-dev.txt

pytest
```

`requirements-dev.txt` inclui `requirements.txt` (dependências de produção)
mais `pytest` e `httpx` (usado pelo `TestClient` do FastAPI nos testes).

## Funcionalidades

- Cadastro e gestão de funcionários com controle de acesso por cargo
- Controle de estoque com entrada e saída de produtos
- Registro e aprovação de pedidos de compra
- Lançamento de vendas com diferentes métodos de pagamento
- Registro de ponto e fechamento de folha mensal
- Comunicados internos entre funcionários
- Dashboard com estatísticas de vendas e despesas
- Logs de movimentações

## Licença

MIT
