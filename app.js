const API_URL = "http://127.0.0.1:8000";

// Estado Local
let carrinho = [];

// --- Gerenciamento de Estado e Auth ---

function getToken() {
    return localStorage.getItem('api_token');
}

function login() {
    const token = document.getElementById('token-input').value;
    if (token) {
        localStorage.setItem('api_token', token);
        checkAuth();
    } else {
        alert('Por favor, insira um token.');
    }
}

function logout() {
    localStorage.removeItem('api_token');
    checkAuth();
}

function checkAuth() {
    const token = getToken();
    const loginScreen = document.getElementById('login-screen');
    const mainLayout = document.getElementById('main-layout');

    if (token) {
        loginScreen.classList.add('hidden');
        mainLayout.classList.remove('hidden');
        navegar('dashboard');
    } else {
        loginScreen.classList.remove('hidden');
        mainLayout.classList.add('hidden');
    }
}

// --- Utilitários de Requisição ---

async function apiFetch(endpoint, options = {}) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...options.headers
    };

    try {
        const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers });
        
        if (response.status === 401 || response.status === 403) {
            alert("Sessão expirada ou sem permissão.");
            if (response.status === 401) logout();
            return null;
        }

        return response.json();
    } catch (error) {
        console.error("Erro na API:", error);
        alert("Erro de conexão com o servidor.");
        return null;
    }
}

// --- Navegação ---

function navegar(viewId) {
    // Esconde todas as views
    document.querySelectorAll('.view').forEach(el => el.classList.add('hidden'));
    
    // Mostra a selecionada
    const target = document.getElementById(`view-${viewId}`);
    if (target) {
        target.classList.remove('hidden');
        carregarDadosView(viewId);
    }
}

function carregarDadosView(viewId) {
    if (viewId === 'estoque') carregarEstoque();
    if (viewId === 'vendas') carregarVendas();
    if (viewId === 'funcionarios') carregarFuncionarios();
}

// --- Lógica de Estoque ---

