
CREATE DATABASE IF NOT EXISTS proyecto_integrador
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE proyecto_integrador;


-- 1. NOMINA


CREATE TABLE IF NOT EXISTS departamento (
    departamento_id SMALLINT UNSIGNED AUTO_INCREMENT,
    nombre          VARCHAR(100) NOT NULL,
    PRIMARY KEY (departamento_id),
    UNIQUE KEY uq_departamento_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS cargo (
    cargo_id SMALLINT UNSIGNED AUTO_INCREMENT,
    nombre   VARCHAR(120) NOT NULL,
    PRIMARY KEY (cargo_id),
    UNIQUE KEY uq_cargo_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS eps (
    eps_id SMALLINT UNSIGNED AUTO_INCREMENT,
    nombre VARCHAR(100) NOT NULL,
    PRIMARY KEY (eps_id),
    UNIQUE KEY uq_eps_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS arl (
    arl_id SMALLINT UNSIGNED AUTO_INCREMENT,
    nombre VARCHAR(100) NOT NULL,
    PRIMARY KEY (arl_id),
    UNIQUE KEY uq_arl_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fondo_pension (
    fondo_pension_id SMALLINT UNSIGNED AUTO_INCREMENT,
    nombre VARCHAR(100) NOT NULL,
    PRIMARY KEY (fondo_pension_id),
    UNIQUE KEY uq_fondo_pension_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS empleado (
    empleado_id       INT UNSIGNED NOT NULL COMMENT 'Código original de nómina',
    nombre_completo   VARCHAR(160) NOT NULL,
    departamento_id   SMALLINT UNSIGNED NOT NULL,
    cargo_id          SMALLINT UNSIGNED NOT NULL,
    fecha_ingreso     DATE NOT NULL,
    eps_id            SMALLINT UNSIGNED NOT NULL,
    arl_id            SMALLINT UNSIGNED NOT NULL,
    fondo_pension_id  SMALLINT UNSIGNED NOT NULL,
    sueldo_base       DECIMAL(13,2) NOT NULL,
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
    periodo_id SMALLINT UNSIGNED AUTO_INCREMENT,
    anio       YEAR NOT NULL,
    mes        TINYINT UNSIGNED NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin    DATE NOT NULL,
    PRIMARY KEY (periodo_id),
    UNIQUE KEY uq_periodo_anio_mes (anio, mes),
    CONSTRAINT chk_periodo_mes CHECK (mes BETWEEN 1 AND 12),
    CONSTRAINT chk_periodo_fechas CHECK (fecha_fin >= fecha_inicio)
) ENGINE=InnoDB;

-- Una fila por empleado y periodo. Los valores monetarios se almacenan
-- separados del sueldo base para conservar el detalle de cada liquidación.
CREATE TABLE IF NOT EXISTS detalle_nomina (
    detalle_nomina_id BIGINT UNSIGNED AUTO_INCREMENT,
    periodo_id        SMALLINT UNSIGNED NOT NULL,
    empleado_id       INT UNSIGNED NOT NULL,
    dias_trabajados   DECIMAL(5,2) NOT NULL DEFAULT 0,
    dias_incapacidad  DECIMAL(5,2) NOT NULL DEFAULT 0,
    dias_vacaciones   DECIMAL(5,2) NOT NULL DEFAULT 0,
    bonificacion      DECIMAL(13,2) NOT NULL DEFAULT 0,
    auxilio_transporte DECIMAL(13,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (detalle_nomina_id),
    UNIQUE KEY uq_detalle_periodo_empleado (periodo_id, empleado_id),
    CONSTRAINT chk_detalle_dias CHECK (
        dias_trabajados >= 0 AND dias_incapacidad >= 0 AND dias_vacaciones >= 0
    ),
    CONSTRAINT chk_detalle_valores CHECK (bonificacion >= 0 AND auxilio_transporte >= 0),
    CONSTRAINT fk_detalle_periodo FOREIGN KEY (periodo_id)
        REFERENCES periodo_nomina (periodo_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_detalle_empleado FOREIGN KEY (empleado_id)
        REFERENCES empleado (empleado_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS novedad_nomina (
    novedad_id BIGINT UNSIGNED AUTO_INCREMENT,
    detalle_nomina_id BIGINT UNSIGNED NOT NULL,
    tipo_novedad ENUM('INCAPACIDAD','VACACIONES') NOT NULL,
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    observacion VARCHAR(255) NULL,
    PRIMARY KEY (novedad_id),
    CONSTRAINT chk_novedad_fechas CHECK (fecha_fin >= fecha_inicio),
    CONSTRAINT fk_novedad_detalle FOREIGN KEY (detalle_nomina_id)
        REFERENCES detalle_nomina (detalle_nomina_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    KEY ix_novedad_tipo_fechas (tipo_novedad, fecha_inicio, fecha_fin)
) ENGINE=InnoDB;


-- 2. CATALOGO DE PELICULAS (movies.dat)


CREATE TABLE IF NOT EXISTS pelicula (
    pelicula_id INT UNSIGNED NOT NULL COMMENT 'movieID del archivo movies.dat',
    titulo      VARCHAR(255) NOT NULL,
    anio_estreno SMALLINT UNSIGNED NULL,
    PRIMARY KEY (pelicula_id),
    KEY ix_pelicula_titulo (titulo),
    KEY ix_pelicula_anio (anio_estreno)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS genero_pelicula (
    genero_id SMALLINT UNSIGNED AUTO_INCREMENT,
    nombre    VARCHAR(60) NOT NULL,
    PRIMARY KEY (genero_id),
    UNIQUE KEY uq_genero_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pelicula_genero (
    pelicula_id INT UNSIGNED NOT NULL,
    genero_id   SMALLINT UNSIGNED NOT NULL,
    PRIMARY KEY (pelicula_id, genero_id),
    CONSTRAINT fk_pg_pelicula FOREIGN KEY (pelicula_id)
        REFERENCES pelicula (pelicula_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_pg_genero FOREIGN KEY (genero_id)
        REFERENCES genero_pelicula (genero_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    KEY ix_pg_genero (genero_id)
) ENGINE=InnoDB;


-- 3. CATALOGO DE LIBROS 


CREATE TABLE IF NOT EXISTS editorial (
    editorial_id INT UNSIGNED AUTO_INCREMENT,
    nombre       VARCHAR(180) NOT NULL,
    PRIMARY KEY (editorial_id),
    UNIQUE KEY uq_editorial_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS idioma (
    idioma_id SMALLINT UNSIGNED AUTO_INCREMENT,
    codigo    VARCHAR(12) NOT NULL,
    PRIMARY KEY (idioma_id),
    UNIQUE KEY uq_idioma_codigo (codigo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS autor (
    autor_id INT UNSIGNED AUTO_INCREMENT,
    nombre   VARCHAR(220) NOT NULL,
    PRIMARY KEY (autor_id),
    UNIQUE KEY uq_autor_nombre (nombre)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS libro (
    libro_id          INT UNSIGNED NOT NULL COMMENT 'bookID del JSON',
    titulo            VARCHAR(500) NOT NULL,
    isbn              VARCHAR(20) NULL,
    isbn13            CHAR(13) NULL,
    idioma_id         SMALLINT UNSIGNED NULL,
    numero_paginas    SMALLINT UNSIGNED NULL,
    promedio_rating   DECIMAL(3,2) NULL,
    cantidad_ratings  INT UNSIGNED NOT NULL DEFAULT 0,
    cantidad_resenas  INT UNSIGNED NOT NULL DEFAULT 0,
    fecha_publicacion DATE NULL,
    editorial_id      INT UNSIGNED NULL,
    PRIMARY KEY (libro_id),
    UNIQUE KEY uq_libro_isbn (isbn),
    UNIQUE KEY uq_libro_isbn13 (isbn13),
    CONSTRAINT chk_libro_rating CHECK (promedio_rating IS NULL OR promedio_rating BETWEEN 0 AND 5),
    CONSTRAINT fk_libro_idioma FOREIGN KEY (idioma_id)
        REFERENCES idioma (idioma_id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_libro_editorial FOREIGN KEY (editorial_id)
        REFERENCES editorial (editorial_id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    KEY ix_libro_titulo (titulo(191)),
    KEY ix_libro_editorial (editorial_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS libro_autor (
    libro_id INT UNSIGNED NOT NULL,
    autor_id INT UNSIGNED NOT NULL,
    orden_autoria SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (libro_id, autor_id),
    UNIQUE KEY uq_libro_orden_autoria (libro_id, orden_autoria),
    CONSTRAINT fk_la_libro FOREIGN KEY (libro_id)
        REFERENCES libro (libro_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_la_autor FOREIGN KEY (autor_id)
        REFERENCES autor (autor_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    KEY ix_la_autor (autor_id)
) ENGINE=InnoDB;


