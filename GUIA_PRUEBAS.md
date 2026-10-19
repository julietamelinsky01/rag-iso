# Guía de prueba del RAG

Preguntas para comprobar cómo responde el sistema con los **3 documentos cargados hoy**:

- **PRO-02 Liderazgo** (procedimiento real de AR Consultores, Word, Rev. 07).
- **Manual_Prueba_RAG.pdf** (empresa ficticia "Horizonte Servicios", solo para pruebas).
- **NOM_ISO_9001-2015.pdf** (la norma).

Las respuestas esperadas salen del texto de los documentos. El modelo puede redactar distinto: lo que importa es **el dato** y **la cita**.

## Cómo probar

En la terminal de VS Code, dentro de `rag-iso`:

```bash
python ask.py
```

Escribí cada pregunta, compará con la respuesta esperada y anotá el resultado. Para salir: `salir`.

**Cómo calificar**

| Marca | Significa |
|---|---|
| ✅ | Dato correcto **y** cita al documento y la sección/cláusula esperados |
| ⚠️ | Dato correcto, pero la cita es incompleta, de otra sección, o la respuesta agrega algo de más |
| ❌ | Dato incorrecto, inventado, mezcla documentos, o dice "No encontré" cuando sí está |

Tené en cuenta:
- En el Word **no hay páginas**: la cita es `[PRO-02 Rev. 07, sección ...]`. En los PDF sí: `[archivo, cláusula X, pág. N]`.
- Las páginas de la ISO son las del archivo PDF, no el número impreso en la hoja.

---

## A. Procedimiento real PRO-02

| # | Pregunta | Respuesta esperada | Cita esperada | Qué prueba | Resultado |
|---|---|---|---|---|---|
| 1 | ¿Cada cuánto se revisan los objetivos e indicadores? | Semestralmente | PRO-02, sección Definición de la Política y objetivos de la empresa | Frecuencia correcta entre dos parecidas | |
| 2 | ¿Con qué frecuencia se hacen las reuniones de revisión por la Dirección? | Al menos una vez al año | PRO-02, sección Revisión por la Dirección | La otra frecuencia (no debe decir "semestral") | |
| 3 | ¿Qué temas se tratan en la revisión por la Dirección? | Acciones de revisiones anteriores; cambios externos e internos; desempeño del SGC (satisfacción, objetivos, procesos, no conformidades, seguimiento, auditorías, proveedores); recursos; eficacia ante riesgos; oportunidades de mejora | PRO-02, sección Revisión por la Dirección | Listas largas sin cortar | |
| 4 | ¿Dónde se archiva la Matriz FODA y por cuánto tiempo? | En `\\172.16.134.103\Documentación ISO 9001\SGC AR CONSULTORES 2015\02- Liderazgo`, en forma permanente | PRO-02, sección Registros | Leer una fila de tabla | |
| 5 | ¿Quién archiva las Minutas de Reunión? | El Responsable de Calidad (las confecciona la Dirección) | PRO-02, sección Registros | No mezclar columnas de la tabla | |
| 6 | ¿Cómo se mide la satisfacción de los clientes? | Con encuestas telefónicas y/o por e-mail; escala numérica de 1 a 10; el Representante de la Dirección procesa los datos | PRO-02, sección Satisfacción de clientes | Texto que antes se perdía ("la Satisfacción") | |
| 7 | ¿Qué pasa si un cliente pone un puntaje de 5? | Es prioridad de mejora y obliga a tomar acciones correctivas (puntaje 5 o menos) | PRO-02, sección Satisfacción de clientes | Tabla chica unida a su texto | |
| 8 | ¿Y con un puntaje de 7? | Son aspectos a monitorear (puntaje 6 o 7) | PRO-02, sección Satisfacción de clientes | Rango correcto | |
| 9 | ¿Quién aprobó el procedimiento PRO-02 y qué revisión es? | Aprobado por la Dirección; Rev. 07 del 12/11/2020 (realizado por el Responsable de Calidad) | PRO-02, sección Ficha del documento | Datos del encabezado | |
| 10 | ¿Qué cambió en la revisión 07 del PRO-02? | La revisión de objetivos e indicadores pasa a ser semestral | PRO-02, sección Historial de Cambios | Usar el historial solo cuando se pregunta por cambios | |
| 11 | ¿Quién elaboró la versión 04 y qué se modificó? | Adrián Ferrari; se incorporó cómo se define el puntaje de insatisfacción en la medición de satisfacción y se eliminó la definición de reclamos (ya tratada en el PG 04) | PRO-02, sección Historial de Cambios | Historial más detallado | |
| 12 | ¿Cómo se comunican los cambios que pueden afectar al SGC? | Los comunica el Directorio a toda la empresa, por mail, cada vez que ocurren | PRO-02, sección Comunicaciones | Tabla de una fila | |
| 13 | ¿Quién identifica los riesgos de los procesos y dónde se documentan? | El Responsable de Calidad; en la Matriz de Riesgos | PRO-02, sección Gestión de riesgos | Sección corta | |

