CREATE DATABASE IF NOT EXISTS estoque_mercado;
USE `estoque_mercado`;

CREATE TABLE IF NOT EXISTS `setor` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(255) NOT NULL,
    `tipo` VARCHAR(50) NOT NULL,
    UNIQUE KEY `unique_tipo` (`tipo`)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `funcionario` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(100) NOT NULL,
    `sobrenome` VARCHAR(100) NOT NULL,
    `data_nascimento` DATE NOT NULL,
    `genero` VARCHAR(20) NOT NULL,
    `cargo` VARCHAR(50) NOT NULL DEFAULT 'operacional',
    `possui_filhos` BOOLEAN NOT NULL DEFAULT FALSE,
    `setor_id` INT NOT NULL,
    `is_admin` BOOLEAN NOT NULL DEFAULT FALSE,
    `bate_ponto` BOOLEAN NOT NULL DEFAULT TRUE,
    `cargo_confianca` BOOLEAN NOT NULL DEFAULT FALSE,
    `password_hash` VARCHAR(255),
    `last_password_change` DATETIME,
    `token` VARCHAR(255),
    `token_expiracao` DATETIME,
    KEY `idx_token` (`token`),
    CONSTRAINT `fk_func_setor` FOREIGN KEY (`setor_id`) REFERENCES `setor` (`id`)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `estoque` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    titulo VARCHAR(255),
    nomedoproduto VARCHAR(255) NOT NULL,
    quantidade INT NOT NULL DEFAULT 0,
    preco DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    codigodebarras VARCHAR(100) NOT NULL UNIQUE,
    categoria VARCHAR(100),
    funcionario_id INT,
    INDEX (codigodebarras),
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `venda` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data DATETIME DEFAULT CURRENT_TIMESTAMP,
    valor_total DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    funcionario_id INT NOT NULL,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `itemvenda` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    venda_id INT NOT NULL,
    codigodebarras VARCHAR(100) NOT NULL,
    quantidade INT NOT NULL,
    preco_unitario DECIMAL(10, 2) NOT NULL,
    preco_total DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (venda_id) REFERENCES venda(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `log` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    tipo_movimentacao VARCHAR(255) NOT NULL,
    data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `ponto` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    data DATE NOT NULL,
    entrada DATETIME,
    saida_almoco DATETIME,
    retorno_almoco DATETIME,
    saida DATETIME,
    horas_trabalhadas DECIMAL(5, 2) DEFAULT 0.00,
    horas_extras DECIMAL(5, 2) DEFAULT 0.00,
    horas_devidas DECIMAL(5, 2) DEFAULT 0.00,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `salario` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL UNIQUE,
    valor_mensal DECIMAL(10, 2) DEFAULT 0.00,
    valor_hora DECIMAL(10, 2) DEFAULT 0.00,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `salariohistorico` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    valor_antigo DECIMAL(10, 2) NOT NULL,
    valor_novo DECIMAL(10, 2) NOT NULL,
    data_alteracao DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `holerite` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    mes INT NOT NULL,
    ano INT NOT NULL,
    data_competencia DATE NOT NULL,
    valor_bruto DECIMAL(10, 2) DEFAULT 0.00,
    valor_liquido DECIMAL(10, 2) DEFAULT 0.00,
    salario_base DECIMAL(10, 2) DEFAULT 0.00,
    inss DECIMAL(10, 2) DEFAULT 0.00,
    irpf DECIMAL(10, 2) DEFAULT 0.00,
    fgts DECIMAL(10, 2) DEFAULT 0.00,
    vale_transporte DECIMAL(10, 2) DEFAULT 0.00,
    vale_refeicao DECIMAL(10, 2) DEFAULT 0.00,
    contribuicao_assistencial DECIMAL(10, 2) DEFAULT 0.00,
    ajuda_custo DECIMAL(10, 2) DEFAULT 0.00,
    adiantamento DECIMAL(10, 2) DEFAULT 0.00,
    horas_extras_valor DECIMAL(10, 2) DEFAULT 0.00,
    horas_trabalhadas DECIMAL(10, 2) DEFAULT 0.00,
    dias_trabalhados INT DEFAULT 30,
    horas_extras DECIMAL(10, 2) DEFAULT 0.00,
    horas_devidas DECIMAL(10, 2) DEFAULT 0.00,
    assinado BOOLEAN NOT NULL DEFAULT FALSE,
    data_assinatura DATETIME,
    data_emissao DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

-- ATENÇÃO: tabela órfã, não usada por nenhum código atual (ver comentário
-- completo perto da criação de `historico_senha`, mais abaixo neste arquivo).
CREATE TABLE IF NOT EXISTS `senhahistorico` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

-- ============================================================================
-- Migração aditiva (fix/base-tecnica-sistema-real) -- NÃO apaga nem recria
-- nada acima. Só adiciona o que os modelos do SQLModel (src/utils/database.py)
-- já esperam e que faltava aqui, para o projeto subir do zero só com este
-- arquivo (sem depender do SQLModel.metadata.create_all() criar tabela por
-- fora). Requer MySQL 8.0+ (usa information_schema e stored procedures,
-- compatível desde o MySQL 5.x também, mas testado em 8.0.46).
-- Regra seguida: toda alteração usa IF NOT EXISTS; nenhum DROP/TRUNCATE.
-- ============================================================================

-- MySQL (diferente do MariaDB) não entende `ADD COLUMN IF NOT EXISTS` em SQL
-- puro, então a forma portátil e segura de fazer "adicione a coluna só se
-- ela não existir" é com uma stored procedure temporária que consulta o
-- information_schema e monta o ALTER TABLE dinamicamente.
DELIMITER $$
DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`$$
CREATE PROCEDURE `_add_column_if_not_exists`(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = p_table AND column_name = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

-- `funcionario` ganhou campos de documento/endereço e de senha temporária
-- (ver classe Funcionario) depois que esta tabela já existia em produção.
CALL `_add_column_if_not_exists`('funcionario', 'cpf', 'VARCHAR(11) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'email', 'VARCHAR(255) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'cep', 'VARCHAR(8) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'estado', 'VARCHAR(2) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'cidade', 'VARCHAR(100) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'bairro', 'VARCHAR(100) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'rua', 'VARCHAR(255) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'numero', 'VARCHAR(20) NULL');
CALL `_add_column_if_not_exists`('funcionario', 'senha_temporaria', 'BOOLEAN NOT NULL DEFAULT FALSE');
CALL `_add_column_if_not_exists`('funcionario', 'senha_atualizada_em', 'DATETIME NULL');

-- NOTA: no modelo, `cpf` e `email` são `unique=True`. A constraint UNIQUE não
-- foi adicionada automaticamente aqui porque, se já existir alguma linha
-- duplicada (ou a tabela já tiver dados reais), o ALTER TABLE falharia no
-- meio da migração. Antes de rodar em produção, confira duplicados e, se
-- não houver, adicione manualmente:
--   ALTER TABLE funcionario ADD UNIQUE KEY uq_funcionario_cpf (cpf);
--   ALTER TABLE funcionario ADD UNIQUE KEY uq_funcionario_email (email);

-- `estoque` ganhou preço de custo (Estoque.preco_custo) além do preço de
-- venda, usado no cálculo de margem/compras.
CALL `_add_column_if_not_exists`('estoque', 'preco_custo', 'DECIMAL(10, 2) NOT NULL DEFAULT 0.00');

DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`;

-- Tabelas abaixo já existiam no banco (criadas pelo SQLModel.metadata.create_all
-- na inicialização da aplicação), mas nunca tinham sido adicionadas aqui.
CREATE TABLE IF NOT EXISTS `compra` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data DATETIME DEFAULT CURRENT_TIMESTAMP,
    solicitante_id INT NOT NULL,
    aprovador_id INT,
    valor_total DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    status VARCHAR(50) NOT NULL DEFAULT 'pendente',
    data_autorizacao DATETIME,
    INDEX (solicitante_id),
    INDEX (status),
    FOREIGN KEY (solicitante_id) REFERENCES funcionario(id),
    FOREIGN KEY (aprovador_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `itemcompra` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    compra_id INT NOT NULL,
    codigodebarras VARCHAR(100) NOT NULL,
    nomedoproduto VARCHAR(255) NOT NULL,
    categoria VARCHAR(100),
    preco_venda DECIMAL(10, 2),
    quantidade INT NOT NULL,
    preco_custo_unitario DECIMAL(10, 2) NOT NULL,
    preco_custo_total DECIMAL(10, 2) NOT NULL,
    lancado_em DATETIME,
    INDEX (compra_id),
    INDEX (codigodebarras),
    FOREIGN KEY (compra_id) REFERENCES compra(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `despesa` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data DATETIME DEFAULT CURRENT_TIMESTAMP,
    descricao VARCHAR(255) NOT NULL,
    valor DECIMAL(10, 2) NOT NULL,
    categoria VARCHAR(50) NOT NULL,
    funcionario_id INT NOT NULL,
    INDEX (funcionario_id),
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `comunicado` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    titulo VARCHAR(255) NOT NULL,
    conteudo TEXT NOT NULL,
    autor_id INT NOT NULL,
    data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
    para_todos BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX (autor_id),
    INDEX (data_criacao),
    FOREIGN KEY (autor_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `comunicadodestinatario` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    comunicado_id INT NOT NULL,
    funcionario_id INT NOT NULL,
    lido BOOLEAN NOT NULL DEFAULT FALSE,
    data_leitura DATETIME,
    INDEX (comunicado_id),
    INDEX (funcionario_id),
    FOREIGN KEY (comunicado_id) REFERENCES comunicado(id),
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

-- Tabela realmente usada pelo modelo HistoricoSenha (__tablename__ =
-- "historico_senha"). É DIFERENTE da `senhahistorico` já existente acima
-- (nomes de tabela e de coluna de data não batem -- `senhahistorico` ficou
-- órfã, sem nenhum código apontando para ela; mantida aqui intocada por
-- segurança, já que apagar tabela está fora de cogitação nesta migração).
CREATE TABLE IF NOT EXISTS `historico_senha` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX (funcionario_id),
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

-- ============================================================================
-- Migração aditiva (feat/produto-completo) -- cadastro de produto completo:
-- unidade de medida, quantidade decimal (venda por peso), estoque mínimo e
-- fornecedor. Mesma regra das migrações anteriores: tudo aditivo, nenhum
-- DROP/TRUNCATE, idempotente (pode rodar mais de uma vez sem erro).
-- ============================================================================

-- Mesmo padrão da Fase 1 (ver comentário completo mais acima, perto da
-- primeira definição desta mesma procedure): define uma vez no início desta
-- seção, chama várias vezes ao longo dela, dropa uma vez no fim.
DELIMITER $$
DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`$$
CREATE PROCEDURE `_add_column_if_not_exists`(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = p_table AND column_name = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

-- `estoque` ganhou unidade de medida (Estoque.unidade_medida): UN (unidade),
-- KG (quilo) ou L (litro). Guardado como VARCHAR (não ENUM do MySQL) para
-- seguir o mesmo padrão já usado em `funcionario.cargo` neste projeto --
-- valor fixo validado na camada Pydantic (schemas.UnidadeMedida), não via
-- constraint do banco.
CALL `_add_column_if_not_exists`('estoque', 'unidade_medida', "VARCHAR(2) NOT NULL DEFAULT 'UN'");

-- `estoque.quantidade`, `itemvenda.quantidade` e `itemcompra.quantidade`
-- eram INT; produtos vendidos por peso/volume (unidade_medida KG/L)
-- precisam de fração de unidade (ex.: 0.350 kg). `MODIFY COLUMN` muda o
-- tipo da coluna preservando os valores já gravados (um INT existente, ex.
-- 10, vira DECIMAL 10.000, sem perda), diferente de um DROP+ADD que
-- apagaria os dados. Não precisa de IF NOT EXISTS: alterar o tipo de uma
-- coluna que já existe não falha se este script rodar de novo (o segundo
-- MODIFY só reaplica a mesma definição, sem efeito colateral).
--
-- NOTA DE DEPLOY: diferente de um `ADD COLUMN` simples (que só mexe nos
-- metadados da tabela e é praticamente instantâneo), `MODIFY COLUMN` que
-- muda o tipo de uma coluna reescreve a tabela inteira (InnoDB recria o
-- arquivo por baixo, linha por linha, mesmo com ALGORITHM=INPLACE) -- não é
-- instantâneo em tabelas com volume real de dados. Durante a execução, o
-- MySQL mantém um metadata lock que bloqueia ESCRITAS concorrentes nessa
-- tabela (leituras continuam funcionando normalmente), então em produção
-- este ALTER TABLE (e os dois seguintes) deve rodar numa janela de baixo
-- tráfego, não a qualquer hora do dia.
ALTER TABLE `estoque` MODIFY COLUMN `quantidade` DECIMAL(10, 3) NOT NULL DEFAULT 0.000;
ALTER TABLE `itemvenda` MODIFY COLUMN `quantidade` DECIMAL(10, 3) NOT NULL;
ALTER TABLE `itemcompra` MODIFY COLUMN `quantidade` DECIMAL(10, 3) NOT NULL;

-- `estoque` ganhou estoque mínimo (Estoque.estoque_minimo): hoje só um
-- valor informativo mostrado no cadastro/listagem de produtos; o endpoint
-- de reposição automática que vai consumir esse valor é de uma fase futura
-- do projeto (fora do escopo desta migração).
CALL `_add_column_if_not_exists`('estoque', 'estoque_minimo', 'DECIMAL(10, 3) NOT NULL DEFAULT 0.000');

-- Fornecedor: nova tabela (CREATE TABLE IF NOT EXISTS, mesmo padrão já
-- usado nas tabelas `compra`/`itemcompra`/etc. acima), com vínculo opcional
-- em `estoque` (fornecedor principal do produto) e em `compra` (fornecedor
-- do pedido) -- opcional nos dois casos para não quebrar produtos/compras
-- já existentes sem fornecedor definido.
CREATE TABLE IF NOT EXISTS `fornecedor` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    documento VARCHAR(14) NOT NULL,
    telefone VARCHAR(20),
    email VARCHAR(255),
    prazo_medio_entrega_dias INT,
    UNIQUE KEY `unique_fornecedor_documento` (`documento`)
) ENGINE=InnoDB;

-- MySQL também não entende `ADD CONSTRAINT IF NOT EXISTS`, mesmo problema
-- do ADD COLUMN acima -- outra stored procedure temporária, desta vez
-- consultando information_schema.table_constraints, para simular "adicione
-- esta FOREIGN KEY só se ela não existir".
DELIMITER $$
DROP PROCEDURE IF EXISTS `_add_foreign_key_if_not_exists`$$
CREATE PROCEDURE `_add_foreign_key_if_not_exists`(
    IN p_table VARCHAR(64), IN p_constraint VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema = DATABASE() AND table_name = p_table AND constraint_name = p_constraint
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD CONSTRAINT `', p_constraint, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL `_add_column_if_not_exists`('estoque', 'fornecedor_id', 'INT NULL');
CALL `_add_column_if_not_exists`('compra', 'fornecedor_id', 'INT NULL');

CALL `_add_foreign_key_if_not_exists`('estoque', 'fk_estoque_fornecedor', 'FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id)');
CALL `_add_foreign_key_if_not_exists`('compra', 'fk_compra_fornecedor', 'FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id)');

DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`;
DROP PROCEDURE IF EXISTS `_add_foreign_key_if_not_exists`;

-- ============================================================================
-- Migração aditiva (feat/lotes-validade) -- lotes e validade: tabela nova de
-- lote por produto (consumida por FEFO na venda) e alerta de vencimento.
-- Mesma regra das migrações anteriores: tudo aditivo, nenhum DROP/TRUNCATE,
-- idempotente (pode rodar mais de uma vez sem erro).
--
-- DECISÃO DE ARQUITETURA (ver também utils.database.Lote e
-- repository/lotes.py, no código da aplicação): `estoque.quantidade`
-- continua sendo a fonte da verdade do saldo total de cada produto, travada
-- e decrementada exatamente como já era feito antes desta fase
-- (with_for_update(), testado sob concorrência real nas Fases 1/2). A nova
-- tabela `lote` é só um DETALHAMENTO de como esse saldo está repartido por
-- validade -- nunca uma segunda fonte da verdade. Optamos por essa
-- abordagem (em vez de mover a trava de concorrência para a própria tabela
-- `lote`) para reaproveitar 100% da trava já validada, sem reconstruir do
-- zero uma peça crítica que já funciona.
-- ============================================================================

CREATE TABLE IF NOT EXISTS `lote` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    estoque_id INT NOT NULL,
    codigo_lote VARCHAR(100) NOT NULL,
    quantidade DECIMAL(10, 3) NOT NULL DEFAULT 0.000,
    -- NULL = validade desconhecida ("lote legado", ver nota abaixo).
    validade DATE NULL,
    data_entrada DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX (estoque_id),
    INDEX (validade),
    FOREIGN KEY (estoque_id) REFERENCES estoque(id)
) ENGINE=InnoDB;

-- Dado existente: produtos cadastrados ANTES desta fase (todo o histórico)
-- têm `estoque.quantidade > 0` mas nenhum lote registrado -- sem isso, a
-- primeira venda desses produtos ficaria sem nenhum lote de onde baixar a
-- quantidade. A aplicação (repository/lotes.py, função consumir_fefo) já
-- trata esse caso sozinha, criando sob demanda um "lote legado" (validade
-- NULL, igual ao saldo do produto) na primeira venda de um produto sem
-- nenhum lote -- mas pré-popular aqui também, via INSERT condicional
-- (idempotente: só insere se o produto ainda não tiver NENHUM lote), deixa
-- a listagem de lotes correta desde já, sem esperar a primeira venda de
-- cada produto. Esse lote legado nunca aparece no alerta de vencimento
-- (que só considera lotes com validade conhecida).
INSERT INTO `lote` (estoque_id, codigo_lote, quantidade, validade, data_entrada)
SELECT e.id, 'LEGADO', e.quantidade, NULL, NOW()
FROM `estoque` e
WHERE e.quantidade > 0
  AND NOT EXISTS (SELECT 1 FROM `lote` l WHERE l.estoque_id = e.id);

-- ============================================================================
-- Migração aditiva (feat/historico-movimentacoes) -- Fase 4: histórico de
-- movimentações de estoque. Tabela nova (CREATE TABLE IF NOT EXISTS, mesmo
-- padrão das migrações anteriores), sem DROP/TRUNCATE, idempotente.
--
-- DECISÃO DE ARQUITETURA (ver também utils.database.MovimentacaoEstoque e
-- repository/movimentacoes.py, no código da aplicação): toda alteração de
-- `estoque.quantidade`/`lote.quantidade` passa a gerar uma linha aqui, na
-- mesma transação da alteração. `quantidade` é sempre SIGNED (positiva =
-- entrada, negativa = saída); a soma das quantidades de um produto, desde
-- sempre, deve bater com `estoque.quantidade` atual desse produto -- mesma
-- lógica de invariante já estabelecida para `lote` na fase anterior.
--
-- Dado existente: produtos/lotes cadastrados ANTES desta fase NÃO ganham
-- histórico de movimentação retroativo -- diferente da migração de `lote`
-- acima (que pré-popula um "lote legado" cobrindo o saldo existente), aqui
-- não há como reconstruir de forma confiável QUEM fez CADA alteração
-- histórica de quantidade, então nenhum INSERT de dado retroativo é feito.
-- O histórico de movimentações só começa a existir a partir de agora, para
-- toda alteração de saldo que ocorrer DAQUI PRA FRENTE.
-- ============================================================================

CREATE TABLE IF NOT EXISTS `movimentacao_estoque` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    estoque_id INT NOT NULL,
    -- NULL = movimentação não ligada a um lote específico (ex.: incremento
    -- manual via /estoque/inserir, ajuste de inventário) -- ver nota acima
    -- e docstring de MovimentacaoEstoque.
    lote_id INT NULL,
    -- ENTRADA_COMPRA, ENTRADA_MANUAL, VENDA, CANCELAMENTO_VENDA, PERDA,
    -- QUEBRA, VENCIMENTO ou AJUSTE_INVENTARIO -- validado na camada
    -- Pydantic (schemas.TipoMovimentacao), guardado aqui como VARCHAR
    -- simples, mesmo padrão já usado para
    -- `funcionario.cargo`/`estoque.unidade_medida`.
    tipo VARCHAR(30) NOT NULL,
    quantidade DECIMAL(10, 3) NOT NULL,
    -- IMPORTANTE 3 (revisão da Fase 4): SNAPSHOT de estoque.unidade_medida
    -- no momento desta movimentação -- NÃO uma referência viva ao produto.
    -- Sem isso, o frontend formatava o histórico inteiro com a unidade
    -- ATUAL do produto, distorcendo movimentações antigas se a unidade
    -- mudasse depois (ex.: de KG pra UN). Default 'UN' só para a coluna em
    -- si (linhas novas sempre preenchem de verdade via
    -- repository/movimentacoes.py); correção aditiva mais abaixo neste
    -- arquivo para quem já tinha rodado esta CREATE TABLE antes desta
    -- correção existir.
    unidade_medida VARCHAR(2) NOT NULL DEFAULT 'UN',
    -- Só obrigatório na camada Pydantic para o ajuste de inventário -- as
    -- demais movimentações não exigem motivo.
    motivo VARCHAR(255) NULL,
    -- NULL = funcionário autor foi excluído depois (ON DELETE SET NULL
    -- abaixo) -- ver CRÍTICO 1 da revisão da Fase 4, correção aditiva mais
    -- abaixo neste arquivo para quem já tinha rodado esta CREATE TABLE
    -- antes dessa correção existir.
    funcionario_id INT NULL,
    data DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX (estoque_id),
    INDEX (lote_id),
    INDEX (tipo),
    INDEX (data),
    FOREIGN KEY (estoque_id) REFERENCES estoque(id),
    FOREIGN KEY (lote_id) REFERENCES lote(id),
    CONSTRAINT `fk_movimentacao_estoque_funcionario` FOREIGN KEY (funcionario_id) REFERENCES funcionario(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ============================================================================
-- Migração aditiva (fix/historico-movimentacoes -- correções do painel de
-- revisão da Fase 4) -- ver repository/estoque.py::deletar_estoque e
-- repository/funcionarios.py::deletar_funcionario para o contexto completo
-- dos dois achados CRÍTICOS corrigidos aqui.
--
-- CRÍTICO 1a (deletar_estoque): a FK de `movimentacao_estoque` para
-- `estoque`/`lote` nunca teve ON DELETE CASCADE nem precisa ter -- a
-- correção é só na aplicação (deletar_estoque passa a apagar as
-- movimentações do produto ANTES de apagar lotes e o produto, mesmo padrão
-- já usado para `Lote` desde a Fase 3). Nenhuma mudança de schema necessária
-- para essa parte.
--
-- CRÍTICO 1b (deletar_funcionario): diferente do caso acima, aqui a correção
-- É de schema -- `movimentacao_estoque.funcionario_id` passa a aceitar NULL
-- e sua FK passa a ter ON DELETE SET NULL (em vez de bloquear/quebrar o
-- DELETE do funcionário com IntegrityError). DECISÃO: preserva o histórico
-- de movimentação (auditoria de estoque) mesmo depois que o funcionário sai
-- da empresa, só "anonimizando" a autoria -- em vez de apagar o histórico
-- junto (destruiria rastreabilidade de auditoria sem necessidade real) ou
-- bloquear o delete do funcionário (não seria razoável impedir desligar um
-- funcionário só porque ele mexeu no estoque alguma vez). Mesmo padrão já
-- usado em `Estoque.funcionario_id`, que já é opcional/nullable nesta mesma
-- base de código.
--
-- Bloco idempotente: para quem já criou a tabela `movimentacao_estoque` com
-- a definição ANTERIOR (funcionario_id NOT NULL, FK sem ON DELETE), aplica a
-- mesma correção via ALTER TABLE. Para quem ainda não tem a tabela, a
-- CREATE TABLE IF NOT EXISTS logo acima já nasce corrigida e este bloco é um
-- no-op (a stored procedure só age se a FK ainda não estiver como
-- "SET NULL").
-- ============================================================================

ALTER TABLE `movimentacao_estoque` MODIFY COLUMN `funcionario_id` INT NULL;

DELIMITER $$
DROP PROCEDURE IF EXISTS `_set_fk_ondelete_set_null`$$
CREATE PROCEDURE `_set_fk_ondelete_set_null`(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_ref_table VARCHAR(64),
    IN p_new_constraint VARCHAR(64)
)
BEGIN
    DECLARE v_constraint_name VARCHAR(64);
    DECLARE v_delete_rule VARCHAR(20);
    DECLARE v_done INT DEFAULT 0;
    DECLARE cur CURSOR FOR
        SELECT kcu.CONSTRAINT_NAME, rc.DELETE_RULE
          FROM information_schema.KEY_COLUMN_USAGE kcu
          JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
            ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
         WHERE kcu.TABLE_SCHEMA = DATABASE() AND kcu.TABLE_NAME = p_table
           AND kcu.COLUMN_NAME = p_column AND kcu.REFERENCED_TABLE_NAME = p_ref_table;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;

    OPEN cur;
    read_loop: LOOP
        FETCH cur INTO v_constraint_name, v_delete_rule;
        IF v_done THEN
            LEAVE read_loop;
        END IF;

        IF v_delete_rule IS NULL OR v_delete_rule <> 'SET NULL' THEN
            SET @ddl_drop = CONCAT('ALTER TABLE `', p_table, '` DROP FOREIGN KEY `', v_constraint_name, '`');
            PREPARE stmt FROM @ddl_drop; EXECUTE stmt; DEALLOCATE PREPARE stmt;

            SET @ddl_add = CONCAT('ALTER TABLE `', p_table, '` ADD CONSTRAINT `', p_new_constraint,
                                   '` FOREIGN KEY (`', p_column, '`) REFERENCES `', p_ref_table, '`(id) ON DELETE SET NULL');
            PREPARE stmt FROM @ddl_add; EXECUTE stmt; DEALLOCATE PREPARE stmt;
        END IF;
    END LOOP;
    CLOSE cur;
END$$
DELIMITER ;

CALL `_set_fk_ondelete_set_null`('movimentacao_estoque', 'funcionario_id', 'funcionario', 'fk_movimentacao_estoque_funcionario');

DROP PROCEDURE IF EXISTS `_set_fk_ondelete_set_null`;

-- ============================================================================
-- Migração aditiva (fix/historico-movimentacoes -- IMPORTANTE 3 da revisão
-- da Fase 4) -- ver utils.database.MovimentacaoEstoque e
-- repository/movimentacoes.py::registrar_movimentacao para o contexto
-- completo. Mesmo padrão das migrações anteriores: aditiva, idempotente
-- (IF NOT EXISTS), nenhum DROP/TRUNCATE.
--
-- `movimentacao_estoque` ganha `unidade_medida` -- SNAPSHOT da unidade de
-- medida do produto no momento da movimentação (não uma referência viva).
-- A CREATE TABLE IF NOT EXISTS logo acima já nasce com essa coluna para
-- instalação nova; este bloco é a correção para quem já tinha a tabela
-- criada antes dela existir.
-- ============================================================================

DELIMITER $$
DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`$$
CREATE PROCEDURE `_add_column_if_not_exists`(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = p_table AND column_name = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL `_add_column_if_not_exists`('movimentacao_estoque', 'unidade_medida', "VARCHAR(2) NOT NULL DEFAULT 'UN'");

DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`;

-- ============================================================================
-- Correção adicional (fix/historico-movimentacoes) -- bug PRÉ-EXISTENTE, de
-- uma fase anterior a esta (não é um achado da Fase 4 em si), descoberto
-- durante a correção dos achados do painel de revisão da Fase 4: ver
-- repository/funcionarios.py::deletar_funcionario para o contexto completo.
--
-- `historico_senha.funcionario_id -> funcionario.id` (criada bem acima
-- neste arquivo) nunca teve ON DELETE configurado -- deletar um funcionário
-- que já tivesse QUALQUER linha em historico_senha (ou seja, qualquer
-- funcionário real que já trocou de senha alguma vez, seja pelo fluxo de
-- troca obrigatória no primeiro acesso ou por recuperação de senha) quebrava
-- com IntegrityError/500, reproduzido ao vivo contra MySQL real.
--
-- DECISÃO: diferente de `movimentacao_estoque.funcionario_id` (ON DELETE SET
-- NULL logo acima -- preserva o histórico de auditoria de ESTOQUE,
-- anonimizando só a autoria), `historico_senha` é puramente um mecanismo
-- interno de bloqueio de reuso de senha (ver
-- repository/funcionarios.py::_senha_ja_usada) -- não é log de auditoria de
-- negócio que precise sobreviver à saída do funcionário; sem o funcionário
-- dono, a linha não tem mais nenhum propósito. Por isso a correção é só na
-- APLICAÇÃO (deletar_funcionario passa a apagar o histórico de senha do
-- funcionário ANTES de apagar o funcionário, na mesma transação) -- mesmo
-- padrão já usado para Lote/MovimentacaoEstoque em
-- repository/estoque.py::deletar_estoque (CRÍTICO 1a acima). Nenhuma mudança
-- de schema (ON DELETE CASCADE) é necessária para esta correção.
-- ============================================================================

-- ============================================================================
-- Migração aditiva (fix/login-rate-limiting) -- ver utils.database.Funcionario
-- e repository/funcionarios.py::autenticar_funcionario para o contexto
-- completo. Mesmo padrão das migrações anteriores: aditiva, idempotente
-- (IF NOT EXISTS), nenhum DROP/TRUNCATE.
--
-- Correção de uma varredura de segurança que confirmou ao vivo, contra o
-- servidor real, dois problemas no login (POST /funcionarios/login):
--   1) Mensagens de erro distintas revelavam quais usernames existem no
--      sistema -- corrigido só na aplicação (mensagem genérica única +
--      mitigação de timing-attack), sem precisar de mudança de schema.
--   2) Zero rate-limiting/lockout -- 20 tentativas de login seguidas contra
--      a mesma conta em ~4 segundos eram todas processadas normalmente, sem
--      nenhum bloqueio. É o que este bloco resolve.
--
-- `funcionario` ganha:
--   - tentativas_login_falhas: contador de tentativas de senha errada
--     consecutivas (zera a cada login bem-sucedido).
--   - bloqueado_ate: até quando a conta fica temporariamente bloqueada
--     depois de atingir o limite de tentativas (NULL = não bloqueada).
-- ============================================================================

DELIMITER $$
DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`$$
CREATE PROCEDURE `_add_column_if_not_exists`(
    IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = p_table AND column_name = p_column
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL `_add_column_if_not_exists`('funcionario', 'tentativas_login_falhas', 'INT NOT NULL DEFAULT 0');
CALL `_add_column_if_not_exists`('funcionario', 'bloqueado_ate', 'DATETIME NULL');

DROP PROCEDURE IF EXISTS `_add_column_if_not_exists`;

-- ============================================================================
-- Migração aditiva (fix/login-rate-limiting -- CRÍTICO 1 da revisão da trava
-- de login) -- ver repository/funcionarios.py::autenticar_funcionario para o
-- contexto completo. Mesmo padrão das migrações anteriores: aditiva,
-- idempotente, nenhum DROP/TRUNCATE.
--
-- ACHADO (painel de revisão, confirmado ao vivo contra MySQL real via
-- EXPLAIN, performance_schema.data_locks e um teste de concorrência com
-- threads reais): a consulta de login (SELECT ... FOR UPDATE, introduzida
-- pelo lockout acima) filtrava `nome`/`sobrenome` sem NENHUM índice
-- utilizável -- EXPLAIN mostrava type=ALL (full table scan). Sob
-- REPEATABLE READ (padrão do InnoDB), uma leitura de bloqueio que faz table
-- scan trava a tabela `funcionario` INTEIRA durante a transação, não só a
-- linha procurada: medido ao vivo, 10 contas DIFERENTES logando
-- simultaneamente levaram ~9x mais tempo que uma chamada isolada -- deveriam
-- ser independentes entre si. A própria correção de segurança (lockout)
-- tinha introduzido um problema de disponibilidade pior do que o resolvido.
--
-- POR QUE ÍNDICE FUNCIONAL (não um índice comum em nome/sobrenome): a
-- consulta compara via `func.lower(nome) == valor.lower()` (ver código),
-- então a expressão realmente filtrada é LOWER(nome)/LOWER(sobrenome), não
-- as colunas em si -- um índice comum não é utilizável para uma expressão
-- assim (não-sargable para um B-tree normal). Índice funcional (MySQL
-- 8.0.13+, disponível na versão já usada por este projeto -- 8.0.46)
-- definido sobre a MESMA expressão -- confirmado com EXPLAIN real que passa
-- a eliminar o type=ALL (vira type=ref, usando este índice).
--
-- POR QUE NÃO-ÚNICO: `nome.sobrenome` é o formato do username de login, mas
-- nada no código (criar_funcionario/atualizar_funcionario) impede dois
-- funcionários com o mesmo nome+sobrenome -- só CPF e email são verificados
-- como únicos hoje. Não há como inspecionar dados reais de produção a partir
-- deste ambiente de correção para confirmar ausência de duplicatas, então
-- não é seguro assumir unicidade. Declarar UNIQUE aqui arriscaria falhar a
-- migração (se já existir duplicata) ou bloquear cadastros futuros
-- legítimos (nomes comuns reais, ex. dois funcionários "Maria Silva" num
-- supermercado) -- um custo de disponibilidade desnecessário para resolver
-- o problema desta correção. Fechar essa lacuna de integridade (impedir
-- duplicatas de nome+sobrenome na aplicação) é uma mudança de escopo maior,
-- deixada para uma correção futura dedicada caso se confirme necessária.
--
-- MySQL não entende `ADD INDEX IF NOT EXISTS`, mesmo problema do ADD COLUMN/
-- ADD CONSTRAINT acima -- mesma solução (stored procedure temporária
-- consultando information_schema, desta vez information_schema.statistics).
-- ============================================================================

DELIMITER $$
DROP PROCEDURE IF EXISTS `_add_index_if_not_exists`$$
CREATE PROCEDURE `_add_index_if_not_exists`(
    IN p_table VARCHAR(64), IN p_index VARCHAR(64), IN p_definition TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = p_table AND index_name = p_index
    ) THEN
        SET @ddl = CONCAT('ALTER TABLE `', p_table, '` ADD INDEX `', p_index, '` ', p_definition);
        PREPARE stmt FROM @ddl;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL `_add_index_if_not_exists`(
    'funcionario', 'idx_funcionario_login_nome_sobrenome',
    '((LOWER(nome)), (LOWER(sobrenome)))'
);

DROP PROCEDURE IF EXISTS `_add_index_if_not_exists`;