# Guía de prueba del RAG — PRO-02

Preguntas para comprobar cómo responde el sistema con el documento real cargado:
**PRO 02 - Liderazgo Rev 07** (procedimiento de AR Consultores, Word).

El manual de prueba y la ISO 9001 se desactivaron. Cuando se carguen otros procedimientos o normas, se agregan sus preguntas acá y en `evaluar.py`.

Las respuestas esperadas salen del texto del documento. El modelo puede redactar distinto: lo que importa es **el dato** y **la cita**.

## Cómo probar

**Automático** (las 22 preguntas, unos 3 minutos):

```bash
python evaluar.py
```

Opciones: `--solo 6,30` (algunas), `--veces 2` (repetir), `--detalle` (ver cada respuesta).

**A mano**:

```bash
python ask.py
```

| Marca | Significa |
|---|---|
| ✅ | Dato correcto **y** cita a la sección esperada |
| ⚠️ | Dato correcto, pero incompleto, con otra sección o con algo de más |
| ❌ | Dato incorrecto, inventado, o "No encontré" cuando sí está |

En Word no hay páginas: la cita es `[PRO-02 Rev. 07, sección ...]`.

---

## A. Contenido del procedimiento

| # | Pregunta | Respuesta esperada | Sección esperada | Qué prueba | Resultado |
|---|---|---|---|---|---|
| 1 | ¿Cada cuánto se revisan los objetivos e indicadores? | Semestralmente | Definición de la Política y objetivos de la empresa | Frecuencia correcta entre dos parecidas | |
| 2 | ¿Con qué frecuencia se hacen las reuniones de revisión por la Dirección? | Al menos una vez al año | Revisión por la Dirección | La otra frecuencia (no "semestral") | |
| 3 | ¿Qué temas se tratan en la revisión por la Dirección? | Acciones de revisiones anteriores; cambios externos e internos; desempeño del SGC (satisfacción, objetivos, procesos, no conformidades, seguimiento, auditorías, proveedores); recursos; eficacia ante riesgos; oportunidades de mejora | Revisión por la Dirección | Listas largas | |
| 4 | ¿Dónde se archiva la Matriz FODA y por cuánto tiempo? | En `\\172.16.134.103\Documentación ISO 9001\SGC AR CONSULTORES 2015\02- Liderazgo`, en forma permanente | Registros | Fila de tabla | |
| 5 | ¿Quién archiva las Minutas de Reunión? | El Responsable de Calidad (las confecciona la Dirección) | Registros | No mezclar columnas | |
| 6 | ¿Cómo se mide la satisfacción de los clientes? | Encuestas telefónicas y/o por e-mail; escala de 1 a 10; el Representante de la Dirección procesa los datos | Satisfacción de clientes | Respuesta completa | |
| 7 | ¿Qué pasa si un cliente pone un puntaje de 5? | Prioridad de mejora; acciones correctivas obligatorias (5 o menos) | Satisfacción de clientes | Rango correcto | |
| 8 | ¿Y con un puntaje de 7? | Aspectos a monitorear (6 o 7) | Satisfacción de clientes | Rango correcto | |
| 12 | ¿Cómo se comunican los cambios que pueden afectar al SGC? | El Directorio, a toda la empresa, por mail, cada vez que ocurren | Comunicaciones | Todos los datos de la fila | |
| 13 | ¿Quién identifica los riesgos de los procesos y dónde se documentan? | El Responsable de Calidad; en la Matriz de Riesgos | Gestión de riesgos | Sección corta | |
| 31 | ¿Cuál es el objetivo del procedimiento de liderazgo? | Describir la metodología que sigue la Dirección para implementar y mantener el Sistema de Gestión de Calidad | Inicio del documento | Tabla inicial sin título | |
| 32 | ¿Quién es el responsable del proceso de liderazgo y qué áreas involucra? | Responsable: Dirección. Área involucrada: Directorio | Inicio del documento | Tabla clave–valor | |
| 33 | ¿Qué registros genera el procedimiento PRO-02? | Matriz FODA, Minuta de Reunión, Objetivos de SGC, Requisitos partes interesadas, Encuestas de Satisfacción de Clientes, Matriz de Riesgos | Registros | Tabla completa | |
| 34 | ¿Dónde se registran las partes interesadas y cuándo se revisan? | En el registro "Requisitos partes interesadas"; se revisan durante la Revisión del Sistema de Gestión | Identificación de partes interesadas | Dato en el texto | |
| 35 | ¿Qué se hace con los resultados de la revisión por la Dirección? | La Dirección identifica y gestiona oportunidades de mejora, cambios en el SGC y necesidades de recursos; se registran en Minutas de Reunión | Revisión por la Dirección | Respuesta completa | |

## B. Encabezado e historial

| # | Pregunta | Respuesta esperada | Sección esperada | Qué prueba | Resultado |
|---|---|---|---|---|---|
| 9 | ¿Quién aprobó el procedimiento PRO-02 y qué revisión es? | Aprobado por la Dirección; Rev. 07 del 12/11/2020 | Ficha del documento | Datos del encabezado | |
| 10 | ¿Qué cambió en la revisión 07 del PRO-02? | La revisión de objetivos e indicadores pasa a ser semestral | Historial de Cambios | Usar el historial cuando se pregunta por cambios | |
| 11 | ¿Quién elaboró la versión 04 y qué se modificó? | Adrián Ferrari; se definió el puntaje de insatisfacción en la medición de satisfacción y se eliminó la definición de reclamos | Historial de Cambios | No mezclar filas del historial | |
| 30 | ¿El PRO-02 Rev. 07 es la versión vigente? | Que el documento cargado es la Rev. 07 del 12/11/2020, **sin afirmar** que sea la vigente | Ficha del documento | No afirmar vigencia | |

## C. Lo que NO debe inventar

| # | Pregunta | Respuesta esperada | Resultado |
|---|---|---|---|
| 27 | ¿Cuántos días de vacaciones corresponden a un empleado con cinco años de antigüedad? | "No encontré eso en los documentos cargados." | |
| 28 | ¿AR Consultores está certificada en ISO 9001? | "No encontré…" o aclarar que el documento no lo indica | |
| 29 | ¿Cuál es el salario de la responsable de calidad? | "No encontré eso en los documentos cargados." | |

---

## Última medición

20/10/2026, automática, después de agregar la línea de vigencia: **20/22**.
- La 30 ya no afirma que la Rev. 07 sea la vigente (responde "No encontré").
- Fallan la 6 y la 35: respuestas correctas pero incompletas.
