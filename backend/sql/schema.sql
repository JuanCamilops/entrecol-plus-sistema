-- ==========================================================
-- ESQUEMA MYSQL / MARIADB (XAMPP) generado desde los 4 MER:
--   1. Seguridad y Auditoría   2. Nómina   3. Libros   4. Películas
-- Los módulos Nómina, Libros y Películas usan los mismos nombres de tablas
-- y columnas que Bse_DDL.sql (Integrante 1)
-- Se ejecuta con: python init_db.py   (o importándolo en phpMyAdmin)
-- Nota: no usar punto y coma dentro de comentarios (init_db separa por ese carácter)
-- ==========================================================

-- ----------------------------------------------------------
-- MÓDULO SEGURIDAD Y AUDITORÍA
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS rol (
    id_rol        INT AUTO_INCREMENT PRIMARY KEY,
    nombre        VARCHAR(30)  NOT NULL UNIQUE,
    descripcion   VARCHAR(200)
) ENGINE=InnoDB;

-- TIENE_ROL: USUARIO (1,1) -- ROL (0,N)
CREATE TABLE IF NOT EXISTS usuario (
    id_usuario        INT AUTO_INCREMENT PRIMARY KEY,
    username          VARCHAR(50)  NOT NULL UNIQUE,
    password_hash     VARCHAR(255) NOT NULL,
    correo            VARCHAR(120) NOT NULL UNIQUE,
    activo            TINYINT(1)   NOT NULL DEFAULT 1,
    intentos_fallidos INT          NOT NULL DEFAULT 0,
    fecha_creacion    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    id_rol            INT          NOT NULL,
    CONSTRAINT fk_usuario_rol FOREIGN KEY (id_rol) REFERENCES rol(id_rol)
) ENGINE=InnoDB;

-- GENERA: USUARIO (0,N) -- AUDITORIA (1,1)
-- id_usuario admite NULL solo para intentos de login con un usuario que no existe
CREATE TABLE IF NOT EXISTS auditoria (
    id_auditoria   BIGINT AUTO_INCREMENT PRIMARY KEY,
    id_usuario     INT NULL,
    accion         VARCHAR(30)  NOT NULL,
    tabla_afectada VARCHAR(50),
    fecha_hora     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip             VARCHAR(45),
    detalle        TEXT,
    CONSTRAINT fk_auditoria_usuario FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario),
    INDEX idx_auditoria_fecha (fecha_hora),
    INDEX idx_auditoria_accion (accion)
) ENGINE=InnoDB;

-- REALIZA: USUARIO (0,N) -- CARGA_ARCHIVO (1,1)
CREATE TABLE IF NOT EXISTS carga_archivo (
    id_carga             INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario           INT          NOT NULL,
    nombre_archivo       VARCHAR(255) NOT NULL,
    tipo_archivo         VARCHAR(30)  NOT NULL,
    fecha_hora           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    registros_leidos     INT          NOT NULL DEFAULT 0,
    registros_cargados   INT          NOT NULL DEFAULT 0,
    registros_rechazados INT          NOT NULL DEFAULT 0,
    estado               VARCHAR(20)  NOT NULL DEFAULT 'PROCESANDO',
    CONSTRAINT fk_carga_usuario FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario)
) ENGINE=InnoDB;

