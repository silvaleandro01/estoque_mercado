const API_URL = "http://127.0.0.1:8000";

let carrinho = [];
let pendingFuncionarioId = null;

function getToken() {
    return localStorage.getItem('api_token');
}

async function login() {
    const user = document.getElementById('user-input').value.trim();
    const pass = document.getElementById('pass-input').value;
    
    if (!user) {
        alert('Por favor, insira seu usuário (nome.sobrenome).');
        return;
    }

    const res = await fetch(`${API_URL}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: user, password: pass })
    });

    const data = await res.json();

    if (res.status === 401) {
        alert(data.detail);
        return;
    }

    if (data.status === "primeiro_acesso" || data.status === "senha_expirada") {
        pendingFuncionarioId = data.funcionario_id;
        document.getElementById('login-screen').classList.add('hidden');
        document.getElementById('password-screen').classList.remove('hidden');
        document.getElementById('pwd-title').innerText = data.status === "primeiro_acesso" ? "Primeiro Acesso" : "Senha Expirada";
        document.getElementById('pwd-msg').innerText = "Por favor, defina uma senha forte para continuar.";
    } else if (data.status === "sucesso") {
        localStorage.setItem('api_token', data.token);
        checkAuth();
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
    
    // 1. Limpar estado de erro anterior e preparar feedback
    feedback.style.display = 'none';
    feedback.className = 'feedback-msg';

    if (novaSenha !== confirmaSenha) {
        feedback.innerText = "As senhas não coincidem!";
        feedback.className = 'feedback-msg feedback-error';
        feedback.style.display = 'block';
        return;
    }

    try {
        const res = await fetch(`${API_URL}/funcionarios/definir-senha`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ funcionario_id: pendingFuncionarioId, nova_senha: novaSenha })
        });

        let data;
        try {
            data = await res.json();
        } catch (e) {
            // Caso o servidor retorne um erro 500 sem JSON válido
            data = { detail: "Erro interno no servidor. Verifique a força da senha e tente novamente." };
        }

        if (res.ok) {
            alert("Senha cadastrada com sucesso! Por favor, realize o login com sua nova senha.");
            
            // Retorna para a tela de login
            document.getElementById('password-screen').classList.add('hidden');
            document.getElementById('login-screen').classList.remove('hidden');
            
            // Limpa os campos e estados
            document.getElementById('new-password').value = '';
            document.getElementById('confirm-password').value = '';
            document.getElementById('pass-input').value = '';
            feedback.style.display = 'none';
            pendingFuncionarioId = null;
        } else {
            // Aqui pegamos o detalhe exato do erro vindo do backend (ex: "Falta caractere especial")
            const mensagemErro = data.detail || "Erro ao validar senha.";
            alert(`Senha Inválida: ${mensagemErro}`);
            feedback.innerText = mensagemErro;
            feedback.className = 'feedback-msg feedback-error';
            feedback.style.display = 'block';
        }
    } catch (error) {
        console.error("Erro ao definir senha:", error);
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
        navegar('dashboard');
        verificarLembretePonto();
    } else {
        loginScreen.classList.remove('hidden');
        mainLayout.classList.add('hidden');
    }
}

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
            const errorData = await response.json();
            const mensagem = errorData.detail || "Erro de permissão";
            
            alert(`Erro ${response.status}: ${mensagem}`);
            
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
    if (viewId === 'funcionarios') carregarFuncionarios();
    if (viewId === 'pontos') carregarPontos();
}

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
        titulo: document.getElementById('novo-prod-nome').value
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

async function carregarVendas() {
    const container = document.getElementById('view-vendas');
    
    const vendasDia = await apiFetch('/vendas/vendasdodia');
    
    if (!vendasDia) {
        container.innerHTML = '<h2>Acesso Negado</h2><p>Você não tem permissão para visualizar o caixa.</p>';
        return;
    }

    let totalHoje = 0;
    if (vendasDia.total_vendido !== undefined) {
        totalHoje = vendasDia.total_vendido;
    }

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

// Função auxiliar para converter decimal (7.99) para HH:MM
function formatarHorasRelogio(decimal) {
    if (decimal === null || decimal === undefined || isNaN(decimal)) return "00:00";
    const sinal = decimal < 0 ? "-" : "";
    const valorAbsoluto = Math.abs(decimal);
    const horas = Math.floor(valorAbsoluto);
    const minutos = Math.round((valorAbsoluto - horas) * 60);
    // Garante que 60 minutos virem 1 hora extra
    const horasFinal = minutos === 60 ? horas + 1 : horas;
    const minutosFinal = minutos === 60 ? 0 : minutos;
    return `${sinal}${horasFinal.toString().padStart(2, '0')}:${minutosFinal.toString().padStart(2, '0')}`;
}

// Função auxiliar para formatar data ISO sem deslocamento de fuso horário
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

    // Carrega funcionários e setores simultaneamente
    const [funcionarios, setores, pontosGerais] = await Promise.all([
        apiFetch('/funcionarios/listar'),
        apiFetch('/setores/listar'),
        apiFetch(`/pontos/rh/geral?mes=${mes}&ano=${ano}`)
    ]);
    
    if (!funcionarios) {
        container.innerHTML = `<div class="card"><h3>Acesso Negado</h3><p>Apenas RH ou Admin podem ver isso.</p></div>`;
        return;
    }

    const listaSetores = setores || [];

    let html = `
        <h2>Gestão de RH</h2>

        <div class="card">
            <h3>Cadastrar Novo Setor</h3>
            <div class="form-group">
                <input class="form-control" type="text" id="setor-nome-novo" placeholder="Nome do Setor (ex: Recursos Humanos)">
                <input class="form-control" type="text" id="setor-tipo-novo" placeholder="Tipo (ex: rh, estoque, vendas, gerencia)">
            </div>
            <button onclick="criarSetor()">Cadastrar Setor</button>
        </div>
        
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
                <select class="form-control" id="func-setor">
                    <option value="">Selecione o Setor</option>
                    ${listaSetores.map(s => `<option value="${s.id}">${s.nome} (${s.tipo})</option>`).join('')}
                </select>
            </div>
            <button onclick="criarFuncionario()">Cadastrar</button>
        </div>

        <div class="card">
        <h3>Equipe</h3>
        <table>
            <thead>
                <tr><th>ID</th><th>Nome</th><th>Setor ID</th><th>Admin</th><th>Ações</th></tr>
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
                <td>
                    <button class="btn" style="padding: 5px 10px; font-size: 0.8rem;" 
                        onclick="verRelatorioPontoIndividual(${f.id}, '${f.nome} ${f.sobrenome}')">Ver Ponto Mensal</button>
                </td>
            </tr>
        `;
    });

    html += '</tbody></table></div>';

    html += `<div id="detalhe-ponto-individual"></div>`;

    html += `
        <div class="card">
            <h3>Controle de Ponto Geral - Carga Semanal 44h (8h Diárias)</h3>
            <p style="font-size: 0.85rem; color: #666; margin-bottom: 15px;">
                Relatório consolidado de batidas, horas trabalhadas e balanço do banco de horas.
            </p>
            <table>
                <thead>
                    <tr><th>Data</th><th>Funcionário</th><th>Entrada</th><th>Saída</th><th>Trabalhadas</th><th>Extras</th><th>Saldo Diário</th></tr>
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
                                <strong style="color: ${p.extras - p.devidas >= 0 ? (p.extras - p.devidas > 0 ? '#27ae60' : '#333') : '#e74c3c'}">
                                    ${formatarHorasRelogio(p.extras - p.devidas)}
                                </strong>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = html;
}

async function verRelatorioPontoIndividual(id, nomeCompleto) {
    const container = document.getElementById('detalhe-ponto-individual');
    container.innerHTML = '<h3>Carregando relatório...</h3>';
    
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
                <button class="btn-danger" onclick="document.getElementById('detalhe-ponto-individual').innerHTML = ''">Fechar</button>
            </div>
            
            <div style="display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap;">
                <div class="ponto-stamp">Trabalhado:<br><strong>${formatarHorasRelogio(relatorio.resumo.total_trabalhado_mes)}</strong></div>
                <div class="ponto-stamp">Extras:<br><strong style="color: green">+${formatarHorasRelogio(relatorio.resumo.total_extra_mes)}</strong></div>
                <div class="ponto-stamp">Devidas:<br><strong style="color: red">${relatorio.resumo.total_devido_mes > 0 ? '-' : ''}${formatarHorasRelogio(relatorio.resumo.total_devido_mes)}</strong></div>
                <div class="ponto-stamp">Saldo Mensal:<br><strong style="color: ${relatorio.resumo.saldo_mensal >= 0 ? (relatorio.resumo.saldo_mensal > 0 ? '#27ae60' : '#333') : '#e74c3c'}">
                    ${formatarHorasRelogio(relatorio.resumo.saldo_mensal)}
                </strong></div>
            </div>

            <table>
                <thead>
                    <tr><th>Data</th><th>Entrada</th><th>Almoço</th><th>Retorno</th><th>Saída</th><th>Extras</th><th>Devidas</th></tr>
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
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
    
    container.innerHTML = html;
    container.scrollIntoView({ behavior: 'smooth' });
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

    const res = await apiFetch('/setores/criar', {
        method: 'POST',
        body: JSON.stringify(dados)
    });

    if (res) {
        alert('Setor criado com sucesso!');
        carregarFuncionarios(); // Recarrega para atualizar o dropdown de funcionários
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
        setor_id: parseInt(setorId)
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

async function verificarLembretePonto() {
    const status = await apiFetch('/pontos/status');
    // Se não houver registro hoje ou se ainda não bateu a entrada
    if (!status || !status.entrada) {
        alert("Atenção: Você ainda não bateu o ponto de entrada hoje!");
    }
}

async function carregarPontos() {
    const container = document.getElementById('view-pontos');
    container.innerHTML = '<h3>Carregando...</h3>';
    
    const agora = new Date();
    const mes = agora.getMonth() + 1;
    const ano = agora.getFullYear();

    const [status, relatorio] = await Promise.all([
        apiFetch('/pontos/status'),
        apiFetch(`/pontos/meu-relatorio?mes=${mes}&ano=${ano}`)
    ]);

    const hojeStr = agora.toLocaleDateString();

    const formatarHora = (iso) => iso ? new Date(iso).toLocaleTimeString() : '--:--';

    let html = `
        <h2>Ponto Eletrônico - ${hojeStr}</h2>
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
            <div style="display: flex; gap: 20px; margin-bottom: 20px;">
                <div class="ponto-stamp">Total Horas:<br><strong>${formatarHorasRelogio(relatorio?.resumo.total_trabalhado_mes)}</strong></div>
                <div class="ponto-stamp">Banco Extras:<br><strong style="color: green">+${formatarHorasRelogio(relatorio?.resumo.total_extra_mes)}</strong></div>
                <div class="ponto-stamp">Banco Horas Devidas:<br><strong style="color: red">${relatorio?.resumo.total_devido_mes > 0 ? '-' : ''}${formatarHorasRelogio(relatorio?.resumo.total_devido_mes)}</strong></div>
                <div class="ponto-stamp">Saldo Final:<br><strong style="color: ${relatorio?.resumo.saldo_mensal >= 0 ? (relatorio?.resumo.saldo_mensal > 0 ? '#27ae60' : '#333') : '#e74c3c'}">${formatarHorasRelogio(relatorio?.resumo.saldo_mensal)}</strong></div>
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
    `;
    container.innerHTML = html;
}

async function baterPonto() {
    const res = await apiFetch('/pontos/bater', { method: 'POST' });
    if (res) {
        alert(res.detail);
        carregarPontos();
    }
}

checkAuth();