## B. Manual de prueba (empresa ficticia)

| # | Pregunta | Respuesta esperada | Cita esperada | Qué prueba | Resultado |
|---|---|---|---|---|---|
| 14 | ¿Cada cuánto se realizan las auditorías internas y cuánto se conservan sus informes? | Cada cuatro meses; los informes, cinco años | Manual, cláusula 3.3, pág. 3 | Caso base | |
| 15 | Según el manual, ¿cada cuánto se revisan los procedimientos? | Cada seis meses | Manual, cláusula 1.1, pág. 1 | No confundir con PRO-02 | |
| 16 | ¿Cuánto tiempo se conservan los procedimientos obsoletos y los registros de aprobación? | Obsoletos: dos años. Registros de aprobación: tres años | Manual, cláusula 1.3, pág. 1 | Dos plazos en la misma cláusula | |
| 17 | ¿Cómo se hacen las copias de seguridad? | Todos los días a las 22:00; se conservan 45 días en un repositorio separado; prueba de restauración el primer lunes de cada mes | Manual, cláusula 2.1, pág. 2 | Varios datos juntos | |
| 18 | ¿En cuánto tiempo se revocan los accesos de alguien que se va? | Dentro de las 24 horas del aviso de baja de Recursos Humanos | Manual, cláusula 2.2, pág. 2 | Dato puntual | |
| 19 | ¿Qué plazos hay para responder un reclamo de un cliente? | Confirmar recepción en un día hábil; respuesta inicial en tres días hábiles | Manual, cláusula 3.1, pág. 3 | Plazos parecidos | |

## C. Norma ISO 9001:2015

| # | Pregunta | Respuesta esperada | Cita esperada | Qué prueba | Resultado |
|---|---|---|---|---|---|
| 20 | ¿Qué debe establecer la alta dirección en la política de la calidad? | Que sea apropiada al propósito y contexto; marco para los objetivos; compromiso de cumplir requisitos; compromiso de mejora continua | ISO, cláusula 5.2.1, pág. 15 | Lista a)–d) | |
| 21 | ¿Qué información documentada exige la norma para las auditorías internas? | Conservarla como evidencia de la implementación del programa de auditoría y de los resultados | ISO, cláusula 9.2.2, pág. 30 | Atribuir a la norma, no al manual | |
| 22 | Según la norma, ¿cada cuánto se debe hacer la revisión por la dirección? | A intervalos planificados (la norma no fija una frecuencia) | ISO, cláusula 9.3.1, pág. 31 | **No** debe decir "una vez al año": eso es del PRO-02 | |
| 23 | ¿Qué exige la norma cuando ocurre una no conformidad? | Reaccionar (controlar, corregir, hacer frente a consecuencias); evaluar acciones para eliminar las causas; implementar acciones; revisar su eficacia; actualizar riesgos y cambios al SGC si hace falta | ISO, cláusula 10.2.1, pág. 32 | Lista con sublistas | |
| 24 | ¿Qué pide la norma sobre la competencia del personal? | Determinar la competencia necesaria; asegurar que sean competentes (educación, formación o experiencia); tomar acciones y evaluar su eficacia; conservar evidencia | ISO, cláusula 7.2, pág. 19 | Cláusula de otro capítulo | |

## D. Mezcla de documentos (atribución)

| # | Pregunta | Respuesta esperada | Qué prueba | Resultado |
|---|---|---|---|---|
| 25 | ¿Qué dice el PRO-02 sobre la frecuencia de la revisión por la Dirección y qué exige la norma? | PRO-02: al menos una vez al año. Norma: a intervalos planificados (9.3.1). Cada dato con su cita | Separar "el procedimiento establece" de "la norma exige" | |
| 26 | ¿Qué pasa si no se aplica algún punto de la norma en el alcance? | PRO-02: se justifica en el alcance que determine la Dirección. Norma (4.3): el alcance debe justificar cualquier requisito que no se aplique | Dos documentos que dicen algo parecido | |

## E. Lo que NO debe inventar

| # | Pregunta | Respuesta esperada | Qué prueba | Resultado |
|---|---|---|---|---|
| 27 | ¿Cuántos días de vacaciones corresponden a un empleado con cinco años de antigüedad? | "No encontré eso en los documentos cargados." | No inventar | |
| 28 | ¿AR Consultores está certificada en ISO 9001? | "No encontré…" o aclarar que los documentos no lo indican | No afirmar certificaciones | |
| 29 | ¿Cuál es el salario de la responsable de calidad? | "No encontré…" (el manual aclara que no establece salarios) | No inventar números | |
| 30 | ¿El PRO-02 Rev. 07 es la versión vigente? | Que el documento cargado es la Rev. 07 del 12/11/2020, **sin afirmar** que sea la vigente | No afirmar vigencia | |

---

## Cuando termines

Pasame los números marcados ⚠️ o ❌, con lo que respondió el sistema (podés copiar la salida de la terminal). Con eso vemos si el problema está en la lectura del documento, en la búsqueda o en la redacción del modelo.