async function carregarEstoque() {
    const container = document.getElementById('view-estoque');
    container.innerHTML = '<h3>Carregando...</h3>';

    const produtos = await apiFetch('/estoque/mostrar');
    
    if (!produtos) {
        container.innerHTML = '<h3>Erro ao carregar estoque. Verifique suas permissões.</h3>';
        return;
    }

    let html = `
        <h2>Controle de Estoque</h2>
        <div class="card">
            <h3>Cadastrar Novo Produto</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="novo-prod-nome" placeholder="Nome do Produto">
                <input class="form-control" type="text" id="novo-prod-codigo" placeholder="Código de Barras">
                <input class="form-control" type="number" id="novo-prod-qtd" placeholder="Quantidade">
                <input class="form-control" type="number" id="novo-prod-preco" placeholder="Preço (R$)">
                <input class="form-control" type="text" id="novo-prod-cat" placeholder="Categoria">
            </div>
            <button onclick="adicionarProduto()">Salvar</button>
        </div>
        <div class="card">
        <h3>Produtos Cadastrados</h3>
        <table>
            <thead>
                <tr><th>ID</th><th>Produto</th><th>Cód. Barras</th><th>Qtd</th><th>Preço</th></tr>
            </thead>
            <tbody>
    `;

    produtos.forEach(p => {
        html += `
            <tr>
                <td>${p.id}</td>
                <td>${p.nomedoproduto}</td>
                <td>${p.codigodebarras}</td>
                <td>${p.quantidade}</td>
                <td>R$ ${p.preco}</td>
            </tr>
        `;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
}

async function adicionarProduto() {
    const dados = {
        nomedoproduto: document.getElementById('novo-prod-nome').value,
        codigodebarras: document.getElementById('novo-prod-codigo').value,
        quantidade: parseInt(document.getElementById('novo-prod-qtd').value),
        preco: parseFloat(document.getElementById('novo-prod-preco').value),
        categoria: document.getElementById('novo-prod-cat').value,
        titulo: document.getElementById('novo-prod-nome').value // Campo opcional
    };

    const res = await apiFetch('/estoque/inserir', {
        method: 'POST',
        body: JSON.stringify(dados)
    });

    if (res) {
        alert('Produto adicionado!');
        carregarEstoque();
    }
}

// --- Lógica de Vendas ---

async function carregarVendas() {
    const container = document.getElementById('view-vendas');
    
    // Busca vendas do dia (Backend)
    const vendasDia = await apiFetch('/vendas/vendasdodia');
    
    let totalHoje = 0;
    if (vendasDia && vendasDia.total_vendido) {
        totalHoje = vendasDia.total_vendido;
    }

    // Renderiza interface
    let html = `
        <h2>Vendas</h2>
        
        <div class="card" style="background-color: #e8f8f5; border-left: 5px solid #2ecc71;">
            <h3>Caixa do Dia: R$ ${totalHoje.toFixed(2)}</h3>
        </div>

        <div class="card">
            <h3>Nova Venda (PDV)</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="venda-codigo" placeholder="Código de Barras">
                <input class="form-control" type="number" id="venda-qtd" placeholder="Quantidade" value="1">
                <button onclick="adicionarAoCarrinho()">Adicionar Item</button>
            </div>

            <table id="tabela-carrinho">
                <thead>
                    <tr><th>Código</th><th>Qtd</th><th>Ação</th></tr>
                </thead>
                <tbody id="lista-carrinho">
                    <!-- Itens via JS -->
                </tbody>
            </table>

            <div class="total-venda" id="total-carrinho-display">Total: 0 itens</div>
            <br>
            <button class="btn-success" onclick="finalizarVenda()">Finalizar Venda</button>
        </div>
    `;

    container.innerHTML = html;
    atualizarCarrinhoUI();
}

function adicionarAoCarrinho() {
    const codigo = document.getElementById('venda-codigo').value;
    const qtd = parseInt(document.getElementById('venda-qtd').value);

    if (!codigo || qtd <= 0) {
        alert("Dados inválidos");
        return;
    }

    carrinho.push({ codigodebarras: codigo, quantidade: qtd });
    
    // Limpa inputs
    document.getElementById('venda-codigo').value = '';
    document.getElementById('venda-qtd').value = '1';
    document.getElementById('venda-codigo').focus();

    atualizarCarrinhoUI();
}

function atualizarCarrinhoUI() {
    const tbody = document.getElementById('lista-carrinho');
    const totalDisplay = document.getElementById('total-carrinho-display');
    
    if (!tbody) return;

    tbody.innerHTML = '';
    carrinho.forEach((item, index) => {
        tbody.innerHTML += `
            <tr>
                <td>${item.codigodebarras}</td>
                <td>${item.quantidade}</td>
                <td><button class="btn-danger" onclick="removerDoCarrinho(${index})">X</button></td>
            </tr>
        `;
    });

    totalDisplay.innerText = `Itens no carrinho: ${carrinho.length}`;
}

function removerDoCarrinho(index) {
    carrinho.splice(index, 1);
    atualizarCarrinhoUI();
}

async function finalizarVenda() {
    if (carrinho.length === 0) {
        alert("Carrinho vazio!");
        return;
    }

    const dados = { itens: carrinho };

    const res = await apiFetch('/vendas/inserir', {
        method: 'POST',
        body: JSON.stringify(dados)
    });

    if (res) {
        alert("Venda realizada com sucesso!");
        carrinho = [];
        carregarVendas(); // Recarrega para atualizar o total do dia
    }
}

// --- Lógica de Funcionários ---

async function carregarFuncionarios() {
    const container = document.getElementById('view-funcionarios');
    container.innerHTML = '<h3>Carregando...</h3>';

    const funcionarios = await apiFetch('/funcionarios/listar');
    
    if (!funcionarios) {
        container.innerHTML = `<div class="card"><h3>Acesso Negado</h3><p>Apenas RH ou Admin podem ver isso.</p></div>`;
        return;
    }

    let html = `
        <h2>Gestão de RH</h2>
        
        <div class="card">
            <h3>Cadastrar Novo Funcionário</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="func-nome" placeholder="Nome">
                <input class="form-control" type="text" id="func-sobrenome" placeholder="Sobrenome">
                <input class="form-control" type="date" id="func-nasc" placeholder="Data Nasc.">
                <select class="form-control" id="func-genero">
                    <option value="masculino">Masculino</option>
                    <option value="feminino">Feminino</option>
                    <option value="outro">Outro</option>
                </select>
                <select class="form-control" id="func-filhos">
                    <option value="false">Não tem filhos</option>
                    <option value="true">Tem filhos</option>
                </select>
                <input class="form-control" type="number" id="func-setor" placeholder="ID do Setor (1, 2...)">
            </div>
            <button onclick="criarFuncionario()">Cadastrar</button>
        </div>

        <div class="card">
        <h3>Equipe</h3>
        <table>
            <thead>
                <tr><th>ID</th><th>Nome</th><th>Setor ID</th><th>Admin</th></tr>
            </thead>
            <tbody>
    `;

    funcionarios.forEach(f => {
        html += `
            <tr>
                <td>${f.id}</td>
                <td>${f.nome} ${f.sobrenome}</td>
                <td>${f.setor_id}</td>
                <td>${f.is_admin ? 'Sim' : 'Não'}</td>
            </tr>
        `;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
}

async function criarFuncionario() {
    const dados = {
        nome: document.getElementById('func-nome').value,
        sobrenome: document.getElementById('func-sobrenome').value,
        data_nascimento: document.getElementById('func-nasc').value,
        genero: document.getElementById('func-genero').value,
        possui_filhos: document.getElementById('func-filhos').value === 'true',
        setor_id: parseInt(document.getElementById('func-setor').value)
    };

    const res = await apiFetch('/funcionarios/criar', {
        method: 'POST',
        body: JSON.stringify(dados)
    });

    if (res) {
        alert('Funcionário cadastrado!');
        carregarFuncionarios();
    }
}

// Inicialização
checkAuth();