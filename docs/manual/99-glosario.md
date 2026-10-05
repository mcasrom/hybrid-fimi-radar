# Glosario del Observatorio

> Extraído de /glosario.html el 2026-10-05. Fuente viva: la página web; este fichero es su reflejo versionado (se puede ampliar).

## Términos del radar

- **Evento**: Una pieza pública capturada (mensaje, post o noticia) con su fuente, autor y fecha.
- **Tema**: Ámbito que se monitoriza por separado (p. ej. frontera_sur , oriente_medio ). Un evento puede pertenecer a varios temas.
- **Cluster**: Grupo de cuentas/eventos que comparten contenido o publican en ventanas temporales similares. Es la unidad que el radar puntúa.
- **Coordinación**: Grado en que varias cuentas publican lo mismo en momentos parecidos. Mide comportamiento , no intención.
- **Sincronización**: Componente de la coordinación que mide la proximidad temporal entre publicaciones.
- **Anomalía**: Desviación del comportamiento esperado (volumen o ritmo) respecto a la norma de la cuenta o de la red.
- **Infraestructura**: Señales de infraestructura compartida entre cuentas (p. ej. los mismos dominios o enlaces).
- **Densidad de red**: Cuán interconectado está un grupo de cuentas. Se muestra como dato, pero no pondera en el score (se retiró por doble conteo); la cohesión del núcleo la mide el k-core .
- **k-core**: Subconjunto de cuentas donde cada una está conectada con al menos k de las demás. Un k-core alto indica un núcleo cohesionado.
- **Banda**: Nivel de alerta según la puntuación 0-100: Normal (NORMAL, 0-19) · En observación (WATCH, 20-39) · Amplificación anómala (ANOMALOUS, 40-59) · Amplificación alta (HIGH, 60-79) · Amplificación muy alta (CRITICAL, 80-100).
- **Puntuación global**: Valor 0-100 que combina los componentes (coordinación, contenido similar, amplificación, infraestructura y anomalía) según los pesos documentados.
- **Gate**: Condición obligatoria para alcanzar una banda. Ej.: HIGH exige ≥3 cuentas y anomalía ≥20; CRITICAL exige ≥10 cuentas y anomalía ≥40.
- **Narrativa amplificada**: Un mismo contenido reproducido por muchos medios o cuentas. Es eco ; no implica coordinación.
- **Cascada**: Difusión en cadena de una pieza de unos nodos a otros.
- **Hipótesis H1–H6**: Seis explicaciones alternativas de atribución que el sistema contrasta, para evitar el sesgo de confirmación.
- **Atribución**: Intento de identificar quién está detrás. El radar es deliberadamente conservador y a menudo concluye NO_ATTRIBUTION .
- **NO_ATTRIBUTION**: Resultado válido: no hay base suficiente para atribuir autoría. No es un fallo, es honestidad metodológica.
- **lineage_id**: Identificador estable de un cluster a lo largo del tiempo. Los cluster_label cambian en cada ciclo; el lineage_id no.
- **Tipología estructural**: Clasificación del cluster por su forma (cómo se coordina), no por su contenido.
- **Ventana**: Periodo temporal de análisis (en horas) en el que se agrupan los eventos.
- **Piso de escala**: Regla que impide que muy pocas cuentas alcancen bandas altas (evita sobrevalorar parejas aisladas).
- **Techo de escala**: Límite superior de banda en función del número de cuentas.
- **Origen único**: Cuando un cluster es eco de una sola pieza: como máximo alcanza ANOMALOUS.
- **mainstream_cap**: Si el eco es ≥80 % prensa consolidada, el cluster no pasa de ANOMALOUS.
- **event_temas**: Relación evento ↔ tema: un evento puede estar en varios temas a la vez.
- **Bitácora**: Registro de los cambios de estado de un tema (inicio, cierre, notas), con motivos metodológicos.
- **Validación (3 capas)**: Sintética (mecánica) · Curada (muestra etiquetada a mano) · Externa (contraste con un corpus documentado).

## Términos de amenazas híbridas

- **Zona gris**: Espacio entre la paz y el conflicto armado donde se mueven acciones de presión, coerción o desestabilización sin llegar a la guerra abierta.
- **Incursión**: Actuación física limitada (p. ej. un dron que sobrevuela o interfiere). Por sí sola no demuestra campaña ni intención: puede ser coerción, error o simple incidente.
- **Coerción**: Presión para forzar una decisión sin emplear fuerza armada abierta (mostrar capacidad, perturbar, señalar).
- **Amenaza híbrida**: Uso combinado por un actor (estatal o no) de medios militares y no militares —ciber, desinformación, presión económica, instrumentalización migratoria…— por debajo del umbral del conflicto armado. Actor-neutral: no es exclusivo de Rusia.
- **Ataque híbrido**: Acción híbrida con daño/intensidad y, típicamente, dirección estatal + intención + denegabilidad . No es lo mismo que una incursión o una presión en sentido amplio.

## Siglas y acrónimos

- **FIMI**: Foreign Information Manipulation and Interference : manipulación e interferencia informativa de origen extranjero.
- **OSINT**: Open Source Intelligence : inteligencia a partir de fuentes abiertas (contenido público).
- **ARI**: Adjusted Rand Index : métrica de validación del clustering. 1.000 = separación perfecta (test sintético).
- **TF-IDF**: Term Frequency – Inverse Document Frequency : técnica para medir la importancia de un término en un texto frente a un corpus.
- **RDAP**: Registration Data Access Protocol : consulta pública de datos de registro de dominios (usado para señales de infraestructura).
- **RGPD**: Reglamento General de Protección de Datos (UE). El radar usa solo contenido público y no rastrea.
- **KPI**: Key Performance Indicator : indicador clave de rendimiento.
- **EEAS**: European External Action Service : Servicio Europeo de Acción Exterior.
- **ENISA**: Agencia de Ciberseguridad de la Unión Europea.
- **EDMO**: European Digital Media Observatory : observatorio europeo de medios digitales (red de verificadores e investigadores).
- **UE**: Unión Europea.

## Términos técnicos

- **API**: Application Programming Interface : interfaz para que otros programas consulten los datos (aquí, API pública v1 read-only).
- **CLI**: Command Line Interface : uso por línea de comandos.
- **RSS**: Really Simple Syndication : formato de sindicación de contenidos (feeds).
- **JSON**: JavaScript Object Notation : formato de datos legible por máquinas.
- **CSV**: Comma-Separated Values : formato de exportación en texto tabular.
- **HTML**: HyperText Markup Language : lenguaje de las páginas web.
- **HTTP / HSTS**: HyperText Transfer Protocol y su variante segura forzada ( HTTP Strict Transport Security ).
- **URL**: Uniform Resource Locator : dirección de un recurso en la web.
- **BD**: Base de datos.
- **SQL / SQLite**: Structured Query Language y el motor de base de datos ligero embebido que usa el radar.
- **SQLi**: SQL Injection : ataque que inyecta código SQL a través de entradas.
- **CORS / CSP**: Cross-Origin Resource Sharing y Content Security Policy : mecanismos de seguridad del navegador.
- **CTA**: Call To Action : llamada a la acción (p. ej. suscribirse).
- **MVP**: Minimum Viable Product : producto mínimo viable.
- **LLM**: Large Language Model : modelo grande de lenguaje (IA generativa).
- **RAM / OOM**: Memoria de acceso aleatorio y su agotamiento ( Out Of Memory ).

