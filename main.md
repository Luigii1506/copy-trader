Diapositiva 1: Título y Portada
Número y título: Diapositiva 1 — Matriz Maestra LFPIORPI y Plataforma pld.express
Objetivo de la diapositiva: Introducir el proyecto como la respuesta integral (normativa y tecnológica) ante la reforma antilavado en México.
Mensaje principal que debe recordar la audiencia: La reforma al marco Antilavado obliga a transformar el cumplimiento en un modelo automatizado y de gestión activa de riesgos
.
Contenido (3 puntos):
Marco Regulatorio: Implementación del Acuerdo 115/2026 emitido por la SHCP
.
Propuesta Integral: Fusión de consultoría especializada (Matriz Maestra) con software SaaS especializado (pld.express)
.
Motor de Inteligencia: Integración vía API con el motor de screening y grafos Sentinel
.
Visualización recomendada: Composición limpia con el logotipo institucional, acompañado de un esquema con tres bloques interconectados: Norma (Acuerdo 115/2026) ➔ Plataforma (pld.express) ➔ Inteligencia (Sentinel).
Información de respaldo: Publicación del Acuerdo 115/2026 el 7 de agosto de 2026
 y arquitectura del proyecto pld.express
.
Diapositiva 2: El Cambio Paradigmático (El Contexto)
Número y título: Diapositiva 2 — Del Cumplimiento "de Papel" a la Gestión Activa de Riesgos
Objetivo de la diapositiva: Sensibilizar a la audiencia sobre el impacto estructural del Acuerdo 115/2026 en las Actividades Vulnerables.
Mensaje principal que debe recordar la audiencia: El cumplimiento ya no es juntar carpetas físicas ni presentar avisos aislados; ahora es un sistema vivo de gestión de riesgos
.
Contenido (4 puntos):
Régimen previo: Formato documental pasivo, expedientes KYC estáticos y manuales de políticas no actualizados
.
Nuevo modelo 2026: Obligatoriedad del Enfoque Basado en Riesgos (EBR) institucional
.
Conocimiento dinámico: Segmentación por grado de riesgo individual (bajo, medio, alto) y perfiles transaccionales
.
Gobernanza reforzada: Manual de 14 contenidos obligatorios, capacitación anual y auditoría de efectividad
.
Visualización recomendada: Tabla comparativa visual en dos columnas ("Antes: Cumplimiento Documental" vs. "Ahora: Arquitectura de Riesgo Dinámica").
Información de respaldo: Matriz de cambios sustantivos del Acuerdo 115/2026
 y análisis del contexto regulatorio en México
.
Diapositiva 3: La Amenaza del Mandato Legal (El Problema)
Número y título: Diapositiva 3 — El Reloj Regulatorio: La Obligación del Artículo 41
Objetivo de la diapositiva: Evidenciar la urgencia operativa y el riesgo de sanción para los sujetos obligados antes de la fecha límite.
Mensaje principal que debe recordar la audiencia: El 1 de junio de 2027 es la fecha límite legal para que todas las Actividades Vulnerables operen con mecanismos automatizados
.
Contenido (4 puntos):
Prohibición implícita del Excel: Las hojas de cálculo e insumos manuales quedan descalificados si no cumplen las 6 funciones mínimas del Art. 41
.
Universo afectado: Miles de notarios, inmobiliarias, agencias automotrices, joyerías, mutuo y proveedores de activos virtuales (PSAV)
.
Riesgo de notificación: Notificaciones electrónicas del SAT surten efectos al 4.º día hábil, aumentando el peligro de preclusión y multas
.
Ventana de oportunidad: El mercado necesita un sistema integral especializado en menos de un año
.
Visualización recomendada: Gráfico de cuenta regresiva/cronograma resaltando la fecha 1 de junio de 2027 en rojo con un ícono de alerta sobre hojas de cálculo.
Información de respaldo: Transitorio Noveno
, Artículos 6
 y 41 de las RCG