-- ----------------------------------------------------------
-- MÓDULO NÓMINA
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS departamento (
    departamento_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_departamento_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS cargo (
    cargo_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre   VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_cargo_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS eps (
    eps_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_eps_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS arl (
    arl_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_arl_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fondo_pension (
    fondo_pension_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre           VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_fondo_pension_nombre (nombre)
) ENGINE=InnoDB;

-- PERTENECE_A, DESEMPEÑA, AFILIADO_EPS, COTIZA_PENSION, AFILIADO_ARL: EMPLEADO (1,1) -- catálogo (0,N)
CREATE TABLE IF NOT EXISTS empleado (
    empleado_id      VARCHAR(20)   NOT NULL COMMENT 'Código original de nómina',
    nombre_completo  VARCHAR(150)  NOT NULL,
    departamento_id  INT           NOT NULL,
    cargo_id         INT           NOT NULL,
    fecha_ingreso    DATE          NOT NULL,
    eps_id           INT           NOT NULL,
    arl_id           INT           NOT NULL,
    fondo_pension_id INT           NOT NULL,
    sueldo_base      DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (empleado_id),
    CONSTRAINT chk_empleado_sueldo CHECK (sueldo_base >= 0),
    CONSTRAINT fk_empleado_departamento FOREIGN KEY (departamento_id)
        REFERENCES departamento (departamento_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_empleado_cargo FOREIGN KEY (cargo_id)
        REFERENCES cargo (cargo_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_empleado_eps FOREIGN KEY (eps_id)
        REFERENCES eps (eps_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_empleado_arl FOREIGN KEY (arl_id)
        REFERENCES arl (arl_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_empleado_pension FOREIGN KEY (fondo_pension_id)
        REFERENCES fondo_pension (fondo_pension_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    KEY ix_empleado_departamento (departamento_id),
    KEY ix_empleado_cargo (cargo_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS periodo_nomina (
    periodo_id   INT      AUTO_INCREMENT PRIMARY KEY,
    anio         SMALLINT NOT NULL,
    mes          TINYINT  NOT NULL,
    fecha_inicio DATE     NOT NULL,
    fecha_fin    DATE     NOT NULL,
    UNIQUE KEY uq_periodo_anio_mes (anio, mes),
    CONSTRAINT chk_periodo_mes CHECK (mes BETWEEN 1 AND 12),
    CONSTRAINT chk_periodo_fechas CHECK (fecha_fin >= fecha_inicio)
) ENGINE=InnoDB;

-- LIQUIDA (relación N:M con atributos): EMPLEADO (0,N) -- PERIODO_NOMINA (0,N)
-- Una fila por empleado y periodo (uq_detalle_periodo_empleado)
CREATE TABLE IF NOT EXISTS detalle_nomina (
    detalle_nomina_id  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    periodo_id         INT           NOT NULL,
    empleado_id        VARCHAR(20)   NOT NULL,
    dias_trabajados    TINYINT       NOT NULL DEFAULT 0,
    dias_incapacidad   DECIMAL(5,2)  NOT NULL DEFAULT 0,
    dias_vacaciones    DECIMAL(5,2)  NOT NULL DEFAULT 0,
    bonificacion       DECIMAL(12,2) NOT NULL DEFAULT 0,
    auxilio_transporte DECIMAL(12,2) NOT NULL DEFAULT 0,
    UNIQUE KEY uq_detalle_periodo_empleado (periodo_id, empleado_id),
    CONSTRAINT chk_detalle_dias CHECK (
        dias_trabajados >= 0 AND dias_incapacidad >= 0 AND dias_vacaciones >= 0
    ),
    CONSTRAINT chk_detalle_dias_max CHECK (dias_trabajados <= 30),
    CONSTRAINT chk_detalle_valores CHECK (bonificacion >= 0 AND auxilio_transporte >= 0),
    CONSTRAINT fk_detalle_periodo FOREIGN KEY (periodo_id)
        REFERENCES periodo_nomina (periodo_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_detalle_empleado FOREIGN KEY (empleado_id)
        REFERENCES empleado (empleado_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

-- REGISTRA_NOVEDAD: DETALLE_NOMINA (0,N) -- NOVEDAD_NOMINA (1,1)
-- Reemplaza a las tablas incapacidad y vacaciones (tipo_novedad distingue el caso)
CREATE TABLE IF NOT EXISTS novedad_nomina (
    novedad_id        BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    detalle_nomina_id BIGINT UNSIGNED NOT NULL,
    tipo_novedad      ENUM('INCAPACIDAD','VACACIONES') NOT NULL,
    fecha_inicio      DATE NOT NULL,
    fecha_fin         DATE NOT NULL,
    observacion       VARCHAR(255) NULL,
    CONSTRAINT chk_novedad_fechas CHECK (fecha_fin >= fecha_inicio),
    CONSTRAINT fk_novedad_detalle FOREIGN KEY (detalle_nomina_id)
        REFERENCES detalle_nomina (detalle_nomina_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    KEY ix_novedad_tipo_fechas (tipo_novedad, fecha_inicio, fecha_fin)
) ENGINE=InnoDB;

-- ----------------------------------------------------------
-- MÓDULO LIBROS
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS autor (
    autor_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre   VARCHAR(200) NOT NULL,
    UNIQUE KEY uq_autor_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS editorial (
    editorial_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre       VARCHAR(200) NOT NULL,
    UNIQUE KEY uq_editorial_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS idioma (
    idioma_id INT AUTO_INCREMENT PRIMARY KEY,
    codigo    VARCHAR(10) NOT NULL,
    UNIQUE KEY uq_idioma_codigo (codigo)
) ENGINE=InnoDB;

-- PUBLICADO_POR: LIBRO (1,1) -- EDITORIAL (0,N)
-- ESCRITO_EN:    LIBRO (1,1) -- IDIOMA (0,N)
CREATE TABLE IF NOT EXISTS libro (
    libro_id          INT PRIMARY KEY,
    titulo            VARCHAR(500) NOT NULL,
    isbn              VARCHAR(13),
    isbn13            VARCHAR(13),
    numero_paginas    INT,
    promedio_rating   DECIMAL(3,2),
    cantidad_ratings  INT NOT NULL DEFAULT 0,
    cantidad_resenas  INT NOT NULL DEFAULT 0,
    fecha_publicacion DATE,
    editorial_id      INT NOT NULL,
    idioma_id         INT NOT NULL,
    UNIQUE KEY uq_libro_isbn (isbn),
    UNIQUE KEY uq_libro_isbn13 (isbn13),
    CONSTRAINT chk_libro_rating CHECK (promedio_rating IS NULL OR promedio_rating BETWEEN 0 AND 5),
    CONSTRAINT chk_libro_paginas CHECK (numero_paginas IS NULL OR numero_paginas >= 0),
    CONSTRAINT fk_libro_editorial FOREIGN KEY (editorial_id)
        REFERENCES editorial (editorial_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_libro_idioma FOREIGN KEY (idioma_id)
        REFERENCES idioma (idioma_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    KEY ix_libro_titulo (titulo(191)),
    KEY ix_libro_editorial (editorial_id)
) ENGINE=InnoDB;

-- ESCRITO_POR (N:M): LIBRO (1,N) -- AUTOR (0,N)
CREATE TABLE IF NOT EXISTS libro_autor (
    libro_id      INT NOT NULL,
    autor_id      INT NOT NULL,
    orden_autoria SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    CONSTRAINT pk_libro_autor PRIMARY KEY (libro_id, autor_id),
    UNIQUE KEY uq_libro_orden_autoria (libro_id, orden_autoria),
    CONSTRAINT fk_la_libro FOREIGN KEY (libro_id)
        REFERENCES libro (libro_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_la_autor FOREIGN KEY (autor_id)
        REFERENCES autor (autor_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    KEY ix_la_autor (autor_id)
) ENGINE=InnoDB;

-- ----------------------------------------------------------
-- MÓDULO PELÍCULAS
-- ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS pelicula (
    pelicula_id  INT PRIMARY KEY,
    titulo       VARCHAR(300) NOT NULL,
    anio_estreno SMALLINT,
    KEY ix_pelicula_titulo (titulo),
    KEY ix_pelicula_anio (anio_estreno)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS genero_pelicula (
    genero_id INT AUTO_INCREMENT PRIMARY KEY,
    nombre    VARCHAR(60) NOT NULL,
    UNIQUE KEY uq_genero_nombre (nombre)
) ENGINE=InnoDB;

-- TIENE_GENERO (N:M): PELICULA (1,N) -- GENERO_PELICULA (0,N)
CREATE TABLE IF NOT EXISTS pelicula_genero (
    pelicula_id INT NOT NULL,
    genero_id   INT NOT NULL,
    CONSTRAINT pk_pelicula_genero PRIMARY KEY (pelicula_id, genero_id),
    CONSTRAINT fk_pg_pelicula FOREIGN KEY (pelicula_id)
        REFERENCES pelicula (pelicula_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_pg_genero FOREIGN KEY (genero_id)
        REFERENCES genero_pelicula (genero_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    KEY ix_pg_genero (genero_id)
) ENGINE=InnoDB;

-- ----------------------------------------------------------
-- DATOS SEMILLA
-- (el usuario administrador lo crea init_db.py con la contraseña cifrada)
-- ----------------------------------------------------------
INSERT IGNORE INTO rol (nombre, descripcion) VALUES
 ('ADMIN',    'Acceso total: usuarios, roles, auditoría, CRUD y cargas'),
 ('OPERADOR', 'CRUD de los módulos, cargas de archivos y consultas'),
 ('CONSULTA', 'Solo lectura y consultas');

INSERT IGNORE INTO eps (nombre) VALUES ('Sura EPS'), ('Sanitas'), ('Nueva EPS'), ('Compensar'), ('Salud Total'), ('Famisanar');
INSERT IGNORE INTO fondo_pension (nombre) VALUES ('Porvenir'), ('Protección'), ('Colfondos'), ('Skandia'), ('Colpensiones');
INSERT IGNORE INTO arl (nombre) VALUES ('ARL Sura'), ('Positiva'), ('Colmena'), ('Seguros Bolívar'), ('AXA Colpatria');
