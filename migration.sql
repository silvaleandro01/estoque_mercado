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