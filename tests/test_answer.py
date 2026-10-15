"""Pruebas del procesamiento de citas de rag/answer.py.

No usan red, Ollama ni Supabase.
Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.answer import NOT_FOUND, WARNING, build_answer  # noqa: E402

CHUNKS = [
    {"document_id": 3, "source": "Manual_Prueba_RAG.pdf", "clausula": "3.3",
     "titulo": "Auditorías internas", "pagina": 3, "score": 0.03},
    {"document_id": 3, "source": "Manual_Prueba_RAG.pdf", "clausula": "1.3",
     "titulo": "Conservación", "pagina": 1, "score": 0.02},
    {"document_id": 7, "source": "Procedimiento.docx", "clausula": None,
     "titulo": None, "pagina": 1, "score": 0.01},
]
REF_1 = "[Manual_Prueba_RAG.pdf, cláusula 3.3, pág. 3]"
REF_2 = "[Manual_Prueba_RAG.pdf, cláusula 1.3, pág. 1]"


class CitationTests(unittest.TestCase):
    def test_marca_valida_se_reemplaza_por_metadatos(self):
        result = build_answer("Se realizan cada cuatro meses [F1].", CHUNKS)
        self.assertEqual(result["answer"], f"Se realizan cada cuatro meses {REF_1}.")
        self.assertTrue(result["verificada"])
        self.assertEqual([s["clausula"] for s in result["sources"]], ["3.3"])

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
        result = build_answer("Dato [F7] [documento, pág. 2].", CHUNKS)
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
