const API_URL = "http://127.0.0.1:8000";

let carrinho = [];
let pendingFuncionarioId = null;
let editandoFuncionarioId = null;
let editandoProdutoId = null;
let editandoSetorId = null;
let cacheFuncionarios = [];
let cacheProdutos = [];
let cacheSetores = [];

function getToken() {
    return localStorage.getItem('api_token');
}

async function login() {
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
            checkAuth();
        } else {
            alert("Servidor retornou um status desconhecido: " + data?.status);
        }
    } catch (err) {
        console.error("Erro catastrófico no login:", err);
        alert("Erro de conexão. Verifique se o servidor backend está ligado.");
    }
}

function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    input.type = input.type === "password" ? "text" : "password";
}

async function submeterNovaSenha() {
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
        const res = await fetch(`${API_URL}/funcionarios/definir-senha`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ funcionario_id: pendingFuncionarioId, nova_senha: novaSenha })
        });

        let data = {};
        try {
            data = await res.json();
        } catch (e) {
            data = { detail: `Erro interno no servidor (${res.status}).` };
        }

        if (res.ok) {
            alert("Senha cadastrada com sucesso! Por favor, realize o login com sua nova senha.");
            
            document.getElementById('password-screen').classList.add('hidden');
            document.getElementById('login-screen').classList.remove('hidden');
            
            document.getElementById('new-password').value = '';
            document.getElementById('confirm-password').value = '';
            document.getElementById('pass-input').value = '';
            feedback.style.display = 'none';
            pendingFuncionarioId = null;
        } else {
            const mensagemErro = data?.detail || "Erro ao validar senha.";
            alert(`Senha Inválida: ${mensagemErro}`);
            feedback.innerText = mensagemErro;
            feedback.className = 'feedback-msg feedback-error';
            feedback.style.display = 'block';
        }
    } catch (error) {
        alert("Erro de conexão com o servidor. Tente novamente.");
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

        const isAdmin = localStorage.getItem('is_admin') === 'true';
        const setor = (localStorage.getItem('user_setor') || "").toLowerCase().trim();
        const cargo = (localStorage.getItem('user_cargo') || "operacional").toLowerCase().trim();

        // Log para depuração - ajuda a ver por que o menu sumiu
        console.log(`Verificando acessos - Admin: ${isAdmin}, Setor: ${setor}, Cargo: ${cargo}`);

        const isDiretor = cargo.includes('diretor');
        const isGerente = cargo.includes('gerente');
        const inVendas = setor.includes('vendas');
        const inEstoque = setor.includes('estoque');
        const inGerencia = setor.includes('gerencia');
        const inRH = setor.includes('rh');

        document.querySelectorAll('.sidebar ul li').forEach(li => {
            const acao = li.getAttribute('onclick') || "";
            let visivel = true;

            if (acao.includes("'funcionarios'")) {
                if (!isAdmin && !inRH && !isDiretor) visivel = false;
            } else if (acao.includes("'estoque'")) {
                if (!isAdmin && !inEstoque && !isDiretor && !inGerencia) visivel = false;
            } else if (acao.includes("'vendas-dia'")) {
                if (!isAdmin && !isDiretor && !inGerencia && !(isGerente && inVendas)) visivel = false;
            } else if (acao.includes("'vendas'")) {
                if (!isAdmin && !inVendas && !isDiretor && !inGerencia) visivel = false;
            }

            if (visivel) li.classList.remove('hidden');
            else li.classList.add('hidden');
        });

        navegar('pontos');
        verificarLembretePonto();
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
    
    const isGerenciaGeral = isAdmin || setor === 'gerencia' || setor === 'admin';
    const podeCadastrar = isGerenciaGeral || setor === 'estoque';
    const podeEditar = isGerenciaGeral || (cargo.includes('gerente') && setor === 'estoque');

    let html = `
        <h2>Controle de Estoque</h2>
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
                ${podeEditar ? `<td><button class="btn" style="padding: 5px; font-size: 0.7rem; background: #ff9800; color: white;" onclick="prepararEdicaoEstoque(${p.id})">Editar</button></td>` : ''}
            </tr>
        `;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
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

async function carregarVendas() {
    const container = document.getElementById('view-vendas');
    let html = `
        <h2>Terminal de Vendas</h2>
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

async function carregarVendasDia() {
    const container = document.getElementById('view-vendas-dia');
    container.innerHTML = '<h3>Carregando dados do caixa...</h3>';
    const vendasDia = await apiFetch('/vendas/vendasdodia');
    if (!vendasDia) return;

    container.innerHTML = `
        <h2>Vendas do Dia</h2>
        <div class="card" style="background-color: #e8f8f5; border-left: 5px solid #2ecc71;">
            <h3>Resumo Financeiro</h3>
            <p>Data: <strong>${new Date(vendasDia.dat).toLocaleDateString()}</strong></p>
            <p>Total Vendido: <strong style="font-size: 1.5rem; color: #27ae60;">R$ ${vendasDia.total_vendido.toFixed(2)}</strong></p>
        </div>
    `;
}

function adicionarAoCarrinho() {
    const codigo = document.getElementById('venda-codigo').value;
    const qtd = parseInt(document.getElementById('venda-qtd').value);

    if (!codigo || qtd <= 0) {
        alert("Dados inválidos");
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
        carregarVendas();
    }
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

        <div class="card" style="background: #f8f9fa; border-left: 5px solid #2c3e50;">
            <h3>Fechamento de Folha</h3>
            <div class="form-group" style="display:flex; gap:10px; align-items:center;">
                <input type="number" id="fechar-mes" value="${mes}" class="form-control" style="width: 80px;">
                <input type="number" id="fechar-ano" value="${ano}" class="form-control" style="width: 100px;">
                <button class="btn-danger" onclick="fecharFolhaMensal()">Encerrar Folha e Gerar Holerites</button>
            </div>
        </div>

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
                                ${s.tipo !== 'admin' ? `
                                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem; background: #ff9800; color: white;" onclick="prepararEdicaoSetor(${s.id})">Editar</button>
                                    <button class="btn-danger" style="padding: 5px 10px; font-size: 0.8rem;" onclick="removerSetor(${s.id})">Excluir</button>
                                ` : `<button class="btn-danger" style="padding: 5px 10px; font-size: 0.8rem;" disabled>Admin</button>`}
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>

        <div class="card">
            <h3 id="form-setor-title">Cadastrar Novo Setor</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="setor-nome-novo" placeholder="Nome do Setor (ex: Recursos Humanos)">
                <input class="form-control" type="text" id="setor-tipo-novo" placeholder="Tipo (ex: rh, estoque, vendas, gerencia)">
            </div>
            <div id="setor-btn-container">
                <button onclick="criarSetor()">Cadastrar Setor</button>
            </div>
        </div>
        
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
                    <option value="gerente">Gerente de Setor</option>
                    <option value="diretor">Diretor de Mercado</option>
                </select>
                <div style="display:flex; align-items:center; gap:5px; padding: 5px;">
                    <input type="checkbox" id="func-admin" style="width: 20px; height: 20px;">
                    <label for="func-admin" style="font-size: 0.9rem;">Privilégios de Administrador</label>
                </div>
                <input class="form-control" type="number" id="func-salario" placeholder="Salário Mensal (R$)">
            </div>
            <div id="func-btn-container">
                <button class="btn-success" onclick="criarFuncionario()" id="btn-salvar-func">Cadastrar</button>
            </div>
        </div>

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
                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem; background: #ff9800; color: white;" 
                        onclick="prepararEdicaoFuncionario(${f.id})">Editar</button>
                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem;" 
                        onclick="verRelatorioPontoIndividual(${f.id}, '${f.nome} ${f.sobrenome}')">Ver Ponto Mensal</button>
                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem; background: #673ab7; color: white;" 
                        onclick="verHoleriteRH(${f.id}, '${f.nome} ${f.sobrenome}')">Holerite</button>
                    <button class="btn-success" style="padding: 5px 10px; font-size: 0.8rem;" 
                        onclick="abrirGerenciamentoSalario(${f.id}, '${f.nome} ${f.sobrenome}')">$ Salário</button>
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
    
    // Esconde campo de salário na edição rápida (usa-se o botão $ Salário para isso)
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
    
    const hojeStr = agora.toLocaleDateString();

    if (relatorio && relatorio.funcionario) {
        document.getElementById('sidebar-user-name').innerText = `Mercado 24h - ${relatorio.funcionario}`;
    }

    const formatarHora = (iso) => iso ? new Date(iso).toLocaleTimeString() : '--:--';

    let html = `
        <h2>Ponto Eletrônico - ${relatorio?.funcionario || 'Carregando...'} - ${hojeStr}</h2>
        <div class="card" style="text-align: center;">
            <div class="form-group" style="display: flex; justify-content: center; gap: 20px; margin-bottom: 20px;">
                <div class="ponto-stamp">Entrada:<br><strong>${formatarHora(status?.entrada)}</strong></div>
                <div class="ponto-stamp">Almoço:<br><strong>${formatarHora(status?.saida_almoco)}</strong></div>
                <div class="ponto-stamp">Retorno:<br><strong>${formatarHora(status?.retorno_almoco)}</strong></div>
                <div class="ponto-stamp">Saída:<br><strong>${formatarHora(status?.saida)}</strong></div>
            </div>
            
            <div style="margin: 20px 0;">
                <p>Status: <strong>${status?.saida ? 'Expediente Encerrado' : 'Em Aberto'}</strong></p>
                <p>Horas Hoje: ${formatarHorasRelogio(status?.horas_trabalhadas)} | Extras: ${formatarHorasRelogio(status?.horas_extras)}</p>
            </div>

            <button class="btn-success" onclick="baterPonto()" ${status?.saida ? 'disabled' : ''}>
                ${status?.saida ? 'Expediente Finalizado' : 'Bater Próximo Ponto'}
            </button>
        </div>

        <div class="card">
            <h3>Meu Histórico Mensal (${mes}/${ano})</h3>
            <div style="display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;" id="resumo-ponto-container">
                <div class="ponto-stamp">Total Horas:<br><strong>${formatarHorasRelogio(relatorio?.resumo?.total_trabalhado_mes)}</strong></div>
                <div class="ponto-stamp">Banco Extras:<br><strong style="color: green">+${formatarHorasRelogio(relatorio?.resumo?.total_extra_mes)}</strong></div>
                <div class="ponto-stamp">Banco Horas Devidas:<br><strong style="color: red">${relatorio?.resumo?.total_devido_mes > 0 ? '-' : ''}${formatarHorasRelogio(relatorio?.resumo?.total_devido_mes)}</strong></div>
                <div class="ponto-stamp">Saldo Final:<br><strong style="color: ${relatorio?.resumo?.saldo_mensal >= 0 ? (relatorio?.resumo?.saldo_mensal > 0 ? '#27ae60' : '#333') : '#e74c3c'}">${formatarHorasRelogio(relatorio?.resumo?.saldo_mensal)}</strong></div>
                <div class="ponto-stamp" style="background: #27ae60; color: white;">Previsão Salarial:<br><strong>R$ ${relatorio?.resumo?.total_a_receber?.toFixed(2) || '0.00'}</strong></div>
            </div>
            <table>
                <thead>
                    <tr><th>Data</th><th>Entrada</th><th>Almoço</th><th>Retorno</th><th>Saída</th><th>Extra</th><th>Devido</th></tr>
                </thead>
                <tbody>
                    ${(relatorio?.pontos || []).map(p => `
                        <tr>
                            <td>${formatarDataSimples(p.data)}</td>
                            <td>${formatarHora(p.entrada)}</td>
                            <td>${formatarHora(p.saida_almoco)}</td>
                            <td>${formatarHora(p.retorno_almoco)}</td>
                            <td>${formatarHora(p.saida)}</td>
                            <td style="color: green">${p.horas_extras > 0 ? '+' + formatarHorasRelogio(p.horas_extras) : '00:00'}</td>
                            <td style="color: red">${p.horas_devidas > 0 ? '-' + formatarHorasRelogio(p.horas_devidas) : '00:00'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>

        <div class="card">
            <h3>Meu Holerite Digital</h3>
            ${holerite && holerite.id ? `
                <div style="border: 1px solid #ddd; padding: 15px; border-radius: 8px;">
                    <div style="display:flex; justify-content: space-between; align-items: center;">
                        <div>
                            <p>Mês de Referência: <strong>${holerite.mes}/${holerite.ano}</strong></p>
                            <p>Valor Líquido: <strong style="color: #27ae60; font-size: 1.2rem;">R$ ${holerite.valor_liquido.toFixed(2)}</strong></p>
                        </div>
                        <div style="display: flex; gap: 10px;">
                            ${!holerite.assinado ? 
                                `<button class="btn-success" onclick="assinarHolerite(${holerite.id})">Assinar Agora</button>` : 
                                `<span style="color: #27ae60; font-weight: bold;">✓ Assinado em ${new Date(holerite.data_assinatura).toLocaleDateString()}</span>`}
                            <button class="btn" onclick="gerarPDFHolerite(${JSON.stringify(holerite).replace(/"/g, '&quot;')})">Baixar PDF</button>
                        </div>
                    </div>
                </div>
            ` : '<p>Nenhum holerite fechado para o mês anterior.</p>'}
        </div>
    `;
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

checkAuth();