, y análisis del mercado de Actividades Vulnerables
.
Diapositiva 4: La Solución Integral (pld.express + Sentinel)
Número y título: Diapositiva 4 — pld.express: Plataforma Especializada SaaS
Objetivo de la diapositiva: Presentar la propuesta de valor tecnológica y su integración con inteligencia de listas.
Mensaje principal que debe recordar la audiencia: pld.express resuelve el 100% de las exigencias del Acuerdo 115/2026 combinando gestión operativa e inteligencia de screening
.
Contenido (4 puntos):
Plataforma dedicada: Sistema SaaS diseñado exclusivamente para el sector no financiero / Actividades Vulnerables
.
Potenciado por Sentinel: Motor de screening conectado vía API para listas de sanciones, PEP y adverse media
.
Cobertura completa: Automatización de expedientes KYC, scoring de riesgo, acumulación y avisos
.
Tranquilidad normativa: Generación de evidencia inmutable lista para la auditoría anual
.
Visualización recomendada: Diagrama conceptual donde pld.express actúa como el centro operativo que alimenta al cliente y consume servicios de Sentinel vía API.
Información de respaldo: Especificación del producto pld.express y su arquitectura con Sentinel
.
Diapositiva 5: Arquitectura y Aislamiento de Datos
Número y título: Diapositiva 5 — Arquitectura Desacoplada y Seguridad de la Información
Objetivo de la diapositiva: Explicar la separación técnica entre la gestión de datos privados de clientes y el motor de screening público.
Mensaje principal que debe recordar la audiencia: La separación entre pld.express y Sentinel garantiza privacidad, seguridad jurídica e independencia técnica
.
Contenido (4 puntos):
Aislamiento Multi-tenant: Base de datos e infraestructura aisladas en pld.express para custodiar expedientes privados durante 10 años
.
Motor Especializado (Sentinel): Búsqueda difusa en OpenSearch sobre listas internacionales y redes de grafos
.
Consumo API seguro: Llamadas POST /screen/gold e integración de webhooks para monitoreo continuo de la cartera
.
Soberanía de Firma: La consulta PEP 2.0 ante la UIF se mantiene en el obligado mediante su propia e.firma
.
Visualización recomendada: Diagrama de arquitectura de software mostrando dos bloques (Servidor pld.express Multi-Tenant ↔ API REST ↔ Motor Sentinel OpenSearch).
Información de respaldo: Fundamento de la decisión de arquitectura y consumo API entre sistemas
.
Diapositiva 6: Flujo Operativo de Principio a Fin
Número y título: Diapositiva 6 — Flujo de Cumplimiento E2E en pld.express
Objetivo de la diapositiva: Mostrar el ciclo de vida operativo de un cliente dentro de la plataforma.
Mensaje principal que debe recordar la audiencia: El sistema automatiza cada interacción con el cliente, desde el alta hasta la presentación del aviso al SAT
.
Contenido (5 puntos):
1. Onboarding KYC: Alta con e.firma y expedientes únicos parametrizados (Anexos 1 a 10)
.
2. Screening e Identificación BC: Verificación en Sentinel y determinación de Beneficiario Controlador (>25% o control)
.
3. Scoring e Inicia Perfil: Asignación de Riesgo (bajo, medio, alto) y perfil transaccional estimado a 6 meses
.
4. Monitoreo y Acumulación: Rastreo de operaciones en ventanas móviles de hasta 6 meses en UMA y alertas
.
5. Avisos y Auditoría: Generación de XMLs ordinarios, alertas de 24h y recopilación de evidencias para el dictamen
.
Visualización recomendada: Infografía de proceso lineal horizontal con 5 pasos numerados e íconos representativos.
Información de respaldo: Módulos del sistema y flujo operativo derivado de las RCG
.
Diapositiva 7: Motor de Riesgo y Conocimiento del Cliente (EBR)
Número y título: Diapositiva 7 — Matriz EBR, Scoring e Inteligencia KYC
Objetivo de la diapositiva: Detallar cómo funciona la evaluación de riesgo individual e institucional.
Mensaje principal que debe recordar la audiencia: El scoring de riesgo individual combina variables inherentes y transaccionales con reevaluaciones automáticas
.
Contenido (4 puntos):
Factores Inherentes: Antecedentes, tipo de persona, giro, nacionalidad, residencia y fuentes de ingreso
.
Factores Transaccionales: Volumen, frecuencia, monto, instrumento monetario y geografía
.
Obligatoriedad de Riesgo Alto: Clientes no residentes vinculados a regímenes fiscales preferentes y PEP extranjeras
.
Debida Diligencia Reforzada (EDD): Cuestionarios remotos firmados digitalmente y aprobación directiva para riesgo alto
.
Visualización recomendada: Esquema tipo "Embudo de Riesgo" o matriz cuadrante (Riesgo Bajo / Medio / Alto) mostrando los detonantes de escalamiento.
Información de respaldo: Artículos 23 Bis a 23 Ter 5 del Capítulo III Bis y III Ter
.
Diapositiva 8: Acumulación, Alertas y Protocolo 24 Horas
Número y título: Diapositiva 8 — Monitoreo Transaccional y Sistema de Alertas
Objetivo de la diapositiva: Explicar el control de operaciones, límites de efectivo y detección de comportamientos inusitados.
Mensaje principal que debe recordar la audiencia: La plataforma previene omisiones acumulando montos en ventanas móviles y activando alertas en tiempo real
.
Contenido (4 puntos):
Acumulación de 6 Meses: Rastreo automatizado de actos u operaciones desde la primera transacción contra umbrales UMA
.
Control de Efectivo y Metales: Monitoreo estricto de los límites legales de pago en efectivo conforme al Art. 32
.
Motor de Alertas: Detección de desviaciones contra el perfil transaccional con bitácora de análisis y cierre
.
Protocolo de Avisos 24h: Módulo preparado para reportar sospechas o hechos/indicios en un plazo máximo de 24 horas
.
Visualización recomendada: Gráfico de barra de progreso que muestra cómo se acumulan las transacciones de un cliente hacia el umbral de aviso, con una luz de alerta al detectarse una desviación.
Información de respaldo: Artículos 19
, 23 Ter 2
, 26 Bis
 y 41
