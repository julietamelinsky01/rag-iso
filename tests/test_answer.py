"""Pruebas del procesamiento de citas de rag/answer.py.

No usan red, Ollama ni Supabase.
Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.answer import NOT_FOUND, WARNING, _format_context, build_answer  # noqa: E402

CHUNKS = [
    {"document_id": 3, "source": "Manual_Prueba_RAG.pdf", "clausula": "3.3",
     "titulo": "Auditorías internas", "pagina": 3, "score": 0.03},
    {"document_id": 3, "source": "Manual_Prueba_RAG.pdf", "clausula": "1.3",
     "titulo": "Conservación", "pagina": 1, "score": 0.02},
    {"document_id": 7, "source": "Procedimiento.docx", "clausula": None,
     "titulo": None, "pagina": 1, "score": 0.01},
    {"document_id": 11, "source": "NOM_ISO_9001-2015.pdf", "norma": "ISO 9001:2015",
     "clausula": "9.2.2", "titulo": "La organización debe:", "pagina": 30, "score": 0.02},
    {"document_id": 20, "source": "PRO 02 - Liderazgo Rev 07.docx", "codigo": "PRO-02",
     "titulo_doc": "Liderazgo", "revision": "07", "fecha_revision": "12/11/2020",
     "clausula": None, "titulo": "Descripción del Proceso > Revisión por la Dirección",
     "pagina": None, "tipo": "contenido", "score": 0.02},
    {"document_id": 20, "source": "PRO 02 - Liderazgo Rev 07.docx", "codigo": "PRO-02",
     "titulo_doc": "Liderazgo", "revision": "07", "fecha_revision": "12/11/2020",
     "clausula": None, "titulo": "Historial de Cambios", "pagina": None,
     "tipo": "historial", "score": 0.01},
    {"document_id": 20, "source": "PRO 02 - Liderazgo Rev 07.docx", "codigo": "PRO-02",
     "titulo_doc": "Liderazgo", "revision": "07", "fecha_revision": "12/11/2020",
     "clausula": None, "titulo": "Registros", "pagina": None,
     "tipo": "tabla", "score": 0.01},
]
for _chunk in CHUNKS:
    _chunk.setdefault("content", "texto")

REF_1 = "[Manual_Prueba_RAG.pdf, cláusula 3.3, pág. 3]"
REF_2 = "[Manual_Prueba_RAG.pdf, cláusula 1.3, pág. 1]"


class OriginTests(unittest.TestCase):
    def test_contexto_indica_norma_o_documento_interno(self):
        for chunk in CHUNKS:
            chunk.setdefault("content", "texto")
        context = _format_context(CHUNKS)
        self.assertIn("[F1] (Documento interno | Manual_Prueba_RAG.pdf", context)
        self.assertIn("[F4] (Norma ISO 9001:2015 | NOM_ISO_9001-2015.pdf", context)

    def test_contexto_de_procedimiento_con_encabezado(self):
        context = _format_context(CHUNKS)
        self.assertIn(
            "[F5] (Documento interno | PRO-02 Liderazgo Rev. 07 del 12/11/2020 | "
            "Descripción del Proceso > Revisión por la Dirección)",
            context,
        )
        self.assertIn("Historial de Cambios | HISTORIAL DE CAMBIOS (antecedente, no vigente))", context)
        self.assertIn("Registros | TABLA)", context)

    def test_referencia_de_procedimiento_sin_pagina(self):
        result = build_answer("Una vez al año [F5]. Cambió [F6].", CHUNKS)
        self.assertEqual(
            result["answer"],
            "Una vez al año [PRO-02 Rev. 07, sección Revisión por la Dirección]. "
            "Cambió [PRO-02 Rev. 07, sección Historial de Cambios].",
        )
        self.assertEqual([s["tipo"] for s in result["sources"]], ["contenido", "historial"])
        self.assertEqual(
            [s["referencia"] for s in result["sources"]],
            ["PRO-02 Rev. 07, sección Revisión por la Dirección",
             "PRO-02 Rev. 07, sección Historial de Cambios"],
        )

    def test_sources_incluye_norma(self):
        result = build_answer("Interno [F1]. Norma [F4].", CHUNKS)
        self.assertEqual([s["norma"] for s in result["sources"]], [None, "ISO 9001:2015"])


class CitationTests(unittest.TestCase):
    def test_marca_valida_se_reemplaza_por_metadatos(self):
        result = build_answer("Se realizan cada cuatro meses [F1].", CHUNKS)
        self.assertEqual(result["answer"], f"Se realizan cada cuatro meses {REF_1}.")
        self.assertTrue(result["verificada"])
        self.assertEqual([s["clausula"] for s in result["sources"]], ["3.3"])
        self.assertEqual(f"[{result['sources'][0]['referencia']}]", REF_1)

    def test_sources_solo_incluye_citados_en_orden(self):
        result = build_answer("Uno [F2]. Dos [F1]. Otra vez [F2].", CHUNKS)
        self.assertEqual([s["clausula"] for s in result["sources"]], ["1.3", "3.3"])
        self.assertEqual(result["sources"][0]["document_id"], 3)

    def test_varias_marcas_en_un_bloque(self):
        result = build_answer("Dato [F1, F2].", CHUNKS)
        self.assertEqual(
            result["answer"],
            "Dato [Manual_Prueba_RAG.pdf, cláusula 3.3, pág. 3; "
            "Manual_Prueba_RAG.pdf, cláusula 1.3, pág. 1].",
        )

    def test_mismo_documento_repetido_en_bloque(self):
        result = build_answer("Dato [F1][F1].", CHUNKS)
        self.assertEqual(result["answer"], f"Dato {REF_1}{REF_1}.")
        self.assertEqual(len(result["sources"]), 1)

    def test_marca_inexistente_se_descarta(self):
        result = build_answer("Dato [F1]. Inventado [F9].", CHUNKS)
        self.assertEqual(result["answer"], f"Dato {REF_1}. Inventado.")
        self.assertEqual(len(result["sources"]), 1)

    def test_cita_escrita_a_mano_se_descarta(self):
        result = build_answer(
            "Cada cuatro meses [documento, cláusula 3.4, pág. 3] [F1].", CHUNKS
        )
        self.assertEqual(result["answer"], f"Cada cuatro meses {REF_1}.")

    def test_marca_mezclada_con_texto(self):
        result = build_answer("Dato [F1, cláusula 3.3].", CHUNKS)
        self.assertEqual(result["answer"], f"Dato {REF_1}.")

    def test_variantes_de_formato(self):
        result = build_answer("A [ f2 ]. B [F 1].", CHUNKS)
        self.assertEqual(result["answer"], f"A {REF_2}. B {REF_1}.")

    def test_documento_sin_clausula(self):
        result = build_answer("Dato [F3].", CHUNKS)
        self.assertEqual(result["answer"], "Dato [Procedimiento.docx, pág. 1].")

    def test_corchetes_que_no_son_citas_se_conservan(self):
        result = build_answer("Use el formulario [opcional] [F1].", CHUNKS)
        self.assertEqual(result["answer"], f"Use el formulario [opcional] {REF_1}.")

    def test_sin_citas_validas_agrega_advertencia(self):
        result = build_answer("Se realizan cada cuatro meses.", CHUNKS)
        self.assertFalse(result["verificada"])
        self.assertEqual(result["sources"], [])
        self.assertTrue(result["answer"].endswith(WARNING))
        self.assertTrue(result["answer"].startswith("Se realizan cada cuatro meses."))

    def test_solo_citas_invalidas_agrega_advertencia(self):
        result = build_answer("Dato [F17] [documento, pág. 2].", CHUNKS)
        self.assertFalse(result["verificada"])
        self.assertEqual(result["answer"], f"Dato.\n\n{WARNING}")

    def test_no_encontrado_no_es_advertencia(self):
        for text in (NOT_FOUND, NOT_FOUND.rstrip("."), f"  {NOT_FOUND}\n"):
            result = build_answer(text, CHUNKS)
            self.assertEqual(result["answer"], NOT_FOUND)
            self.assertTrue(result["verificada"])
            self.assertEqual(result["sources"], [])


if __name__ == "__main__":
    unittest.main()
