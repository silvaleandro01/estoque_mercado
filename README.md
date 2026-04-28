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