.
Diapositiva 9: Gobernanza, Capacitación y Evidencia Inmutable
Número y título: Diapositiva 9 — Gobernanza Institucional y Control Interno
Objetivo de la diapositiva: Presentar los módulos de soporte normativo que protegen a la empresa ante inspecciones y auditorías.
Mensaje principal que debe recordar la audiencia: El sistema no solo monitorea operaciones, también gestiona la gobernanza interna y genera prueba inmutable
.
Contenido (4 puntos):
Manual de Políticas Internas: Módulo parametrizado para gestionar los 14 contenidos obligatorios y el control de versiones
.
Programa de Capacitación: Control de cursos anuales, evaluaciones aplicadas y emisión de constancias con retención de 10 años
.
Selección de Personal: Registro y custodia de declaraciones firmadas de honorabilidad y experiencia para nuevas contrataciones
.
Audit Trail de 10 Años: Bitácora inalterable que conserva registros de scoring, perfil y decisiones para el auditor
.
Visualización recomendada: Escudo de protección dividido en 4 cuadrantes (Manual, Capacitación, RH, Bitácora Inmutable).
Información de respaldo: Capítulos X
, XII
, XIII
 y XIV
 de las RCG.
Diapositiva 10: Estado Actual y Entregables del Proyecto
Número y título: Diapositiva 10 — Madurez del Proyecto y Entregables Actuales
Objetivo de la diapositiva: Demostrar el avance real del proyecto y la solidez de sus fundamentos metodológicos.
Mensaje principal que debe recordar la audiencia: El proyecto cuenta con un diseño técnico y jurídico terminado, listo para la fase de construcción del software
.
Contenido (4 puntos):
Matriz Maestra de Impacto: Análisis exhaustivo que conecta la norma con el proceso, dato fuente, control y prueba
.
Especificación de Arquitectura: Diseño del modelo de datos de pld.express (20 entidades) y contrato de API con Sentinel
.
Mapeo Regulatorio Traducido: Mapeo normativo completo transformado en especificaciones para los 8 módulos del sistema
.
Estrategia de Mercado: Definición de empaquetado por Actividad Vulnerable y modelo de precios escalable
.
Visualización recomendada: Diagrama de pastel o barra de estado que muestre el 100% completado en la fase de Análisis y Diseño Jurídico-Técnico.
Información de respaldo: Matriz comparativa de Grupo Asesores en Negocios
 y documento de diseño de producto pld.express
