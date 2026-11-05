"""Evaluación automática del RAG con las preguntas de GUIA_PRUEBAS.md.

Uso:
    python evaluar.py                 (todas las preguntas)
    python evaluar.py --solo 6,11,22  (algunas)
    python evaluar.py --veces 2       (cada pregunta dos veces)
    python evaluar.py --detalle       (muestra cada respuesta completa)

Solo lee: busca en Supabase y genera con Ollama, no modifica nada.

Cada pregunta se aprueba si la respuesta:
- contiene los datos esperados (se aceptan variantes de redacción),
- no contiene lo prohibido (por ejemplo, la frecuencia equivocada),
- cita el documento y la sección o cláusula esperados.
Es una comprobación por palabras clave: sirve para detectar cambios,
pero una revisión humana sigue siendo la referencia final.
"""
import argparse
import re
import time
import unicodedata

from rag.answer import NOT_FOUND, answer

# debe:    cada elemento es un texto o una lista de alternativas.
# no_debe: expresiones regulares que no pueden aparecer.
# citas:   textos que deben figurar en alguna referencia citada.
CASOS = [
    # A. PRO-02
    {"n": 1, "q": "¿Cada cuánto se revisan los objetivos e indicadores?",
     "debe": ["semestral"], "no_debe": [r"una vez al a[nñ]o"],
     "citas": ["Definición de la Política"]},
    {"n": 2, "q": "¿Con qué frecuencia se hacen las reuniones de revisión por la Dirección?",
     "debe": [["una vez al año", "anual"]], "no_debe": [r"semestral"],
     "citas": ["sección Revisión por la Dirección"]},
    {"n": 3, "q": "Según el PRO-02, ¿qué temas se tratan en la revisión por la Dirección?",
     "debe": ["suficiencia de recursos", "oportunidades de mejora", "proveedores externos"],
     "citas": ["sección Revisión por la Dirección"]},
    {"n": 4, "q": "¿Dónde se archiva la Matriz FODA y por cuánto tiempo?",
     "debe": ["172.16.134.103", "permanente"], "citas": ["sección Registros"]},
    {"n": 5, "q": "¿Quién archiva las Minutas de Reunión?",
     "debe": ["responsable de calidad"], "citas": ["sección Registros"]},
    {"n": 6, "q": "¿Cómo se mide la satisfacción de los clientes?",
     "debe": ["encuesta", ["1 a 10", "1 al 10", "del 1 al 10"]],
     "no_debe": [r"una vez al a[nñ]o"], "citas": ["sección Satisfacción de clientes"]},
    {"n": 7, "q": "En la encuesta de satisfacción del PRO-02, ¿qué pasa si un cliente pone un puntaje de 5?",
     "debe": ["correctiva"], "citas": ["sección Satisfacción de clientes"]},
    {"n": 8, "q": "En la encuesta de satisfacción del PRO-02, ¿qué significa un puntaje de 7?",
     "debe": ["monitorear"], "citas": ["sección Satisfacción de clientes"]},
    {"n": 9, "q": "¿Quién aprobó el procedimiento PRO-02 y qué revisión es?",
     "debe": ["direccion", "07", "12/11/2020"], "citas": ["Ficha del documento"]},
    {"n": 10, "q": "¿Qué cambió en la revisión 07 del PRO-02?",
     "debe": ["semestral"], "citas": ["Historial de Cambios"]},
    {"n": 11, "q": "¿Quién elaboró la versión 04 del PRO-02 y qué se modificó?",
     "debe": ["Adrián Ferrari", "satisfacción"], "no_debe": [r"5\.3", r"OBS 2"],
     "citas": ["Historial de Cambios"]},
    {"n": 12, "q": "¿Cómo se comunican los cambios que pueden afectar al SGC?",
     "debe": ["directorio", "mail", "toda la empresa"], "citas": ["sección Comunicaciones"]},
    {"n": 13, "q": "¿Quién identifica los riesgos de los procesos y dónde se documentan?",
     "debe": ["responsable de calidad", "matriz de riesgos"],
     "citas": ["sección Gestión de riesgos"]},
    # E. Lo que no debe inventar
    {"n": 27, "q": "¿Cuántos días de vacaciones corresponden a un empleado con cinco años de antigüedad?",
     "no_encontrado": True},
    # Vale informar lo que dicen los informes; no afirmar que sigue vigente.
    {"n": 28, "q": "¿AR Consultores está certificada en ISO 9001?",
     "debe": [["informe", "auditor", "no encontr", "no indica"]],
     "no_debe": [r"(?<!no )(?<!no est[aá] )\bvigente"]},
    {"n": 29, "q": "¿Cuál es el salario de la responsable de calidad?",
     "no_encontrado": True,
     },
    {"n": 30, "q": "¿El PRO-02 Rev. 07 es la versión vigente?",
     # Vale identificar la revisión o decir que no lo encontró;
     # lo que no puede es afirmar que está vigente.
     "debe": [["07", "no encontr"]],
     "no_debe": [r"(?<!no )\bes la (versi[oó]n|revisi[oó]n) vigente",
                 r"^s[ií][,.]"]},
    # F. Más preguntas sobre PRO-02
    {"n": 31, "q": "¿Cuál es el objetivo del procedimiento de liderazgo?",
     "debe": ["metodología", "Sistema de Gestión de Calidad"], "citas": ["PRO-02"]},
    {"n": 32, "q": "¿Quién es el responsable del proceso de liderazgo y qué áreas involucra?",
     "debe": ["Dirección", "Directorio"], "citas": ["PRO-02"]},
    {"n": 33, "q": "¿Qué registros genera el procedimiento PRO-02?",
     "debe": ["Matriz FODA", "Minuta", "Matriz de Riesgos", "partes interesadas"],
     "citas": ["sección Registros"]},
    {"n": 34, "q": "¿Dónde se registran las partes interesadas y cuándo se revisan?",
     "debe": ["Requisitos partes interesadas", "Revisión"],
     "citas": ["sección Identificación de partes interesadas"]},
    {"n": 35, "q": "Según el PRO-02, ¿qué se hace con los resultados de la revisión por la Dirección?",
     "debe": ["oportunidades de mejora", ["minuta", "minutas"]],
     "citas": ["sección Revisión por la Dirección"]},
    # G. Otros documentos reales
    {"n": 36, "q": "Según el PRO-03, ¿cada cuánto deben revisarse los elementos del Sistema?",
     "debe": ["una vez al año"], "citas": ["PRO-03"]},
    {"n": 37, "q": "¿Qué diferencia hay entre una No Conformidad y una Observación?",
     "debe": ["parcial"], "citas": ["PRO-03"]},
    {"n": 38, "q": "¿Quién puede modificar los documentos del SGC?",
     "debe": ["responsable de calidad"], "citas": ["PRO-01"]},
    {"n": 39, "q": "¿Cuánto tiempo guardo las minutas?",
     "debe": ["permanente"], "citas": ["sección Registros"]},
    # H. Versiones por año
    {"n": 40, "q": "¿Qué oportunidades tiene la FODA 2024?",
     "debe": ["ampliación del mercado"], "no_debe": [r"destinar tiempo"], "citas": ["(2024)"]},
    {"n": 41, "q": "¿Cuáles eran las amenazas en la Matriz FODA 2022?",
     "debe": ["DNU"], "citas": ["(2022)"]},
    {"n": 42, "q": "¿Cuántas no conformidades hubo en la auditoría de recertificación 2023?",
     "debe": [["0", "ninguna", "no hubo"]], "citas": ["(2023)"]},
    # I. Leyes
    {"n": 43, "q": "Según la Ley 11.723, ¿cuándo termina un contrato de edición?",
     "debe": ["agot"], "citas": ["Art. 44"]},
    {"n": 44, "q": "¿Cuál es el objeto de la ley de protección de datos personales?",
     "debe": ["protección integral"], "citas": ["Art. 1"]},
    {"n": 45, "q": "¿Cuál es el objeto de la Ley 25.326?",
     "debe": ["protección integral"], "no_debe": [r"registro de infractores"], "citas": ["Art. 1"]},
    # J. Cruce de documentos
    {"n": 46, "q": "¿Cada cuánto se hacen las auditorías según el PRO-03 y qué exige la norma?",
     "debe": ["una vez al año", "intervalos planificados"], "citas": ["PRO-03", "cláusula 9.2"]},
    {"n": 47, "q": "Según la norma, ¿cada cuánto se debe hacer la revisión por la dirección?",
     "debe": ["intervalos planificados"], "no_debe": [r"una vez al a[nñ]o", r"no encontr"],
     "citas": ["cláusula 9.3.1"]},
    {"n": 48, "q": "¿Qué dice el PRO-02 sobre la frecuencia de la revisión por la Dirección y qué exige la norma?",
     "debe": [["una vez al año", "anual"], "intervalos planificados"],
     "citas": ["sección Revisión por la Dirección", "cláusula 9.3"]},
    # K. Lo que todavía no está cargado o no existe
    {"n": 49, "q": "¿Qué resultado tuvo la auditoría externa de 2025?", "no_encontrado": True},
    {"n": 50, "q": "¿Cuántos riesgos tiene la Matriz de Riesgos?", "no_encontrado": True},
]

