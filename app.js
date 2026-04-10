const API_URL = "http://127.0.0.1:8000";

let carrinho = [];
let pendingFuncionarioId = null;
let editandoFuncionarioId = null;
let editandoProdutoId = null;
let editandoSetorId = null;
let cacheFuncionarios = [];
let cacheProdutos = [];
let cacheSetores = [];
let carrinhoCompra = [];

window.login = async function () {
    const userEl = document.getElementById('user-input');
    const passEl = document.getElementById('pass-input');

    if (!userEl || !passEl) {
        alert("Erro técnico: Campos de entrada não localizados.");
        return;
    }
    const user = userEl.value.trim();
    const pass = passEl.value;
    if (!user) {
        alert('Por favor, insira seu usuário (nome.sobrenome).');
        return;
    }

    try {
        const res = await fetch(`${API_URL}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass })
        });

        let data = null;
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            data = await res.json();
        }

        if (!res.ok) {
            alert(data?.detail || "Usuário ou senha incorretos.");
            return;
        }

        if (data?.status === "primeiro_acesso" || data?.status === "senha_expirada") {
            pendingFuncionarioId = data?.funcionario_id;

            const loginScr = document.getElementById('login-screen');
            const pwdScr = document.getElementById('password-screen');

            if (loginScr && pwdScr) {
                loginScr.classList.add('hidden');
                pwdScr.classList.remove('hidden');
                if (document.getElementById('pwd-title'))
                    document.getElementById('pwd-title').innerText = data?.status === "primeiro_acesso" ? "Primeiro Acesso" : "Senha Expirada";
                if (document.getElementById('pwd-msg'))
                    document.getElementById('pwd-msg').innerText = "Defina sua senha de acesso.";
            } else {
                alert("Erro: Telas de transição não encontradas no HTML (login-screen ou password-screen).");
            }
        } else if (data?.status === "sucesso") {
            console.log("Login bem sucedido, token armazenado.");
            localStorage.setItem('api_token', data?.token);
            localStorage.setItem('user_setor', data?.setor);
            localStorage.setItem('is_admin', data?.is_admin);
            localStorage.setItem('user_cargo', data?.cargo);
            localStorage.setItem('bate_ponto', data?.bate_ponto);
            localStorage.setItem('nome_completo', data?.nome_completo || '');
            checkAuth();
        } else {
            alert("Servidor retornou um status desconhecido: " + data?.status);
        }
    } catch (err) {
        console.error("Erro catastrófico no login:", err);
        alert("Erro de conexão. Verifique se o servidor backend está ligado.");
    }
};

window.togglePassword = function (inputId) {
    const input = document.getElementById(inputId);
    input.type = input.type === "password" ? "text" : "password";
};

window.submeterNovaSenha = async function () {
    const novaSenha = document.getElementById('new-password').value;
    const confirmaSenha = document.getElementById('confirm-password').value;
    const feedback = document.getElementById('pwd-feedback');
    feedback.style.display = 'none';
    feedback.className = 'feedback-msg';
    if (novaSenha !== confirmaSenha) {
        feedback.innerText = "As senhas não coincidem!";
        feedback.style.display = 'block';
        return;
    }
    try {
        const res = await apiFetch('/funcionarios/definir-senha', {
            method: 'POST',
            body: JSON.stringify({ funcionario_id: pendingFuncionarioId, nova_senha: novaSenha })
        });
        if (res) {
            alert("Senha cadastrada com sucesso! Por favor, realize o login com sua nova senha.");
            document.getElementById('password-screen').classList.add('hidden');
            document.getElementById('login-screen').classList.remove('hidden');
            document.getElementById('new-password').value = '';
            document.getElementById('confirm-password').value = '';
            document.getElementById('pass-input').value = '';
            feedback.style.display = 'none';
            pendingFuncionarioId = null;
        } else {
            // apiFetch já exibe o alerta de erro, mas podemos adicionar feedback visual aqui
            feedback.innerText = "Erro ao definir senha. Verifique os requisitos.";
            feedback.className = 'feedback-msg feedback-error';
            feedback.style.display = 'block';
        }
    } catch (error) {
        alert("Erro de conexão com o servidor. Tente novamente.");
    }
};

window.logout = function () {
    localStorage.removeItem('api_token');
    checkAuth();
};

window.navegar = navegar;
window.adicionarProduto = adicionarProduto;
window.removerProduto = removerProduto;
window.prepararEdicaoEstoque = prepararEdicaoEstoque;
window.cancelarEdicaoEstoque = cancelarEdicaoEstoque;
window.cancelarVenda = cancelarVenda;
window.adicionarAoCarrinho = adicionarAoCarrinho;
window.baterPonto = baterPonto;
window.autorizarCompra = autorizarCompra;
window.cancelarCompra = cancelarCompra;
window.encaminharCompra = encaminharCompra;
window.recusarCompra = recusarCompra;

function getToken() {
    return localStorage.getItem('api_token');
}

function checkAuth() {
    const token = getToken();
    const loginScreen = document.getElementById('login-screen');
    const mainLayout = document.getElementById('main-layout');

    if (token) {
        loginScreen.classList.add('hidden');
        mainLayout.classList.remove('hidden');

        const isAdmin = localStorage.getItem('is_admin') === 'true';
        const setor = (localStorage.getItem('user_setor') || "").toLowerCase().trim();
        const cargo = (localStorage.getItem('user_cargo') || "operacional").toLowerCase().trim();
        const nomeCompleto = localStorage.getItem('nome_completo') || '';
        if (nomeCompleto) {
            document.getElementById('sidebar-user-name').innerText = `Mercado 24h - ${nomeCompleto}`;
        }

        const isDiretor = cargo.includes('direto');
        const isGerente = cargo.includes('gerente') || isDiretor || isAdmin;
        const batePonto = localStorage.getItem('bate_ponto') === 'true';
        const inVendas = setor.includes('vendas');
        const inEstoque = setor.includes('estoque');
        const inCompras = setor.includes('compras');
        const inGerencia = setor === 'gerencia' || setor === 'admin';
        const inRH = setor === 'rh';
        document.querySelectorAll('.sidebar ul li').forEach(li => {
            const acao = li.getAttribute('onclick') || "";
            let visivel = true;

            if (acao.includes("'pontos'")) {
                if (!batePonto || isAdmin || isDiretor) visivel = false;
            } else if (acao.includes("'funcionarios'")) {
                if (!isAdmin && !inRH && !isDiretor && !inGerencia) visivel = false;
            } else if (acao.includes("'estoque'")) {
                if (!isAdmin && !inEstoque && !isDiretor && !inGerencia) visivel = false;
            } else if (acao.includes("'compras-dia'")) {
                const isGerenteCompras = inCompras && cargo.includes('gerente');
                if (!isAdmin && !inGerencia && !isDiretor && !isGerenteCompras) visivel = false;
            } else if (acao.includes("'compras'")) {
                if (!isAdmin && !inCompras && !inGerencia && !isDiretor) visivel = false;
            } else if (acao.includes("'solicitacoes'")) {
                const isGerenteCompras = inCompras && cargo.includes('gerente');
                if (!isAdmin && !isDiretor && !isGerenteCompras) visivel = false;
            } else if (acao.includes("'movimentacao'")) {
                const isGerenteEstoque = inEstoque && cargo.includes('gerente');
                if (!isAdmin && !isDiretor && !isGerenteEstoque && !inGerencia) visivel = false;
            } else if (acao.includes("'vendas-dia'")) {
                if (!isAdmin && !isDiretor && !(inVendas && cargo.includes('gerente'))) visivel = false;
            } else if (acao.includes("'dashboard'")) {
                if (!isAdmin && !isDiretor) visivel = false;
            } else if (acao.includes("'despesas'")) {
                if (!isAdmin && !inRH && !inGerencia) visivel = false;
            } else if (acao.includes("'vendas'")) {
                if (!isAdmin && !inVendas && !inGerencia) visivel = false;
            }

            if (visivel) li.classList.remove('hidden');
            else li.classList.add('hidden');
        });

        if (batePonto) {
            navegar('pontos');
            verificarLembretePonto();
        } else if (isDiretor || isAdmin) {
            navegar('dashboard');
        } else {
            navegar('comunicados');
        }
        atualizarBadgeComunicados();
    } else {
        loginScreen.classList.remove('hidden');
        mainLayout.classList.add('hidden');
    }
}

async function apiFetch(endpoint, options = {}, silent = false) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...options.headers
    };

    try {
        const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers });

        let data = null;
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            data = await response.json();
        }

        if (!response.ok) {
            let errorMsg = `Erro ${response.status}`;
            if (data && data.detail) {
                errorMsg += `: ${typeof data.detail === 'object' ? JSON.stringify(data.detail) : data.detail}`;
            }

            if (response.status === 401) logout();
            else if (!silent) alert(errorMsg);
            return null;
        }

        return data;
    } catch (error) {
        if (!silent) alert("Erro de comunicação com o servidor.");
        return null;
    }
}

function navegar(viewId) {
    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const setor = (localStorage.getItem('user_setor') || "").toLowerCase().trim();
    const cargo = (localStorage.getItem('user_cargo') || "operacional").toLowerCase().trim();
    const isDiretor = cargo.includes('direto');

    if (viewId === 'pontos') {
        const batePonto = localStorage.getItem('bate_ponto') === 'true';
        if (!batePonto || isAdmin || isDiretor) return;
    }

    if (setor === 'rh' && !isAdmin && !isDiretor) {
        if (['vendas', 'vendas-dia', 'estoque', 'movimentacao'].includes(viewId)) {
            alert("Acesso restrito: Funcionários do RH só podem acessar o módulo de gestão de pessoal.");
            return;
        }
    }

    if (setor === 'compras' && !isAdmin) {
        if (['vendas', 'vendas-dia', 'estoque', 'rh', 'movimentacao'].includes(viewId)) {
            alert("Acesso restrito: Setor de compras não possui permissão para este módulo.");
            return;
        }
    }

    document.querySelectorAll('.view').forEach(el => el.classList.add('hidden'));
    
    const target = document.getElementById(`view-${viewId}`);
    if (target) {
        target.classList.remove('hidden');
        carregarDadosView(viewId);
    }
}

function carregarDadosView(viewId) {
    if (viewId === 'estoque') carregarEstoque();
    if (viewId === 'vendas') carregarVendas();
    if (viewId === 'vendas-dia') carregarVendasDia();
    if (viewId === 'funcionarios') carregarFuncionarios();
    if (viewId === 'movimentacao') carregarMovimentacao();
    if (viewId === 'pontos') carregarPontos();
    if (viewId === 'dashboard') carregarDashboard();
    if (viewId === 'compras') carregarCompras();
    if (viewId === 'compras-dia') carregarComprasDia();
    if (viewId === 'despesas') carregarDespesas();
    if (viewId === 'comunicados') carregarComunicados();
    if (viewId === 'solicitacoes') carregarSolicitacoes();
}

async function carregarEstoque() {
    const container = document.getElementById('view-estoque');
    container.innerHTML = '<h3>Carregando...</h3>';

    const produtos = await apiFetch('/estoque/mostrar');
    cacheProdutos = produtos || [];
    
    if (!produtos) {
        container.innerHTML = '<h3>Erro ao carregar estoque. Verifique suas permissões.</h3>';
        return;
    }

    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const cargo = (localStorage.getItem('user_cargo') || "").toLowerCase().trim();
    const setor = (localStorage.getItem('user_setor') || "").toLowerCase().trim();

    const isDiretor = cargo.includes('direto');
    const isSetorEstoque = setor === 'estoque';
    const isGerenteEstoque = isSetorEstoque && cargo.includes('gerente');
    const podeCadastrar = isAdmin || isSetorEstoque;
    const podeEditar = isAdmin || isGerenteEstoque;

    let html = `
        <h2>Controle de Estoque</h2>
        ${isDiretor && !isAdmin ? `
        <div class="card" style="border-left: 5px solid #f39c12; background: #fefdf0;">
            <p style="margin:0; color: #7d6608;">
                <strong>Modo somente leitura.</strong> Para solicitar alterações no estoque, use a aba Solicitações de Compra.
            </p>
        </div>` : ''}
        ${isSetorEstoque && !isGerenteEstoque && !isAdmin ? `
        <div class="card" style="border-left: 5px solid #3498db; background: #f0f8ff;">
            <p style="margin:0; color: #1a5276;">
                Você pode <strong>adicionar novos produtos</strong> ou <strong>incrementar quantidade</strong> de produtos existentes. Edição e exclusão são funções do gerente do setor.
            </p>
        </div>` : ''}
        ${podeCadastrar ? `<div class="card">
            <h3 id="form-estoque-title">Cadastrar Novo Produto</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="novo-prod-nome" placeholder="Nome do Produto">
                <input class="form-control" type="text" id="novo-prod-codigo" placeholder="Código de Barras">
                <input class="form-control" type="number" id="novo-prod-qtd" placeholder="Quantidade">
                <input class="form-control" type="number" id="novo-prod-preco" placeholder="Preço (R$)">
                <input class="form-control" type="text" id="novo-prod-cat" placeholder="Categoria">
            </div>
            <div id="estoque-btn-container">
                <button class="btn-success" onclick="adicionarProduto()">Salvar Produto</button>
            </div>
        </div>` : ''}
        <div class="card">
        <h3>Produtos Cadastrados</h3>
        <table>
            <thead>
                <tr><th>ID</th><th>Produto</th><th>Cód. Barras</th><th>Qtd</th><th>Preço</th>${podeEditar ? '<th>Ações</th>' : ''}</tr>
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
                ${podeEditar ? `<td>
                    <button class="btn" style="padding: 5px; font-size: 0.7rem; background: #ff9800; color: white;" onclick="prepararEdicaoEstoque(${p.id})">Editar</button>
                    <button class="btn-danger" style="padding: 5px; font-size: 0.7rem;" onclick="removerProduto(${p.id})">Excluir</button>
                </td>` : ''}
            </tr>
        `;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
}

async function removerProduto(id) {
    if (!confirm("Tem certeza que deseja excluir este item permanentemente do estoque?")) return;
    if (await apiFetch(`/estoque/deletar/${id}`, { method: 'DELETE' })) {
        carregarEstoque();
    }
}

async function carregarMovimentacao() {
    const container = document.getElementById('view-movimentacao');
    container.innerHTML = '<h3>Carregando histórico...</h3>';
    
    const logs = await apiFetch('/logs');
    if (!logs) return;

    let html = `
        <h2>Movimentação de Estoque</h2>
        <div class="card">
            <h3>Histórico de Ações</h3>
            <table>
                <thead>
                    <tr><th>Data/Hora</th><th>Funcionário ID</th><th>Ação</th></tr>
                </thead>
                <tbody>
                    ${logs.map(l => `
                        <tr>
                            <td>${new Date(l.data_hora).toLocaleString()}</td>
                            <td>${l.funcionario_id}</td>
                            <td>${l.tipo_movimentacao}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
    container.innerHTML = html;
}

function prepararEdicaoEstoque(id) {
    const p = cacheProdutos.find(prod => prod.id === id);
    if (!p) return;

    editandoProdutoId = p.id;
    document.getElementById('form-estoque-title').innerText = `Editando: ${p.nomedoproduto}`;
    document.getElementById('novo-prod-nome').value = p.nomedoproduto;
    document.getElementById('novo-prod-codigo').value = p.codigodebarras;
    document.getElementById('novo-prod-qtd').value = p.quantidade;
    document.getElementById('novo-prod-preco').value = p.preco;
    document.getElementById('novo-prod-cat').value = p.categoria;

    const btnContainer = document.getElementById('estoque-btn-container');
    btnContainer.innerHTML = `
        <button class="btn-success" onclick="adicionarProduto()">Atualizar Produto</button>
        <button class="btn" onclick="cancelarEdicaoEstoque()">Cancelar</button>
    `;
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function cancelarEdicaoEstoque() {
    editandoProdutoId = null;
    document.getElementById('form-estoque-title').innerText = "Cadastrar Novo Produto";
    const btnContainer = document.getElementById('estoque-btn-container');
    btnContainer.innerHTML = `<button class="btn-success" onclick="adicionarProduto()">Salvar Produto</button>`;
    carregarEstoque();
}

async function adicionarProduto() {
    const dados = {
        nomedoproduto: document.getElementById('novo-prod-nome').value,
        codigodebarras: document.getElementById('novo-prod-codigo').value,
        quantidade: parseInt(document.getElementById('novo-prod-qtd').value),
        preco: parseFloat(document.getElementById('novo-prod-preco').value),
        categoria: document.getElementById('novo-prod-cat').value,
        titulo: document.getElementById('novo-prod-nome').value
    };

    let res;
    if (editandoProdutoId) {
        res = await apiFetch(`/estoque/atualizar/${editandoProdutoId}`, {
            method: 'PUT',
            body: JSON.stringify(dados)
        });
    } else {
        res = await apiFetch('/estoque/inserir', {
            method: 'POST',
            body: JSON.stringify(dados)
        });
    }

    if (res) {
        alert(editandoProdutoId ? 'Produto atualizado!' : 'Produto adicionado!');
        cancelarEdicaoEstoque();
    }
}

async function carregarDashboard() {
    const container = document.getElementById('view-dashboard');
    container.innerHTML = '<h3>Processando inteligência de dados...</h3>';
    
    if (!window.Chart) {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js';
        document.head.appendChild(script);
        await new Promise(r => script.onload = r);
    }

    const stats = await apiFetch('/vendas/dashboard-stats');
    if (!stats) return;

    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const cargo = (localStorage.getItem('user_cargo') || "").toLowerCase();
    const setor = (localStorage.getItem('user_setor') || "").toLowerCase();
    const isDirecao = isAdmin || cargo.includes('direto');
    const showFinanceiro = isDirecao || setor.includes('vendas') || setor.includes('gerencia');
    const periodos = [
        { key: "diario", label: "Diário" },
        { key: "semanal", label: "Semanal" },
        { key: "mensal", label: "Mensal" },
        { key: "bimestral", label: "Bimestral" },
        { key: "trimestral", label: "Trimestral" },
        { key: "semestral", label: "Semestral" },
        { key: "anual", label: "Anual" }
    ];
    const faturamentos = periodos.map(p => stats[p.key].faturamento);
    const lucros = periodos.map(p => stats[p.key].lucro_liquido);
    const investimentos = periodos.map(p => stats[p.key].investimento);

    container.innerHTML = `
        <h2>Dashboard Executivo</h2>
        <div class="card"><canvas id="chartLucro" style="max-height: 300px;"></canvas></div>
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h3>Relatórios de Performance</h3>
                <button class="btn-success" onclick="exportarDashboardCSV()">Exportar para CSV</button>
            </div>
            <table>
                <thead>
                    <tr><th>Período</th>${showFinanceiro ? '<th>Vendas</th><th>Faturamento</th>' : ''}<th>Invest. Compras</th><th>Despesas</th>${showFinanceiro ? '<th>Lucro Líquido</th>' : ''}</tr>
                </thead>
                <tbody>
                    ${periodos.map(p => `<tr>
                        <td><strong>${p.label}</strong></td>
                        ${showFinanceiro ? `<td>${stats[p.key].vendas_count}</td><td>R$ ${stats[p.key].faturamento.toFixed(2)}</td>` : ''}
                        <td style="color: #c0392b">R$ ${stats[p.key].investimento.toFixed(2)}</td>
                        <td style="color: #e74c3c">R$ ${stats[p.key].despesas.toFixed(2)}</td>
                        ${showFinanceiro ? `<td style="color: #27ae60">R$ ${stats[p.key].lucro_liquido.toFixed(2)}</td>` : ""}
                        </tr>`).join('')}
                </tbody>
            </table>
        </div>
    `;

    const datasets = [
        { label: 'Investimento Estoque', data: investimentos, backgroundColor: '#e67e22' },
        { label: 'Despesas', data: periodos.map(p => stats[p.key].despesas), backgroundColor: '#e74c3c' }
    ];
    if (showFinanceiro) {
        datasets.unshift({ label: 'Faturamento', data: faturamentos, backgroundColor: '#3498db' });
        datasets.push({ label: 'Lucro Líquido', data: lucros, backgroundColor: '#27ae60' });
    }

    new Chart(document.getElementById('chartLucro'), {
        type: 'bar',
        data: {
            labels: periodos.map(p => p.label),
            datasets: datasets
        },
        options: { responsive: true, maintainAspectRatio: false }
    });

    window.cacheDashboardStats = stats;
}

function exportarDashboardCSV() {
    const stats = window.cacheDashboardStats;
    if (!stats) return;
    let csv = "Periodo,Vendas,Faturamento,Lucro Liquido\n";
    Object.keys(stats).forEach(k => {
        csv += `${k},${stats[k].vendas_count},${stats[k].faturamento},${stats[k].lucro_liquido}\n`;
    });
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.setAttribute('hidden', '');
    a.setAttribute('href', url);
    a.setAttribute('download', `relatorio_diretoria_${new Date().getTime()}.csv`);
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function carregarComprasDia() {
    const container = document.getElementById('view-compras-dia');
    container.innerHTML = '<h3>Carregando...</h3>';
    const res = await apiFetch('/compras/comprasdodia');
    if (!res) return;
    container.innerHTML = `
        <h2>Compras do Dia (Saídas)</h2>
        <div class="card" style="background: #fdfefe; border-left: 5px solid #34495e;">
            <h3>Resumo de Investimento</h3>
            <p>Data: <strong>${new Date(res.data).toLocaleDateString()}</strong></p>
            <p>Total Autorizado: <strong style="font-size: 1.5rem; color: #c0392b;">R$ ${res.total.toFixed(2)}</strong></p>
        </div>
    `;
}

async function carregarVendas() {
    const container = document.getElementById('view-vendas');
    const produtos = await apiFetch('/estoque/mostrar');
    cacheProdutos = produtos || [];

    let html = `
        <h2>Terminal de Vendas</h2>
        <div id="container-pdv" class="card">
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
                </tbody>
            </table>

            <div class="total-venda" id="total-carrinho-display">Total: R$ 0.00 (0 itens)</div>
            <br>
            <button class="btn-success" onclick="abrirMenuPagamento()">Ir para o Pagamento</button>
        </div>
        <div id="container-pagamento" class="card hidden"></div>
    `;

    container.innerHTML = html;
    atualizarCarrinhoUI();
}

async function carregarVendasDia() {
    const container = document.getElementById('view-vendas-dia');
    container.innerHTML = '<h3>Carregando dados do caixa...</h3>';
    const vendasDia = await apiFetch('/vendas/vendasdodia');
    if (!vendasDia) return;

    container.innerHTML = `
        <h2>Vendas do Dia</h2>
        <div class="card" style="background-color: #e8f8f5; border-left: 5px solid #2ecc71;">
            <h3>Resumo Financeiro</h3>
            <p>Data: <strong>${new Date(vendasDia.data || vendasDia.dat).toLocaleDateString()}</strong></p>
            <p>Total Vendido: <strong style="font-size: 1.5rem; color: #27ae60;">R$ ${vendasDia.total_vendido.toFixed(2)}</strong></p>
        </div>
        <div class="card">
            <h3>Listagem de Vendas</h3>
            <table>
                <thead><tr><th>ID</th><th>Hora</th><th>Total</th><th>Ações</th></tr></thead>
                <tbody>
                    ${vendasDia.lista.map(v => `
                        <tr>
                            <td>#${v.id}</td>
                            <td>${new Date(v.data).toLocaleTimeString()}</td>
                            <td>R$ ${v.valor_total.toFixed(2)}</td>
                            <td><button class="btn-danger" onclick="cancelarVenda(${v.id})">Cancelar Venda</button></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function cancelarVenda(id) {
    if (!confirm("Deseja cancelar esta venda? O estoque será devolvido.")) return;
    if (await apiFetch(`/vendas/cancelar/${id}`, { method: 'DELETE' })) carregarVendasDia();
}

function adicionarAoCarrinho() {
    const codigo = document.getElementById('venda-codigo').value.trim();
    const qtd = parseInt(document.getElementById('venda-qtd').value);

    if (!codigo || qtd <= 0) {
        alert("Dados inválidos");
        return;
    }

    const produto = cacheProdutos.find(p => p.codigodebarras.toString().trim() == codigo);
    if (!produto) {
        alert("Erro: Este produto não está cadastrado no sistema.");
        return;
    }

    carrinho.push({ codigodebarras: codigo, quantidade: qtd });
    
    document.getElementById('venda-codigo').value = '';
    document.getElementById('venda-qtd').value = '1';
    document.getElementById('venda-codigo').focus();

    atualizarCarrinhoUI();
}

function atualizarCarrinhoUI() {
    const tbody = document.getElementById('lista-carrinho');
    const totalDisplay = document.getElementById('total-carrinho-display');
    
    if (!tbody || !totalDisplay) return;

    let total = 0.0;
    tbody.innerHTML = '';
    carrinho.forEach((item, index) => {
        const p = cacheProdutos.find(prod => prod.codigodebarras.toString().trim() == item.codigodebarras.toString().trim());
        const nome = p ? p.nomedoproduto : "Produto não identificado";
        const preco = p ? p.preco : 0;
        total += preco * item.quantidade;

        tbody.innerHTML += `
            <tr>
                <td>${nome}<br><small>${item.codigodebarras}</small></td>
                <td>${item.quantidade}</td>
                <td><button class="btn-danger" onclick="removerDoCarrinho(${index})">X</button></td>
            </tr>
        `;
    });

    totalDisplay.innerHTML = `Total: <strong>R$ ${total.toFixed(2)}</strong> (${carrinho.length} itens)`;
}

function abrirMenuPagamento() {
    if (carrinho.length === 0) return alert("Carrinho vazio!");

    let total = 0.0;
    carrinho.forEach(item => {
        const p = cacheProdutos.find(prod => prod.codigodebarras.toString().trim() == item.codigodebarras.toString().trim());
        total += (p ? p.preco : 0) * item.quantidade;
    });

    const pdv = document.getElementById('container-pdv');
    const pgto = document.getElementById('container-pagamento');
    pdv.classList.add('hidden');
    pgto.classList.remove('hidden');

    pgto.innerHTML = `
        <h3>Finalizar Pagamento</h3>
        <p style="font-size: 1.2rem;">Valor Total: <strong>R$ ${total.toFixed(2)}</strong></p>
        <div class="form-group">
            <label>Selecione a forma de pagamento:</label>
            <select class="form-control" id="select-metodo" onchange="atualizarOpcoesPagamento(${total})">
                <option value="dinheiro">Dinheiro</option>
                <option value="debito">Cartão de Débito</option>
                <option value="credito">Cartão de Crédito</option>
                <option value="pix">PIX</option>
            </select>
        </div>
        <div id="detalhes-pagamento" class="form-group"></div>
        <div style="margin-top: 20px; display: flex; gap: 10px;">
            <button class="btn-success" onclick="processarVenda(${total})">Confirmar Pagamento</button>
            <button class="btn-danger" onclick="cancelarPagamento()">Voltar ao Carrinho</button>
        </div>
    `;
    atualizarOpcoesPagamento(total);
}

function atualizarOpcoesPagamento(total) {
    const metodo = document.getElementById('select-metodo').value;
    const detalhes = document.getElementById('detalhes-pagamento');
    detalhes.innerHTML = '';

    if (metodo === 'dinheiro') {
        detalhes.innerHTML = `
            <label>Valor Recebido:</label>
            <input type="number" class="form-control" id="valor-recebido" placeholder="0.00" oninput="calcularTroco(${total})">
            <p id="troco-display" style="margin-top:10px; font-weight:bold; color: #2c3e50;"></p>
        `;
    } else if (metodo === 'credito') {
        let options = '<option value="1">1x (À vista)</option>';
        if (total >= 50) {
            options += '<option value="2">2x</option>';
            options += '<option value="3">3x</option>';
        }
        detalhes.innerHTML = `
            <label>Parcelamento (Mín. R$ 50 p/ parcelar):</label>
            <select class="form-control" id="select-parcelas">${options}</select>
        `;
    } else if (metodo === 'pix') {
        detalhes.innerHTML = `
            <div style="text-align:center; padding: 10px; border: 2px dashed #2ecc71;">
                <p>Escaneie o QR Code abaixo:</p>
                <img src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=MERCADO24H_PAGAMENTO_${total}" style="margin: 10px auto; display: block;">
                <p style="font-size:0.8rem; margin-top:5px;">Aguardando confirmação bancária (Simulado)</p>
            </div>
        `;
    }
}

function calcularTroco(total) {
    const recebido = parseFloat(document.getElementById('valor-recebido').value) || 0;
    const display = document.getElementById('troco-display');
    if (recebido >= total) {
        display.innerText = `Troco: R$ ${(recebido - total).toFixed(2)}`;
        display.style.color = '#27ae60';
    } else {
        display.innerText = `Faltam: R$ ${(total - recebido).toFixed(2)}`;
        display.style.color = '#e74c3c';
    }
}

function cancelarPagamento() {
    document.getElementById('container-pdv').classList.remove('hidden');
    document.getElementById('container-pagamento').classList.add('hidden');
}

async function processarVenda(total) {
    const metodo = document.getElementById('select-metodo').value;
    const parcelas = metodo === 'credito' ? parseInt(document.getElementById('select-parcelas').value) : 1;

    if (metodo === 'dinheiro') {
        const recebido = parseFloat(document.getElementById('valor-recebido').value) || 0;
        if (recebido < total) return alert("Valor recebido insuficiente!");
    }

    const dados = {
        itens: carrinho,
        metodo_pagamento: metodo,
        parcelas: parcelas
    };

    const res = await apiFetch('/vendas/inserir', {
        method: 'POST',
        body: JSON.stringify(dados)
    });

    if (res) {
        alert("Venda Processada!");
        emitirNotaFiscal(res, metodo, parcelas);
        carrinho = [];
        carregarVendas();
    }
}

function emitirNotaFiscal(venda, metodo, parcelas) {
    if (!venda || !venda.itens) {
        alert("Erro ao gerar dados da nota fiscal.");
        return;
    }
    const win = window.open('', '_blank', 'height=600,width=400');
    if (!win) return alert("Pop-up bloqueado! Ative os pop-ups para ver a nota fiscal.");
    
    let itensHtml = '';
    venda.itens.forEach(i => {
        const nome = i.nomedoproduto || "Produto";
        const preco = Number(i.preco_total) || 0;
        const unitario = Number(i.preco_unitario) || 0;

        itensHtml += `<tr><td>${nome}<br><small>${i.codigodebarras}</small></td><td>${i.quantidade}x</td><td>R$ ${unitario.toFixed(2)}</td><td>R$ ${preco.toFixed(2)}</td></tr>`;
    });

    const totalFinal = Number(venda.valor_total) || 0;
    const dataVenda = venda.data ? new Date(venda.data).toLocaleString() : new Date().toLocaleString();

    win.document.write(`
        <html>
        <head><title>Cupom Fiscal</title><style>body{font-family:monospace;padding:20px;font-size:12px;}.line{border-bottom:1px dashed #000;margin:5px 0;}.text-center{text-align:center;}</style></head>
        <body>
            <div class="text-center">
                <strong>MERCADO 24H</strong><br>CNPJ: 00.000.000/0001-00<br>Rua de Teste, 123
            </div>
            <div class="line"></div>
            <p>DATA: ${dataVenda}</p>
            <p>VENDA ID: ${venda.id}</p>
            <div class="line"></div>
            <table style="width:100%;">
                <thead><tr><th align="left">PRODUTO</th><th align="left">QTD</th><th align="left">UNIT</th><th align="left">TOTAL</th></tr></thead>
                <tbody>${itensHtml}</tbody>
            </table>
            <div class="line"></div>
            <p align="right"><strong>VALOR TOTAL: R$ ${totalFinal.toFixed(2)}</strong></p>
            <p>FORMA PGTO: ${metodo.toUpperCase()} ${parcelas > 1 ? `(${parcelas}X)` : ''}</p>
            <div class="line"></div>
            <div class="text-center">OBRIGADO PELA PREFERENCIA!</div>
        </body>
        </html>
    `);
    win.document.close();
}

async function carregarCompras() {
    const container = document.getElementById('view-compras');
    const [produtos, compras] = await Promise.all([
        apiFetch('/estoque/mostrar'),
        apiFetch('/compras/listar')
    ]);
    cacheProdutos = produtos || [];
    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const cargo = (localStorage.getItem('user_cargo') || "").toLowerCase();
    const setor = (localStorage.getItem('user_setor') || "").toLowerCase();
    const isDiretor = cargo.includes('direto') || isAdmin;
    const isGerenteCompras = setor.includes('compras') && cargo.includes('gerente') && !isDiretor;
    const isOperacionalCompras = setor.includes('compras') && !isGerenteCompras && !isDiretor;

    const corStatus = { autorizada: '#27ae60', pendente: '#f39c12', aguardando_diretor: '#3498db', recusada: '#e74c3c', cancelada: '#95a5a6' };
    const labelStatus = { autorizada: 'AUTORIZADA', pendente: 'PENDENTE', aguardando_diretor: 'AGUARD. DIRETOR', recusada: 'RECUSADA', cancelada: 'CANCELADA' };

    const renderBotoesAcao = (c) => {
        let btns = '';
        if (isDiretor && c.status === 'aguardando_diretor') {
            btns += `<button class="btn-success" style="padding:5px;" onclick="autorizarCompra(${c.id})">✅ Aprovar</button> `;
            btns += `<button class="btn-danger" style="padding:5px;" onclick="recusarCompra(${c.id})">❌ Recusar</button>`;
        }
        if (isGerenteCompras) {
            if (c.status === 'pendente') {
                btns += `<button class="btn-success" style="padding:5px; background:#3498db;" onclick="encaminharCompra(${c.id})">📤 Encaminhar ao Diretor</button> `;
                btns += `<button class="btn-danger" style="padding:5px;" onclick="cancelarCompra(${c.id})">Cancelar</button>`;
            } else if (c.status === 'aguardando_diretor') {
                btns += `<button class="btn-danger" style="padding:5px;" onclick="cancelarCompra(${c.id})">Cancelar</button>`;
            }
        }
        return btns || '-';
    };

    const tabelaHistorico = `
        <div class="card">
            <h3>Histórico de Pedidos</h3>
            <table>
                <thead><tr><th>ID</th><th>Data</th><th>Total</th><th>Status</th><th>Ações</th></tr></thead>
                <tbody>
                    ${(compras || []).map(c => `
                        <tr>
                            <td>#${c.id}</td>
                            <td>${new Date(c.data).toLocaleString()}</td>
                            <td>R$ ${c.valor_total.toFixed(2)}</td>
                            <td><span class="badge" style="background:${corStatus[c.status] || '#95a5a6'}">${labelStatus[c.status] || c.status.toUpperCase()}</span></td>
                            <td>${renderBotoesAcao(c)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;

    let html = `<h2>Gestão de Compras</h2>`;

    if (isDiretor) {
        html += `
        <div class="card" style="border-left:5px solid #3498db; background:#f0f8ff;">
            <p style="margin:0; color:#1a5276;"><strong>Painel do Diretor:</strong> Pedidos com status <em>Aguardando Diretor</em> requerem sua decisão.</p>
        </div>
        ${tabelaHistorico}`;
    } else if (isGerenteCompras) {
        html += `
        <div class="card">
            <h3>Registrar Novo Pedido de Compra</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="compra-codigo" placeholder="Cód. Barras" onchange="verificarNovoProdutoCompra()">
                <input class="form-control" type="number" id="compra-qtd" placeholder="Qtd" value="1">
                <input class="form-control" type="number" id="compra-custo" placeholder="Preço Custo Unit. (R$)">
                <div id="campos-novo-produto" class="hidden" style="width:100%; border:1px dashed #3498db; padding:10px; margin-top:10px;">
                    <p style="color:#3498db; font-size:0.8rem;">Produto novo! Preencha os dados básicos:</p>
                    <input class="form-control" type="text" id="compra-nome" placeholder="Nome do Produto">
                    <input class="form-control" type="number" id="compra-venda" placeholder="Preço Sugerido Venda (R$)">
                    <input class="form-control" type="text" id="compra-cat" placeholder="Categoria">
                </div>
                <button class="btn-success" onclick="adicionarItemCompra()">Adicionar ao Pedido</button>
            </div>
            <table class="card">
                <thead><tr><th>Produto</th><th>Qtd</th><th>Custo Unit.</th><th>Total</th><th>Ação</th></tr></thead>
                <tbody id="lista-carrinho-compra"></tbody>
            </table>
            <div style="text-align:right; margin-top:10px;">
                <button class="btn-success" onclick="enviarPedidoCompra()">Salvar Pedido (Pendente)</button>
            </div>
        </div>
        ${tabelaHistorico}`;
    } else if (isOperacionalCompras) {
        html += `
        <div class="card">
            <h3>Montar Catálogo de Compras</h3>
            <p style="font-size:0.85rem; color:#666;">Monte o pedido e envie ao gerente para análise. Você não pode editar ou excluir pedidos já enviados.</p>
            <div class="form-group">
                <input class="form-control" type="text" id="compra-codigo" placeholder="Cód. Barras" onchange="verificarNovoProdutoCompra()">
                <input class="form-control" type="number" id="compra-qtd" placeholder="Qtd" value="1">
                <input class="form-control" type="number" id="compra-custo" placeholder="Preço Custo Unit. (R$)">
                <div id="campos-novo-produto" class="hidden" style="width:100%; border:1px dashed #3498db; padding:10px; margin-top:10px;">
                    <p style="color:#3498db; font-size:0.8rem;">Produto novo! Preencha os dados básicos:</p>
                    <input class="form-control" type="text" id="compra-nome" placeholder="Nome do Produto">
                    <input class="form-control" type="number" id="compra-venda" placeholder="Preço Sugerido Venda (R$)">
                    <input class="form-control" type="text" id="compra-cat" placeholder="Categoria">
                </div>
                <button class="btn-success" onclick="adicionarItemCompra()">Adicionar ao Pedido</button>
            </div>
            <table class="card">
                <thead><tr><th>Produto</th><th>Qtd</th><th>Custo Unit.</th><th>Total</th><th>Ação</th></tr></thead>
                <tbody id="lista-carrinho-compra"></tbody>
            </table>
            <div style="text-align:right; margin-top:10px;">
                <button class="btn-success" onclick="enviarPedidoCompra()">Enviar ao Gerente</button>
            </div>
        </div>`;
    }

    container.innerHTML = html;
    atualizarCarrinhoCompraUI();
}

async function encaminharCompra(id) {
    if (!confirm("Encaminhar este pedido ao diretor para aprovação?")) return;
    const res = await apiFetch(`/compras/encaminhar/${id}`, { method: 'POST' });
    if (res) { alert(res.msg); carregarCompras(); }
}

async function recusarCompra(id) {
    if (!confirm("Confirmar RECUSA deste pedido de compra?")) return;
    const res = await apiFetch(`/compras/recusar/${id}`, { method: 'POST' });
    if (res) { alert(res.msg); carregarCompras(); }
}

function verificarNovoProdutoCompra() {
    const codigo = document.getElementById('compra-codigo').value.trim();
    const camposNovos = document.getElementById('campos-novo-produto');
    const prod = cacheProdutos.find(p => p.codigodebarras == codigo);
    if (codigo && !prod) camposNovos.classList.remove('hidden');
    else camposNovos.classList.add('hidden');
}

function adicionarItemCompra() {
    const codigo = document.getElementById('compra-codigo').value.trim();
    const qtd = parseInt(document.getElementById('compra-qtd').value);
    const custo = parseFloat(document.getElementById('compra-custo').value);
    if (!codigo || isNaN(qtd) || isNaN(custo)) return alert("Preencha os campos obrigatórios.");
    const prodExistente = cacheProdutos.find(p => p.codigodebarras == codigo);
    const item = {
        codigodebarras: codigo,
        quantidade: qtd,
        preco_custo: custo,
        nomedoproduto: prodExistente ? prodExistente.nomedoproduto : document.getElementById('compra-nome').value,
        preco_venda: prodExistente ? prodExistente.preco : parseFloat(document.getElementById('compra-venda').value),
        categoria: prodExistente ? prodExistente.categoria : document.getElementById('compra-cat').value
    };
    carrinhoCompra.push(item);
    limparCamposCompra();
    atualizarCarrinhoCompraUI();
}

function atualizarCarrinhoCompraUI() {
    const tbody = document.getElementById('lista-carrinho-compra');
    if (!tbody) return;
    tbody.innerHTML = carrinhoCompra.map((i, index) => `
        <tr>
            <td>${i.nomedoproduto}<br><small>${i.codigodebarras}</small></td>
            <td>${i.quantidade}</td>
            <td>R$ ${i.preco_custo.toFixed(2)}</td>
            <td>R$ ${(i.quantidade * i.preco_custo).toFixed(2)}</td>
            <td><button class="btn-danger" onclick="carrinhoCompra.splice(${index},1); atualizarCarrinhoCompraUI();">X</button></td>
        </tr>
    `).join('');
}

async function enviarPedidoCompra() {
    if (carrinhoCompra.length === 0) return alert("Pedido vazio.");
    const res = await apiFetch('/compras/registrar', {
        method: 'POST',
        body: JSON.stringify({ itens: carrinhoCompra })
    });
    if (res) {
        alert(res.status === 'autorizada' ? "Compra realizada e estoque atualizado!" : "Pedido enviado para autorização do gerente.");
        carrinhoCompra = [];
        carregarCompras();
    }
}

async function autorizarCompra(id) {
    const res = await apiFetch(`/compras/autorizar/${id}`, { method: 'POST' });
    if (res) {
        alert("Compra autorizada e estoque abastecido.");
        carregarCompras();
    }
}

async function cancelarCompra(id) {
    if (confirm("Confirmar recusa deste pedido?") && await apiFetch(`/compras/cancelar/${id}`, { method: 'POST' })) {
        carregarCompras();
    }
}

function limparCamposCompra() {
    document.getElementById('compra-codigo').value = '';
    document.getElementById('compra-qtd').value = '1';
    document.getElementById('compra-custo').value = '';
    document.getElementById('compra-nome').value = '';
    document.getElementById('compra-venda').value = '';
    document.getElementById('compra-cat').value = '';
    document.getElementById('campos-novo-produto').classList.add('hidden');
}

async function carregarDespesas() {
    const container = document.getElementById('view-despesas');
    let html = `
        <h2>Controle de Despesas Operacionais</h2>
        <div class="card">
            <h3>Lançar Nova Despesa</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="despesa-desc" placeholder="Descrição (ex: Aluguel, Energia)">
                <input class="form-control" type="number" id="despesa-valor" placeholder="Valor (R$)">
                <select class="form-control" id="despesa-cat">
                    <option value="Fixo">Fixo</option>
                    <option value="Variavel">Variável</option>
                    <option value="Manutencao">Manutenção</option>
                    <option value="Outros">Outros</option>
                </select>
                <button class="btn-danger" onclick="lancarDespesa()">Registrar Saída</button>
            </div>
        </div>
    `;
    container.innerHTML = html;
}

async function lancarDespesa() {
    const dados = {
        descricao: document.getElementById('despesa-desc').value,
        valor: parseFloat(document.getElementById('despesa-valor').value),
        categoria: document.getElementById('despesa-cat').value
    };
    if (!dados.descricao || isNaN(dados.valor)) return alert("Preencha todos os campos.");
    const res = await apiFetch('/despesas/inserir', {
        method: 'POST',
        body: JSON.stringify(dados)
    });
    if (res) {
        alert("Despesa registrada com sucesso!");
        document.getElementById('despesa-desc').value = '';
        document.getElementById('despesa-valor').value = '';
    }
}

function removerDoCarrinho(index) {
    carrinho.splice(index, 1);
    atualizarCarrinhoUI();
}



function formatarHorasRelogio(decimal) {
    if (decimal === null || decimal === undefined || isNaN(decimal)) return "00:00";
    const sinal = decimal < 0 ? "-" : "";
    const valorAbsoluto = Math.abs(decimal);
    const horas = Math.floor(valorAbsoluto);
    const minutos = Math.round((valorAbsoluto - horas) * 60);
    const horasFinal = minutos === 60 ? horas + 1 : horas;
    const minutosFinal = minutos === 60 ? 0 : minutos;
    return `${sinal}${horasFinal.toString().padStart(2, '0')}:${minutosFinal.toString().padStart(2, '0')}`;
}

function formatarDataSimples(dataStr) {
    if (!dataStr) return "--/--/----";
    const partes = dataStr.split('T')[0].split('-');
    return `${partes[2]}/${partes[1]}/${partes[0]}`;
}

async function carregarFuncionarios() {
    const container = document.getElementById('view-funcionarios');
    container.innerHTML = '<h3>Carregando...</h3>';

    const data = new Date();
    const mes = data.getMonth() + 1;
    const ano = data.getFullYear();

    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const userSetor = (localStorage.getItem('user_setor') || "").toLowerCase().trim();
    const isRH = userSetor === 'rh' || isAdmin;

    const [funcionarios, setores, pontosGerais] = await Promise.all([
        apiFetch('/funcionarios/listar'),
        apiFetch('/setores/listar'),
        apiFetch(`/pontos/rh/geral?mes=${mes}&ano=${ano}`)
    ]);
    
    cacheFuncionarios = funcionarios || [];
    cacheSetores = setores || [];

    if (!funcionarios) {
        container.innerHTML = `<div class="card"><h3>Acesso Negado</h3><p>Apenas RH ou Admin podem ver isso.</p></div>`;
        return;
    }

    const listaSetores = setores || [];

    let html = `
        <div id="rh-dashboard">
        <h2>Gestão de RH</h2>
        ${isRH ? `
        <div class="card" style="background: #f8f9fa; border-left: 5px solid #2c3e50;">
            <h3>Fechamento de Folha</h3>
            <div class="form-group" style="display:flex; gap:10px; align-items:center;">
                <input type="number" id="fechar-mes" value="${mes}" class="form-control" style="width: 80px;">
                <input type="number" id="fechar-ano" value="${ano}" class="form-control" style="width: 100px;">
                <button class="btn-danger" onclick="fecharFolhaMensal()">Encerrar Folha e Gerar Holerites</button>
            </div>
        </div>` : ''}

        <div class="card">
            <h3>Setores Existentes</h3>
            <table>
                <thead>
                    <tr><th>ID</th><th>Nome</th><th>Tipo</th><th>Ação</th></tr>
                </thead>
                <tbody>
                    ${listaSetores.map(s => `
                        <tr>
                            <td>${s.id}</td>
                            <td>${s.nome}</td>
                            <td>${s.tipo.charAt(0).toUpperCase() + s.tipo.slice(1)}</td>
                            <td>
                                ${s.tipo !== 'admin' && isRH ? `
                                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem; background: #ff9800; color: white;" onclick="prepararEdicaoSetor(${s.id})">Editar</button>
                                    <button class="btn-danger" style="padding: 5px 10px; font-size: 0.8rem;" onclick="removerSetor(${s.id})">Excluir</button>
                                ` : `<span class="badge">Apenas Leitura</span>`}
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        ${isRH ? `
        <div class="card">
            <h3 id="form-setor-title">Cadastrar Novo Setor</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="setor-nome-novo" placeholder="Nome do Setor (ex: Vendas)">
                <input class="form-control" type="text" id="setor-tipo-novo" placeholder="Tipo (ex: vendas, estoque, rh)">
            </div>
            <div id="setor-btn-container">
                <button onclick="criarSetor()">Cadastrar Setor</button>
            </div>
        </div>` : ''}
        
        ${isRH ? `
        <div class="card">
            <h3 id="form-func-title">Cadastrar Novo Funcionário</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="func-nome" placeholder="Nome">
                <input class="form-control" type="text" id="func-sobrenome" placeholder="Sobrenome">
                <label style="font-size:0.8rem; color: #666;">Data de Nascimento:</label>
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
                <select class="form-control" id="func-setor">
                    <option value="">Selecione o Setor</option>
                    ${listaSetores.filter(s => s.tipo !== 'admin').map(s => `<option value="${s.id}">${s.nome} (${s.tipo})</option>`).join('')}
                </select>
                <select class="form-control" id="func-cargo">
                    <option value="operacional">Operacional</option>
                    <option value="gerente de setor">Gerente de Setor</option>
                    <option value="diretoria">Diretoria</option>
                </select>
                <div style="display:flex; align-items:center; gap:5px; padding: 5px;">
                    <input type="checkbox" id="func-admin" style="width: 20px; height: 20px;">
                    <label for="func-admin" style="font-size: 0.9rem;">Privilégios de Administrador</label>
                </div>
                <div style="display:flex; align-items:center; gap:5px; padding: 5px;">
                    <input type="checkbox" id="func-bate-ponto" style="width: 20px; height: 20px;" checked>
                    <label for="func-bate-ponto" style="font-size: 0.9rem;">Bate Ponto</label>
                </div>
                <input class="form-control" type="number" id="func-salario" placeholder="Salário Mensal (R$)">
            </div>
            <div id="func-btn-container">
                <button class="btn-success" onclick="criarFuncionario()" id="btn-salvar-func">Cadastrar</button>
            </div>
        </div>` : ''}

        <div class="card">
            <h3>Equipe</h3>
            <table>
                <thead>
                    <tr><th>ID</th><th>Nome</th><th>Setor</th><th>Cargo</th><th>Admin</th><th>Ações</th></tr>
                </thead>
                <tbody>`;

    funcionarios.forEach(f => {
        const setor = listaSetores.find(s => s.id === f.setor_id);
        html += `
            <tr>
                <td>${f.id}</td>
                <td>${f.nome} ${f.sobrenome}</td>
                <td>${setor ? setor.nome : f.setor_id}</td>
                <td>${f.cargo.charAt(0).toUpperCase() + f.cargo.slice(1)}</td>
                <td>${f.is_admin ? 'Sim' : 'Não'}</td>
                <td>
                    ${isRH ? `<button class="btn" style="padding: 5px 10px; font-size: 0.8rem; background: #ff9800; color: white;"
                        onclick="prepararEdicaoFuncionario(${f.id})">Editar</button>` : ""}
                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem;" 
                        onclick="verRelatorioPontoIndividual(${f.id}, '${(f.nome + ' ' + f.sobrenome).replace(/'/g, "\\\\'")}')">Ver Ponto Mensal</button>
                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem; background: #673ab7; color: white;" 
                        onclick="verHoleriteRH(${f.id}, '${(f.nome + ' ' + f.sobrenome).replace(/'/g, "\\\\'")}')">Holerite</button>
                    ${isRH ? `<button class="btn-success" style="padding: 5px 10px; font-size: 0.8rem;" 
                        onclick="abrirGerenciamentoSalario(${f.id}, '${(f.nome + ' ' + f.sobrenome).replace(/'/g, "\\\\'")}')">$ Salário</button>` : ""}
                </td>
            </tr>
        `;
    });

    html += `</tbody></table></div>
        <div class="card">
            <h3>Controle de Ponto Geral</h3>
            <table>
                <thead>
                    <tr><th>Data</th><th>Funcionário</th><th>Entrada</th><th>Saída</th><th>Trabalhadas</th><th>Extras</th><th>Saldo</th></tr>
                </thead>
                <tbody>
                    ${(pontosGerais || []).map(p => `
                        <tr>
                            <td>${formatarDataSimples(p.data)}</td>
                            <td>${p.funcionario}</td>
                            <td>${p.entrada ? new Date(p.entrada).toLocaleTimeString() : '--'}</td>
                            <td>${p.saida ? new Date(p.saida).toLocaleTimeString() : '--'}</td>
                            <td>${formatarHorasRelogio(p.trabalhadas)}</td>
                            <td><span style="color: green">${p.extras > 0 ? '+' + formatarHorasRelogio(p.extras) : '00:00'}</span></td>
                            <td>
                                <strong style="color: ${(p.extras - p.devidas) >= 0 ? '#27ae60' : '#e74c3c'}">${formatarHorasRelogio(p.extras - p.devidas)}</strong>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    </div>
    <div id="detalhe-ponto-individual" class="hidden"></div>
    <div id="gerenciamento-salario-individual" class="hidden"></div>`;

    container.innerHTML = html;
}

function prepararEdicaoFuncionario(id) {
    const f = cacheFuncionarios.find(emp => emp.id === id);
    if (!f) return alert("Erro ao localizar dados do funcionário.");

    editandoFuncionarioId = f.id;
    document.getElementById('form-func-title').innerText = `Editando: ${f.nome} ${f.sobrenome}`;
    
    document.getElementById('func-nome').value = f.nome;
    document.getElementById('func-sobrenome').value = f.sobrenome;
    document.getElementById('func-nasc').value = f.data_nascimento;
    document.getElementById('func-genero').value = f.genero;
    document.getElementById('func-filhos').value = f.possui_filhos.toString();
    document.getElementById('func-setor').value = f.setor_id;
    document.getElementById('func-cargo').value = f.cargo;
    document.getElementById('func-admin').checked = f.is_admin;
    document.getElementById('func-bate-ponto').checked = f.bate_ponto;

    document.getElementById('func-salario').style.display = 'none';
    
    const btnContainer = document.getElementById('func-btn-container');
    btnContainer.innerHTML = `
        <button class="btn-success" onclick="criarFuncionario()">Salvar Alterações</button>
        <button class="btn" onclick="cancelarEdicaoFuncionario()">Cancelar</button>
    `;
    
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function cancelarEdicaoFuncionario() {
    editandoFuncionarioId = null;
    document.getElementById('form-func-title').innerText = "Cadastrar Novo Funcionário";
    
    document.getElementById('func-nome').value = '';
    document.getElementById('func-sobrenome').value = '';
    document.getElementById('func-nasc').value = '';
    document.getElementById('func-salario').value = '';
    document.getElementById('func-salario').style.display = 'block';
    document.getElementById('func-admin').checked = false;
    
    const btnContainer = document.getElementById('func-btn-container');
    btnContainer.innerHTML = `<button class="btn-success" onclick="criarFuncionario()" id="btn-salvar-func">Cadastrar</button>`;
}

async function fecharFolhaMensal() {
    const mes = parseInt(document.getElementById('fechar-mes').value);
    const ano = parseInt(document.getElementById('fechar-ano').value);
    
    if (!confirm(`Deseja realmente fechar a folha de ${mes}/${ano}? Isso irá consolidar os valores de todos os funcionários.`)) return;

    const res = await apiFetch('/folha/fechar', {
        method: 'POST',
        body: JSON.stringify({ mes: parseInt(mes), ano: parseInt(ano) })
    });
    
    if (res) {
        alert(res.detail);
    }
}

async function abrirGerenciamentoSalario(id, nome) {
    const container = document.getElementById('gerenciamento-salario-individual');
    const dashboard = document.getElementById('rh-dashboard');
    if (dashboard) dashboard.classList.add('hidden');
    
    container.classList.remove('hidden');
    container.innerHTML = '<h3>Processando...</h3>';
    const historico = await apiFetch(`/funcionarios/salario-historico/${id}`) || [];

    container.innerHTML = `
        <div class="card" style="border-top: 5px solid #27ae60;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>Gestão Salarial: ${nome}</h3>
                <button class="btn-danger" onclick="fecharJanelaIndividual('gerenciamento-salario-individual')">Voltar</button>
            </div>
            
            <div class="card" style="background: #f9f9f9; margin: 20px 0;">
                <h4>Alterar Salário Atual</h4>
                <div class="form-group" style="display: flex; gap: 10px;">
                    <input type="number" id="novo-valor-salario" class="form-control" placeholder="Novo Salário Mensal (R$)">
                    <button class="btn-success" onclick="confirmarAlteracaoSalario(${id}, '${nome}')">Atualizar Salário</button>
                </div>
            </div>

            <h4>Tabela de Evolução Salarial</h4>
            <table>
                <thead>
                    <tr><th>Data da Alteração</th><th>Valor Anterior</th><th>Novo Valor</th></tr>
                </thead>
                <tbody>
                    ${historico.length > 0 ? historico.map(h => `
                        <tr>
                            <td>${new Date(h.data_alteracao).toLocaleString()}</td>
                            <td>R$ ${h.valor_antigo.toFixed(2)}</td>
                            <td><strong>R$ ${h.valor_novo.toFixed(2)}</strong></td>
                        </tr>
                    `).join('') : '<tr><td colspan="3">Nenhum histórico registrado.</td></tr>'}
                </tbody>
            </table>
        </div>
    `;
}

async function confirmarAlteracaoSalario(id, nome) {
    const valor = document.getElementById('novo-valor-salario').value;
    if (!valor || valor <= 0) return alert("Insira um valor válido.");

    if (!confirm(`Confirma a alteração do salário de ${nome} para R$ ${parseFloat(valor).toFixed(2)}?`)) return;

    const res = await apiFetch('/funcionarios/definir-salario', {
        method: 'POST',
        body: JSON.stringify({ funcionario_id: id, valor: parseFloat(valor) })
    });
    if (res) {
        alert("Salário atualizado com sucesso!");
        abrirGerenciamentoSalario(id, nome);
    }
}

async function verRelatorioPontoIndividual(id, nomeCompleto) {
    const container = document.getElementById('detalhe-ponto-individual');
    const dashboard = document.getElementById('rh-dashboard');
    if (dashboard) dashboard.classList.add('hidden');
    
    container.classList.remove('hidden');
    container.innerHTML = '<h3>Carregando...</h3>';
    const agora = new Date();
    const mes = agora.getMonth() + 1;
    const ano = agora.getFullYear();

    const relatorio = await apiFetch(`/pontos/rh/funcionario/${id}?mes=${mes}&ano=${ano}`);
    
    if (!relatorio) return;

    const formatarHora = (iso) => iso ? new Date(iso).toLocaleTimeString() : '--:--';

    let html = `
        <div class="card" style="border-top: 5px solid #3498db; animation: fadeIn 0.5s;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>Relatório Detalhado: ${nomeCompleto} (${mes}/${ano})</h3>
                <button class="btn-danger" onclick="fecharJanelaIndividual('detalhe-ponto-individual')">Voltar</button>
            </div>
            
            <div style="display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap;">
                <div class="ponto-stamp">Trabalhado:<br><strong>${formatarHorasRelogio(relatorio.resumo.total_trabalhado_mes)}</strong></div>
                <div class="ponto-stamp">Extras:<br><strong style="color: green">+${formatarHorasRelogio(relatorio.resumo.total_extra_mes)}</strong></div>
                <div class="ponto-stamp">Devidas:<br><strong style="color: red">${relatorio.resumo.total_devido_mes > 0 ? '-' : ''}${formatarHorasRelogio(relatorio.resumo.total_devido_mes)}</strong></div>
                <div class="ponto-stamp">Saldo Mensal:<br><strong style="color: ${relatorio.resumo.saldo_mensal >= 0 ? (relatorio.resumo.saldo_mensal > 0 ? '#27ae60' : '#333') : '#e74c3c'}">
                    ${formatarHorasRelogio(relatorio.resumo.saldo_mensal)}
                </strong></div>
                <div class="ponto-stamp" style="background: #27ae60; color: #fff;">Total a Receber:<br><strong>R$ ${relatorio.resumo.total_a_receber.toLocaleString('pt-BR', {minimumFractionDigits: 2})}</strong></div>
            </div>

            <table>
                <thead>
                    <tr><th>Data</th><th>Entrada</th><th>Almoço</th><th>Retorno</th><th>Saída</th><th>Extras</th><th>Devidas</th><th>Ganho do Dia</th></tr>
                </thead>
                <tbody>
                    ${(relatorio.pontos || []).map(p => `
                        <tr>
                            <td>${formatarDataSimples(p.data)}</td>
                            <td>${formatarHora(p.entrada)}</td>
                            <td>${formatarHora(p.saida_almoco)}</td>
                            <td>${formatarHora(p.retorno_almoco)}</td>
                            <td>${formatarHora(p.saida)}</td>
                            <td style="color: green">${p.horas_extras > 0 ? '+' + formatarHorasRelogio(p.horas_extras) : '00:00'}</td>
                            <td style="color: red">${p.horas_devidas > 0 ? '-' + formatarHorasRelogio(p.horas_devidas) : '00:00'}</td>
                            <td><strong>R$ ${p.valor_monetario.toFixed(2)}</strong></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
    
    container.innerHTML = html;
    container.scrollIntoView({ behavior: 'smooth' });
}

function fecharJanelaIndividual(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = '';
        container.classList.add('hidden');
    }
    const dashboard = document.getElementById('rh-dashboard');
    if (dashboard) dashboard.classList.remove('hidden');
}

function prepararEdicaoSetor(id) {
    const s = cacheSetores.find(sec => sec.id === id);
    if (!s) return;

    editandoSetorId = s.id;
    document.getElementById('form-setor-title').innerText = `Editando Setor: ${s.nome}`;
    document.getElementById('setor-nome-novo').value = s.nome;
    document.getElementById('setor-tipo-novo').value = s.tipo;

    const btnContainer = document.getElementById('setor-btn-container');
    btnContainer.innerHTML = `
        <button class="btn-success" onclick="criarSetor()">Salvar Alterações</button>
        <button class="btn" onclick="cancelarEdicaoSetor()">Cancelar</button>
    `;
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function cancelarEdicaoSetor() {
    editandoSetorId = null;
    document.getElementById('form-setor-title').innerText = "Cadastrar Novo Setor";
    document.getElementById('setor-nome-novo').value = '';
    document.getElementById('setor-tipo-novo').value = '';
    const btnContainer = document.getElementById('setor-btn-container');
    btnContainer.innerHTML = `<button onclick="criarSetor()">Cadastrar Setor</button>`;
}

async function criarSetor() {
    const dados = {
        nome: document.getElementById('setor-nome-novo').value,
        tipo: document.getElementById('setor-tipo-novo').value
    };

    if (!dados.nome || !dados.tipo) {
        alert("Preencha todos os campos do setor.");
        return;
    }

    let res;
    if (editandoSetorId) {
        res = await apiFetch(`/setores/${editandoSetorId}`, {
            method: 'PUT',
            body: JSON.stringify(dados)
        });
    } else {
        res = await apiFetch('/setores/criar', {
            method: 'POST',
            body: JSON.stringify(dados)
        });
    }

    if (res) {
        alert(editandoSetorId ? 'Setor atualizado com sucesso!' : 'Setor criado com sucesso!');
        cancelarEdicaoSetor();
        carregarFuncionarios();
    }
}

async function removerSetor(id) {
    if (!confirm("Deseja realmente excluir este setor?")) return;
    const res = await apiFetch(`/setores/${id}`, { method: 'DELETE' });
    if (res) {
        alert(res.msg || "Setor removido!");
        carregarFuncionarios();
    }
}

async function criarFuncionario() {
    const setorId = document.getElementById('func-setor').value;
    if (!setorId) {
        alert("Selecione um setor válido.");
        return;
    }

    const dados = {
        nome: document.getElementById('func-nome').value,
        sobrenome: document.getElementById('func-sobrenome').value,
        data_nascimento: document.getElementById('func-nasc').value,
        genero: document.getElementById('func-genero').value,
        possui_filhos: document.getElementById('func-filhos').value === 'true',
        setor_id: parseInt(setorId),
        cargo: document.getElementById('func-cargo').value,
        is_admin: document.getElementById('func-admin').checked,
        bate_ponto: document.getElementById('func-bate-ponto').checked,
        cargo_confianca: document.getElementById('func-cargo').value.includes('direto'),
        valor_mensal: parseFloat(document.getElementById('func-salario').value) || 0
    };

    let res;
    if (editandoFuncionarioId) {
        res = await apiFetch(`/funcionarios/atualizar/${editandoFuncionarioId}`, {
            method: 'PUT',
            body: JSON.stringify(dados)
        });
    } else {
        res = await apiFetch('/funcionarios/criar', {
            method: 'POST',
            body: JSON.stringify(dados)
        });
    }

    if (res) {
        alert(editandoFuncionarioId ? 'Cadastro atualizado!' : 'Funcionário cadastrado!');
        cancelarEdicaoFuncionario();
        carregarFuncionarios();
    }
}

async function verificarLembretePonto() {
    const batePonto = localStorage.getItem('bate_ponto') === 'true';
    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const cargo = (localStorage.getItem('user_cargo') || '').toLowerCase();
    const isDiretor = cargo.includes('direto');
    if (!batePonto || isAdmin || isDiretor) return;
    const status = await apiFetch('/pontos/status');
    if (!status || !status.entrada) alert("Atenção: Você ainda não bateu o ponto de entrada hoje!");
}

async function carregarPontos() {
    const container = document.getElementById('view-pontos');
    container.innerHTML = '<h3>Carregando...</h3>';
    
    const agora = new Date();
    const mes = agora.getMonth() + 1;
    const ano = agora.getFullYear();

    const [status, relatorio, holerite] = await Promise.all([
        apiFetch('/pontos/status'),
        apiFetch(`/pontos/meu-relatorio?mes=${mes}&ano=${ano}`),
        apiFetch(`/folha/meu-holerite?mes=${mes}&ano=${ano}`, {}, true)
    ]);
    
    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const userCargo = (localStorage.getItem('user_cargo') || "").toLowerCase();
    const isDiretoria = userCargo.includes('direto');
    const podeBaterPonto = !isDiretoria && !isAdmin;
    const hojeStr = agora.toLocaleDateString();

    if (relatorio && relatorio.funcionario) {
        document.getElementById('sidebar-user-name').innerText = `Mercado 24h - ${relatorio.funcionario}`;
    }

    const fH = (iso) => iso ? new Date(iso).toLocaleTimeString() : '--:--';

    let holeriteHtml = '<p>Nenhum holerite fechado para o mês anterior.</p>';
    if (holerite && holerite.id) {
        window._ultimoHolerite = holerite;
        
        let btnAssinar = '';
        if (!holerite.assinado) {
            btnAssinar = `<button class="btn-success" onclick="assinarHolerite(${holerite.id})">Assinar Agora</button>`;
        } else {
            const dA = new Date(holerite.data_assinatura).toLocaleDateString();
            btnAssinar = `<span style="color: #27ae60; font-weight: bold;">✓ Assinado em ${dA}</span>`;
        }

        holeriteHtml = `
            <div style="border: 1px solid #ddd; padding: 15px; border-radius: 8px;">
                <div style="display:flex; justify-content: space-between; align-items: center;">
                    <div>
                        <p>Mês de Referência: <strong>${holerite.mes}/${holerite.ano}</strong></p>
                        <p>Valor Líquido: <strong style="color: #27ae60; font-size: 1.2rem;">R$ ${Number(holerite.valor_liquido || 0).toFixed(2)}</strong></p>
                    </div>
                    <div style="display: flex; gap: 10px;">
                        ${btnAssinar}
                        <button class="btn" onclick="gerarPDFHolerite(window._ultimoHolerite)">Baixar PDF</button>
                    </div>
                </div>
            </div>`;
    }

    const statusExp = status?.saida ? 'Expediente Encerrado' : 'Em Aberto';
    const btnTxt = !podeBaterPonto ? 'Ponto não requerido' : (status?.saida ? 'Expediente Finalizado' : 'Bater Próximo Ponto');
    const btnDis = (status?.saida || !podeBaterPonto) ? 'disabled' : '';

    let html = `
        <h2>Ponto Eletrônico - ${relatorio?.funcionario || 'Carregando...'} - ${hojeStr}</h2>
        <div class="card" style="text-align: center;">
            <div class="form-group" style="display: flex; justify-content: center; gap: 20px; margin-bottom: 20px;">
                <div class="ponto-stamp">Entrada:<br><strong>${fH(status?.entrada)}</strong></div>
                <div class="ponto-stamp">Almoço:<br><strong>${fH(status?.saida_almoco)}</strong></div>
                <div class="ponto-stamp">Retorno:<br><strong>${fH(status?.retorno_almoco)}</strong></div>
                <div class="ponto-stamp">Saída:<br><strong>${fH(status?.saida)}</strong></div>
            </div>
            
            <div style="margin: 20px 0;">
                <p>Status: <strong>${statusExp}</strong></p>
                <p>Horas Hoje: ${formatarHorasRelogio(status?.horas_trabalhadas)} | Extras: ${formatarHorasRelogio(status?.horas_extras)}</p>
            </div>
            <button class="btn-success" onclick="baterPonto()" ${btnDis}>${btnTxt}</button>
        </div>

        <div class="card">
            <h3>Meu Histórico Mensal (${mes}/${ano})</h3>
            <div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;">
                <div class="ponto-stamp">Total Horas:<br><strong>${formatarHorasRelogio(relatorio?.resumo?.total_trabalhado_mes)}</strong></div>
                <div class="ponto-stamp">Banco Extras:<br><strong style="color: green">+${formatarHorasRelogio(relatorio?.resumo?.total_extra_mes)}</strong></div>
                <div class="ponto-stamp">Banco Horas Devidas:<br><strong style="color: red">${relatorio?.resumo?.total_devido_mes > 0 ? '-' : ''}${formatarHorasRelogio(relatorio?.resumo?.total_devido_mes)}</strong></div>
                <div class="ponto-stamp">Saldo Final:<br><strong style="color: ${relatorio?.resumo?.saldo_mensal >= 0 ? (relatorio?.resumo?.saldo_mensal > 0 ? '#27ae60' : '#333') : '#e74c3c'}">${formatarHorasRelogio(relatorio?.resumo?.saldo_mensal)}</strong></div>
                <div class="ponto-stamp" style="background: #27ae60; color: white;">Previsão Salarial:<br><strong>R$ ${relatorio?.resumo?.total_a_receber?.toFixed(2) || '0.00'}</strong></div>
            </div>
            <table>
                <thead><tr><th>Data</th><th>Entrada</th><th>Almoço</th><th>Retorno</th><th>Saída</th><th>Extra</th><th>Devido</th></tr></thead>
                <tbody>
                    ${(relatorio?.pontos || []).map(p => `
                    <tr>
                        <td>${formatarDataSimples(p.data)}</td>
                        <td>${fH(p.entrada)}</td>
                        <td>${fH(p.saida_almoco)}</td>
                        <td>${fH(p.retorno_almoco)}</td>
                        <td>${fH(p.saida)}</td>
                        <td style="color: green">${p.horas_extras > 0 ? '+' + formatarHorasRelogio(p.horas_extras) : '00:00'}</td>
                        <td style="color: red">${p.horas_devidas > 0 ? '-' + formatarHorasRelogio(p.horas_devidas) : '00:00'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
        </div>

        <div class="card">
            <h3>Meu Holerite Digital</h3>
            ${holeriteHtml}
        </div>`;

    container.innerHTML = html;
}

async function verHoleriteRH(id, nome) {
    const agora = new Date();
    const mes = prompt("Informe o mês do holerite (1-12):", agora.getMonth() + 1);
    const ano = prompt("Informe o ano do holerite:", agora.getFullYear());
    
    if (!mes || !ano) return;

    const holerite = await apiFetch(`/folha/buscar-funcionario?funcionario_id=${id}&mes=${mes}&ano=${ano}`, {}, false);
    if (holerite && holerite.id) {
        gerarPDFHolerite(holerite);
    } else {
        alert("Holerite não encontrado para este período.");
    }
}

async function assinarHolerite(id) {
    if (!confirm("Ao assinar, você confirma o recebimento dos valores e a exatidão das horas. Deseja continuar?")) return;
    const res = await apiFetch(`/folha/assinar/${id}`, { method: 'POST' });
    if (res) {
        alert("Holerite assinado!");
        carregarPontos();
    }
}

function gerarPDFHolerite(h) {
    const win = window.open('', '', 'height=700,width=800');
    const html = `
        <html>
        <head><title>Holerite - ${h.mes}/${h.ano}</title>
        <style>
            body { font-family: sans-serif; padding: 20px; }
            .header { text-align: center; border-bottom: 2px solid #000; margin-bottom: 20px; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            .total { font-weight: bold; background: #eee; }
        </style>
        </head>
        <body>
            <div class="header">
                <h1>Recibo de Pagamento de Salário</h1>
                <p>Mercado 24h - Holerite Digital</p>
            </div>
            <p>Funcionário ID: ${h.funcionario_id} | Competência: ${new Date(h.data_competencia + 'T00:00:00').toLocaleDateString('pt-BR', {month: 'long', year: 'numeric'})}</p>
            <p>Dias Base: ${h.dias_trabalhados} dias</p>
            <table>
                <thead><tr><th>Descrição</th><th>Proventos</th><th>Descontos</th></tr></thead>
                <tbody>
                    <tr><td>Salário Base</td><td>R$ ${h.salario_base.toFixed(2)}</td><td>-</td></tr>
                    <tr><td>Horas Extras (50%)</td><td>R$ ${h.horas_extras_valor.toFixed(2)}</td><td>-</td></tr>
                    <tr><td>Ajuda de Custo</td><td>R$ ${h.ajuda_custo.toFixed(2)}</td><td>-</td></tr>
                    <tr><td>INSS</td><td>-</td><td>R$ ${h.inss.toFixed(2)}</td></tr>
                    <tr><td>IRPF</td><td>-</td><td>R$ ${h.irpf.toFixed(2)}</td></tr>
                    <tr><td>Vale Transporte (6%)</td><td>-</td><td>R$ ${h.vale_transporte.toFixed(2)}</td></tr>
                    <tr><td>Adiantamento (Vale)</td><td>-</td><td>R$ ${h.adiantamento.toFixed(2)}</td></tr>
                    <tr><td>Contribuição Assistencial</td><td>-</td><td>R$ ${h.contribuicao_assistencial.toFixed(2)}</td></tr>
                    <tr class="total"><td>TOTAIS</td><td>R$ ${(h.valor_bruto + h.ajuda_custo).toFixed(2)}</td><td>R$ ${(h.valor_bruto + h.ajuda_custo - h.valor_liquido).toFixed(2)}</td></tr>
                </tbody>
            </table>
            <h3 style="text-align: right;">VALOR LÍQUIDO: R$ ${h.valor_liquido.toFixed(2)}</h3>
            <div style="margin-top: 50px; border-top: 1px solid #000; text-align: center;">
                <p>Emissão: ${new Date(h.data_emissao).toLocaleString()}</p>
                ${h.assinado ? `<p style="color: green; font-weight: bold;">DOCUMENTO ASSINADO DIGITALMENTE PELO FUNCIONÁRIO</p>` : `<p style="color: red;">AGUARDANDO ASSINATURA</p>`}
            </div>
        </body>
        </html>
    `;
    win.document.write(html);
    win.document.close();
    win.print();
}

async function baterPonto() {
    const res = await apiFetch('/pontos/bater', { method: 'POST' });
    if (res) {
        alert(res.detail);
        carregarPontos();
    }
}

async function carregarSolicitacoes() {
    const container = document.getElementById('view-solicitacoes');
    container.innerHTML = '<h3>Carregando...</h3>';

    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const cargo = (localStorage.getItem('user_cargo') || '').toLowerCase();
    const setor = (localStorage.getItem('user_setor') || '').toLowerCase();
    const isDiretor = isAdmin || cargo.includes('direto');
    const isGerenteCompras = setor.includes('compras') && cargo.includes('gerente') && !isDiretor;

    const solicitacoes = await apiFetch('/solicitacoes/listar');
    if (!solicitacoes) return;

    const corStatus = { pendente: '#f39c12', em_andamento: '#3498db', concluida: '#27ae60', recusada: '#e74c3c' };
    const labelStatus = { pendente: 'PENDENTE', em_andamento: 'EM ANDAMENTO', concluida: 'CONCLUÍDA', recusada: 'RECUSADA' };

    let formHtml = '';
    if (isDiretor) {
        formHtml = `
        <div class="card">
            <h3>Nova Solicitação de Compra</h3>
            <p style="font-size:0.85rem; color:#666;">Descreva o que precisa ser comprado. O gerente de compras receberá uma notificação.</p>
            <div class="form-group">
                <input class="form-control" type="text" id="sol-titulo" placeholder="Título (ex: Reposição de higiene)">
                <textarea class="form-control" id="sol-descricao" rows="2" placeholder="Descrição geral da necessidade..." style="resize:vertical;"></textarea>
                <textarea class="form-control" id="sol-itens" rows="4" placeholder="Itens solicitados (ex:&#10;- 50x Papel Higiênico&#10;- 20x Sabão em Pó)" style="resize:vertical;"></textarea>
            </div>
            <button class="btn-success" onclick="enviarSolicitacao()">Enviar ao Gerente de Compras</button>
        </div>`;
    }

    const lista = (solicitacoes || []).map(s => `
        <div class="card" style="border-left:5px solid ${corStatus[s.status] || '#bdc3c7'};">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px;">
                <div style="flex:1;">
                    <h4 style="margin:0 0 4px;">#${s.id} — ${s.titulo}</h4>
                    <small style="color:#888;">Solicitado por: <strong>${s.diretor}</strong> &nbsp;|&nbsp; ${new Date(s.data_criacao).toLocaleString()}</small>
                    <p style="margin:10px 0 4px;"><strong>Descrição:</strong> ${s.descricao}</p>
                    ${s.resposta ? `<p style="margin:8px 0 0; padding:8px; background:#f8f9fa; border-radius:4px;"><strong>Resposta do Gerente:</strong> ${s.resposta}</p>` : ''}
                </div>
                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px; min-width:160px;">
                    <span class="badge" style="background:${corStatus[s.status] || '#bdc3c7'}">${labelStatus[s.status] || s.status.toUpperCase()}</span>
                    <button class="btn" style="padding:5px 10px; font-size:0.8rem;" onclick="toggleDetalhesSolicitacao(${s.id})">🔍 Ver Detalhes</button>
                    ${isGerenteCompras && s.status !== 'concluida' ? `
                        <button class="btn-success" style="padding:5px 10px; font-size:0.8rem; background:#3498db;" onclick="abrirRespostaSolicitacao(${s.id})">Atualizar Status</button>
                    ` : ''}
                </div>
            </div>

            <div id="detalhes-sol-${s.id}" class="hidden" style="margin-top:12px; border-top:1px solid #eee; padding-top:12px;">
                <div style="display:flex; gap:20px; flex-wrap:wrap;">
                    <div style="flex:1; min-width:250px;">
                        <h4 style="margin:0 0 8px; color:#2c3e50;">📋 Itens Solicitados</h4>
                        <div style="background:#f8f9fa; padding:10px; border-radius:6px; white-space:pre-wrap; font-size:0.9rem;">${s.itens}</div>
                    </div>
                    <div style="flex:2; min-width:300px;">
                        <h4 style="margin:0 0 8px; color:#2c3e50;">📦 Situação no Estoque Atual</h4>
                        <div id="estoque-info-${s.id}">
                            <button class="btn" style="padding:5px 12px; font-size:0.8rem;" onclick="carregarInfoEstoqueSolicitacao(${s.id}, \`${s.itens.replace(/`/g, "'")}\`)">Consultar Estoque</button>
                        </div>
                    </div>
                </div>
            </div>

            <div id="form-resposta-${s.id}" class="hidden" style="margin-top:12px; border-top:1px dashed #ddd; padding-top:10px;">
                <div class="form-group">
                    <select class="form-control" id="sol-status-${s.id}">
                        <option value="em_andamento">Em Andamento</option>
                        <option value="concluida">Concluída</option>
                        <option value="recusada">Recusada</option>
                    </select>
                    <textarea class="form-control" id="sol-resposta-${s.id}" rows="2" placeholder="Observação (opcional)..." style="resize:vertical;"></textarea>
                </div>
                <div style="display:flex; gap:8px;">
                    <button class="btn-success" style="padding:5px 12px;" onclick="confirmarResposta(${s.id})">Confirmar</button>
                    <button class="btn" style="padding:5px 12px;" onclick="fecharRespostaSolicitacao(${s.id})">Cancelar</button>
                </div>
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <h2>Solicitações de Compra</h2>
        ${formHtml}
        <div class="card">
            <h3>Histórico de Solicitações</h3>
            ${lista || '<p style="color:#888;">Nenhuma solicitação registrada.</p>'}
        </div>
    `;
}

async function enviarSolicitacao() {
    const titulo = document.getElementById('sol-titulo').value.trim();
    const descricao = document.getElementById('sol-descricao').value.trim();
    const itens = document.getElementById('sol-itens').value.trim();
    if (!titulo || !descricao || !itens) return alert('Preencha todos os campos.');
    const res = await apiFetch('/solicitacoes/criar', {
        method: 'POST',
        body: JSON.stringify({ titulo, descricao, itens })
    });
    if (res) { alert(res.detail); carregarSolicitacoes(); }
}

function toggleDetalhesSolicitacao(id) {
    const painel = document.getElementById(`detalhes-sol-${id}`);
    painel.classList.toggle('hidden');
}

async function carregarInfoEstoqueSolicitacao(solId, itensTexto) {
    const container = document.getElementById(`estoque-info-${solId}`);
    container.innerHTML = '<small style="color:#888;">Consultando estoque...</small>';

    const produtos = cacheProdutos.length > 0 ? cacheProdutos : await apiFetch('/estoque/mostrar');
    if (!produtos) {
        container.innerHTML = '<small style="color:#e74c3c;">Erro ao consultar estoque.</small>';
        return;
    }

    // Extrai palavras-chave dos itens solicitados (linhas não vazias, sem marcadores)
    const linhas = itensTexto.split('\n')
        .map(l => l.replace(/^[-*•\d.]+\s*/, '').trim())
        .filter(l => l.length > 2);

    if (linhas.length === 0) {
        container.innerHTML = '<small style="color:#888;">Nenhum item identificado para consulta.</small>';
        return;
    }

    // Para cada linha, busca produtos que contenham palavras da linha
    const resultados = linhas.map(linha => {
        const palavras = linha.toLowerCase().split(/\s+/).filter(p => p.length > 2);
        const encontrados = produtos.filter(p =>
            palavras.some(palavra =>
                p.nomedoproduto.toLowerCase().includes(palavra) ||
                (p.categoria || '').toLowerCase().includes(palavra)
            )
        );
        return { linha, encontrados };
    });

    const temResultado = resultados.some(r => r.encontrados.length > 0);

    let html = '<table style="width:100%; border-collapse:collapse; font-size:0.85rem;">';
    html += '<thead><tr style="background:#ecf0f1;"><th style="padding:6px; text-align:left;">Item Solicitado</th><th style="padding:6px; text-align:left;">Produto no Estoque</th><th style="padding:6px; text-align:center;">Qtd Atual</th><th style="padding:6px; text-align:right;">Preço Unit.</th></tr></thead><tbody>';

    resultados.forEach(({ linha, encontrados }) => {
        if (encontrados.length === 0) {
            html += `<tr style="border-bottom:1px solid #eee;">
                <td style="padding:6px;">${linha}</td>
                <td colspan="3" style="padding:6px; color:#e74c3c; font-style:italic;">Produto não encontrado no estoque</td>
            </tr>`;
        } else {
            encontrados.forEach((p, i) => {
                const corQtd = p.quantidade <= 5 ? '#e74c3c' : p.quantidade <= 20 ? '#f39c12' : '#27ae60';
                html += `<tr style="border-bottom:1px solid #eee;">
                    ${i === 0 ? `<td style="padding:6px;" rowspan="${encontrados.length}">${linha}</td>` : ''}
                    <td style="padding:6px;">${p.nomedoproduto}<br><small style="color:#888;">${p.codigodebarras}</small></td>
                    <td style="padding:6px; text-align:center;"><strong style="color:${corQtd}">${p.quantidade}</strong></td>
                    <td style="padding:6px; text-align:right;">R$ ${Number(p.preco).toFixed(2)}</td>
                </tr>`;
            });
        }
    });

    html += '</tbody></table>';

    if (!temResultado) {
        html = '<p style="color:#e74c3c; font-size:0.85rem;">Nenhum dos itens solicitados foi encontrado no cadastro de estoque.</p>';
    }

    container.innerHTML = html;
}

function abrirRespostaSolicitacao(id) {
    document.getElementById(`form-resposta-${id}`).classList.remove('hidden');
}

function fecharRespostaSolicitacao(id) {
    document.getElementById(`form-resposta-${id}`).classList.add('hidden');
}

async function confirmarResposta(id) {
    const status = document.getElementById(`sol-status-${id}`).value;
    const resposta = document.getElementById(`sol-resposta-${id}`).value.trim();
    const res = await apiFetch(`/solicitacoes/responder/${id}`, {
        method: 'POST',
        body: JSON.stringify({ status, resposta })
    });
    if (res) { alert(res.detail); carregarSolicitacoes(); }
}

async function atualizarBadgeComunicados() {
    const res = await apiFetch('/comunicados/nao-lidos', {}, true);
    const badge = document.getElementById('badge-comunicados');
    if (!badge) return;
    const total = res?.nao_lidos || 0;
    if (total > 0) {
        badge.textContent = total;
        badge.style.display = 'inline';
    } else {
        badge.style.display = 'none';
    }
}

async function carregarComunicados() {
    const container = document.getElementById('view-comunicados');
    container.innerHTML = '<h3>Carregando...</h3>';

    const cargo = (localStorage.getItem('user_cargo') || '').toLowerCase();
    const setor = (localStorage.getItem('user_setor') || '').toLowerCase();
    const isAdmin = localStorage.getItem('is_admin') === 'true';
    const podeEscrever = isAdmin
        || cargo.includes('direto')
        || cargo.includes('gerente')
        || setor === 'rh';

    const [comunicados, funcionarios] = await Promise.all([
        apiFetch('/comunicados/listar'),
        podeEscrever ? apiFetch('/funcionarios/listar') : Promise.resolve([])
    ]);

    let formHtml = '';
    if (podeEscrever) {
        const opcoesFunc = (funcionarios || []).map(f =>
            `<option value="${f.id}">${f.nome} ${f.sobrenome}</option>`
        ).join('');

        formHtml = `
        <div class="card">
            <h3>Novo Comunicado</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="com-titulo" placeholder="Título do comunicado">
                <textarea class="form-control" id="com-conteudo" rows="4" placeholder="Escreva o comunicado aqui..." style="resize:vertical;"></textarea>
                <div style="margin-top:10px;">
                    <label style="font-size:0.9rem; font-weight:bold;">Destinatários:</label>
                    <div style="display:flex; gap:15px; margin-top:6px; align-items:center;">
                        <label style="display:flex; align-items:center; gap:5px; cursor:pointer;">
                            <input type="radio" name="com-dest-tipo" value="todos" checked onchange="toggleDestinatariosCom()">
                            Todos os funcionários
                        </label>
                        <label style="display:flex; align-items:center; gap:5px; cursor:pointer;">
                            <input type="radio" name="com-dest-tipo" value="especificos" onchange="toggleDestinatariosCom()">
                            Funcionários específicos
                        </label>
                    </div>
                    <div id="com-selecao-func" style="display:none; margin-top:10px;">
                        <select class="form-control" id="com-destinatarios" multiple style="height:120px;">
                            ${opcoesFunc}
                        </select>
                        <small style="color:#666;">Segure Ctrl (ou Cmd) para selecionar mais de um.</small>
                    </div>
                </div>
            </div>
            <button class="btn-success" onclick="enviarComunicado()">Enviar Comunicado</button>
        </div>`;
    }

    const lista = (comunicados || []).map(c => `
        <div class="card" id="com-card-${c.destinatario_id}" style="border-left: 5px solid ${c.lido ? '#bdc3c7' : '#3498db'}; opacity: ${c.lido ? '0.75' : '1'};">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div style="flex:1;">
                    <h4 style="margin:0 0 5px;">${c.titulo}</h4>
                    <small style="color:#888;">De: <strong>${c.autor}</strong> &nbsp;|&nbsp; ${new Date(c.data_criacao).toLocaleString()} &nbsp;|&nbsp; ${c.para_todos ? 'Para todos' : 'Destinatário específico'}</small>
                    <p style="margin:12px 0 0; white-space:pre-wrap;">${c.conteudo}</p>
                </div>
                <div style="margin-left:15px; flex-shrink:0;">
                    ${c.lido
                        ? `<span style="color:#27ae60; font-size:0.8rem;">✓ Lido</span>`
                        : `<button class="btn-success" style="padding:5px 10px; font-size:0.8rem;" onclick="marcarLidoComunicado(${c.destinatario_id})">Marcar como lido</button>`
                    }
                </div>
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <h2>Comunicados</h2>
        ${formHtml}
        <div class="card">
            <h3>Caixa de Entrada</h3>
            ${lista || '<p style="color:#888;">Nenhum comunicado recebido.</p>'}
        </div>
    `;

    atualizarBadgeComunicados();
}

function toggleDestinatariosCom() {
    const tipo = document.querySelector('input[name="com-dest-tipo"]:checked')?.value;
    document.getElementById('com-selecao-func').style.display = tipo === 'especificos' ? 'block' : 'none';
}

async function enviarComunicado() {
    const titulo = document.getElementById('com-titulo').value.trim();
    const conteudo = document.getElementById('com-conteudo').value.trim();
    if (!titulo || !conteudo) return alert('Preencha o título e o conteúdo do comunicado.');

    const tipo = document.querySelector('input[name="com-dest-tipo"]:checked')?.value;
    const paraTodos = tipo !== 'especificos';
    let destinatarios = [];

    if (!paraTodos) {
        const select = document.getElementById('com-destinatarios');
        destinatarios = Array.from(select.selectedOptions).map(o => parseInt(o.value));
        if (destinatarios.length === 0) return alert('Selecione ao menos um destinatário.');
    }

    const res = await apiFetch('/comunicados/criar', {
        method: 'POST',
        body: JSON.stringify({ titulo, conteudo, para_todos: paraTodos, destinatarios })
    });

    if (res) {
        alert('Comunicado enviado com sucesso!');
        carregarComunicados();
    }
}

async function marcarLidoComunicado(destinatarioId) {
    const res = await apiFetch(`/comunicados/marcar-lido/${destinatarioId}`, { method: 'POST' });
    if (res) {
        const card = document.getElementById(`com-card-${destinatarioId}`);
        if (card) {
            card.style.borderLeftColor = '#bdc3c7';
            card.style.opacity = '0.75';
            const btn = card.querySelector('button');
            if (btn) btn.outerHTML = `<span style="color:#27ae60; font-size:0.8rem;">✓ Lido</span>`;
        }
        atualizarBadgeComunicados();
    }
}

// Garante que o arquivo termina sem blocos abertos
checkAuth();