.
Diapositiva 11: Ventajas Competitivas Frente a Alternativas
Número y título: Diapositiva 11 — Por qué pld.express es la Mejor Opción
Objetivo de la diapositiva: Comparar la solución contra los competidores del mercado y procesos manuales.
Mensaje principal que debe recordar la audiencia: Offrece la máxima cobertura normativa al menor costo de adopción para el sector no financiero
.
Contenido (4 puntos):
Frente a Procesos Manuales / Excel: Elimina el riesgo de sanciones, errores en acumulación semestral y falta de trazabilidad
.
Frente a Suites Financieras (ej. Cumplex): Diseñado específicamente para Actividades Vulnerables con tarifas accesibles por volumen
.
Frente a Software Superficial: Incluye la metodología EBR completa, el Manual de 14 puntos y el módulo de dictamen de auditoría
.
Screening Integrado de Alta Calidad: Potenciado por la inteligencia de grafos y adverse media de Sentinel
.
Visualización recomendada: Cuadro comparativo de 4 columnas (Criterio, Excel, Software Bancario, pld.express) con marcas de verificación (Checkmarks) y cruces.
Información de respaldo: Análisis del mercado y diferenciadores competitivos de pld.express
.
Diapositiva 12: Roadmap de Construcción e Implementación
Número y título: Diapositiva 12 — Cronograma Regulatorio y Fases de Desarrollo
Objetivo de la diapositiva: Trazar la ruta de entregables alineada a las fechas críticas fijadas por la ley.
Mensaje principal que debe recordar la audiencia: El desarrollo por fases garantiza el cumplimiento de cada hito regulatorio entre 2026 y 2029
.
Contenido (4 puntos):
Fase 1 (Diciembre 2026 – Febrero 2027): Core multi-tenant, Módulo KYC, Beneficiario Controlador y screening con Sentinel (Listo para el hito del 1 de marzo)
.
Fase 2 (Marzo – Mayo 2027): Acumulación, scoring de riesgo, perfiles y alertas transaccionales (Listo para el hito del 1 de junio de 2027)
.
Fase 3 (Junio – Diciembre 2027): Avisos XML, plantilla de Manual de 14 puntos, Capacitación y Selección de Personal
.
Fase 4 (2028 – 2029): Módulo de Auditoría Anual, proyección de multas y generación del dictamen para marzo de 2029
.
Visualización recomendada: Línea de tiempo horizontal (Roadmap) con 4 hitos destacados y banderas de colores sobre las fechas legales de la SHCP.
Información de respaldo: Cronograma consolidado 2026–2028
 y orden de construcción en 8 fases
.
Diapositiva 13: Riesgos, Limitaciones y Estrategia de Mitigación
Número y título: Diapositiva 13 — Gestión de Riesgos del Proyecto y Próximos Pasos
Objetivo de la diapositiva: Transmitir prudencia, rigor técnico y claridad sobre los límites operativos de la solución.
Mensaje principal que debe recordar la audiencia: El proyecto tiene identificados sus riesgos técnicos y regulatorios con planes claros de mitigación
.
Contenido (4 puntos):
Soberanía de e.firma: La plataforma no suplanta la e.firma del obligado; facilita la integración y custodia evidencias de la Consulta PEP 2.0
.
Avisos de 24 Horas: Módulo condicionado a la publicación oficial de los nuevos formatos XML por parte de la UIF/SAT (Transitorio 5.º)
.
Licencias de Fuentes: Pendiente formalizar los acuerdos comerciales de distribución masiva de listas internacionales
.
Siguiente Paso Impartible: Iniciar la construcción del Núcleo Multi-tenant y Módulo KYC (Fase 1) para asegurar las entregas de 2027
.
Visualización recomendada: Matriz de Riesgo / Mitigación de 2 columnas o lista de verificación de acciones inmediatas.
Información de respaldo: Transitorio Quinto
, puntos a tener claros antes de empezar
 y fases de desarrollo
.