# En ninguna respuesta pueden quedar marcas internas sin reemplazar.
SIEMPRE_PROHIBIDO = [
    r"\[\s*F\s*\d+",
    r"\b(documento|fragmento)\s+F\d+\b",
    # Texto del ejemplo del prompt copiado en la respuesta.
    r"dato tomado",
    r"(primera|segunda) afirmaci[oó]n",
    r"\bfragmento (uno|dos|tres|cuatro|cinco|seis|siete|ocho|\d+)\b",
]


def plain(text: str) -> str:
    """Minúsculas y sin acentos, para comparar con tolerancia."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def evaluate(caso: dict, result: dict) -> list[str]:
    """Devuelve la lista de problemas; vacía si la respuesta aprueba."""
    problems = []
    text = result["answer"]
    flat = plain(text)
    refs = [plain(s.get("referencia", "")) for s in result.get("sources", [])]

    if caso.get("no_encontrado"):
        if NOT_FOUND not in text:
            problems.append("debía decir que no lo encontró")
        return problems

    for item in caso.get("debe", []):
        options = item if isinstance(item, list) else [item]
        if not any(plain(option) in flat for option in options):
            problems.append(f"falta «{' / '.join(options)}»")

    for pattern in caso.get("no_debe", []) + SIEMPRE_PROHIBIDO:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            problems.append(f"contiene algo prohibido ({pattern})")

    for cita in caso.get("citas", []):
        if not any(plain(cita) in ref for ref in refs):
            problems.append(f"no cita «{cita}»")

    if caso.get("citas") and not result.get("verificada", True):
        problems.append("respuesta marcada como no verificada")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluar el RAG con la guía de prueba")
    parser.add_argument("--solo", help="números separados por coma, por ejemplo 6,11,22")
    parser.add_argument("--veces", type=int, default=1, help="repeticiones por pregunta")
    parser.add_argument("--detalle", action="store_true", help="mostrar cada respuesta")
    args = parser.parse_args()

    casos = CASOS
    if args.solo:
        wanted = {int(n) for n in args.solo.split(",")}
        casos = [c for c in CASOS if c["n"] in wanted]

    passed = total = 0
    failed_numbers = []
    started = time.time()

    for caso in casos:
        for attempt in range(args.veces):
            total += 1
            t0 = time.time()
            try:
                result = answer(caso["q"])
                problems = evaluate(caso, result)
            except Exception as error:  # se informa y se sigue con las demás
                result = {"answer": f"(error: {error})", "sources": []}
                problems = [f"error: {error}"]
            seconds = time.time() - t0
            ok = not problems
            passed += ok
            if not ok:
                failed_numbers.append(caso["n"])
            mark = "✅" if ok else "❌"
            suffix = f" (vez {attempt + 1})" if args.veces > 1 else ""
            print(f"{mark} {caso['n']:>2}{suffix}. {caso['q']}  [{seconds:.1f}s]")
            for problem in problems:
                print(f"       - {problem}")
            if args.detalle or not ok:
                for line in result["answer"].splitlines():
                    print(f"       │ {line}")

    print(
        f"\nResultado: {passed}/{total} aprobadas "
        f"en {time.time() - started:.0f} s"
    )
    if failed_numbers:
        print("Fallaron:", ", ".join(str(n) for n in sorted(set(failed_numbers))))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
