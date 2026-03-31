CREATE DATABASE IF NOT EXISTS estoque_mercado;
USE `estoque_mercado`;

CREATE TABLE `setor` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(255) NOT NULL,
    `tipo` VARCHAR(50) NOT NULL,
    UNIQUE KEY `unique_tipo` (`tipo`)
) ENGINE=InnoDB;

CREATE TABLE `funcionario` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `nome` VARCHAR(100) NOT NULL,
    `sobrenome` VARCHAR(100) NOT NULL,
    `data_nascimento` DATE NOT NULL,
    `genero` VARCHAR(20) NOT NULL,
    `cargo` VARCHAR(50) NOT NULL DEFAULT 'operacional',
    `possui_filhos` BOOLEAN NOT NULL DEFAULT FALSE,
    `setor_id` INT NOT NULL,
    `is_admin` BOOLEAN NOT NULL DEFAULT FALSE,
    `password_hash` VARCHAR(255),
    `last_password_change` DATETIME,
    `token` VARCHAR(255), -- Reduzido para 255 para garantir compatibilidade de index
    `token_expiracao` DATETIME,
    KEY `idx_token` (`token`),
    CONSTRAINT `fk_func_setor` FOREIGN KEY (`setor_id`) REFERENCES `setor` (`id`)
) ENGINE=InnoDB;

CREATE TABLE `estoque` (
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

CREATE TABLE `venda` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data DATETIME DEFAULT CURRENT_TIMESTAMP,
    valor_total DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    funcionario_id INT NOT NULL,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE `itemvenda` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    venda_id INT NOT NULL,
    codigodebarras VARCHAR(100) NOT NULL,
    quantidade INT NOT NULL,
    preco_unitario DECIMAL(10, 2) NOT NULL,
    preco_total DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (venda_id) REFERENCES venda(id)
) ENGINE=InnoDB;

CREATE TABLE `log` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    tipo_movimentacao VARCHAR(255) NOT NULL,
    data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE `ponto` (
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

CREATE TABLE `salario` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL UNIQUE,
    valor_mensal DECIMAL(10, 2) DEFAULT 0.00,
    valor_hora DECIMAL(10, 2) DEFAULT 0.00,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE `salariohistorico` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    valor_antigo DECIMAL(10, 2) NOT NULL,
    valor_novo DECIMAL(10, 2) NOT NULL,
    data_alteracao DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;

CREATE TABLE `holerite` (
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

CREATE TABLE `senhahistorico` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    funcionario_id INT NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (funcionario_id) REFERENCES funcionario(id)
) ENGINE=InnoDB;