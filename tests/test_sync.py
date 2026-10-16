"""Pruebas del criterio de comparación de sync_drive.py.

No usan red, claves ni Supabase.
Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest import PIPELINE_VERSION  # noqa: E402
from sync_drive import classify, decide, detect_norma, eligible  # noqa: E402


def drive_file(**changes):
    file = {
        "id": "A",
        "name": "manual.pdf",
        "mimeType": "application/pdf",
        "modifiedTime": "T1",
        "version": "1",
        "md5Checksum": "abc",
    }
    file.update(changes)
    return file


def state(**changes):
    row = {
        "file_name": "manual.pdf",
        "modified_time": "T1",
        "drive_version": "1",
        "content_md5": "abc",
        "active": True,
        "norma": None,
        "pipeline_version": PIPELINE_VERSION,
    }
    row.update(changes)
    return row


class ClassifyTests(unittest.TestCase):
    def test_nuevo(self):
        self.assertEqual(classify(drive_file(), None), "contenido")

    def test_estado_anterior_sin_huella(self):
        self.assertEqual(
            classify(drive_file(), state(content_md5=None)), "contenido"
        )

    def test_sin_cambios(self):
        self.assertEqual(classify(drive_file(), state()), "sin cambios")

    def test_renombrado(self):
        self.assertEqual(
            classify(drive_file(name="nuevo.pdf"), state()), "metadatos"
        )

    def test_mismos_bytes_nueva_version(self):
        self.assertEqual(
            classify(drive_file(version="2"), state()), "metadatos"
        )

    def test_contenido_y_nombre(self):
        self.assertEqual(
            classify(drive_file(name="n.pdf", md5Checksum="xyz"), state()),
            "contenido",
        )

    def test_reaparece_igual(self):
        self.assertEqual(
            classify(drive_file(), state(active=False)), "reactivar"
        )

    def test_reaparece_modificado(self):
        self.assertEqual(
            classify(drive_file(md5Checksum="xyz"), state(active=False)),
            "contenido",
        )

    def test_sin_huella_en_drive(self):
        self.assertEqual(
            classify(drive_file(md5Checksum=None), state()), "sin huella"
        )


    def test_lector_anterior_se_reprocesa(self):
        self.assertEqual(
            classify(drive_file(), state(pipeline_version=None)), "reprocesar"
        )
        self.assertEqual(
            classify(drive_file(), state(pipeline_version=PIPELINE_VERSION - 1)),
            "reprocesar",
        )

    def test_contenido_nuevo_tiene_prioridad_sobre_reprocesar(self):
        self.assertEqual(
            classify(drive_file(md5Checksum="xyz"), state(pipeline_version=None)),
            "contenido",
        )

    def test_cambia_la_norma_detectada(self):
        self.assertEqual(
            classify(drive_file(description="norma: ISO 9001:2015"), state()),
            "metadatos",
        )

    def test_norma_igual_sin_cambios(self):
        self.assertEqual(
            classify(drive_file(name="ISO_9001_2015.pdf"),
                     state(file_name="ISO_9001_2015.pdf", norma="ISO 9001:2015")),
            "sin cambios",
        )


class NormaTests(unittest.TestCase):
    def detect(self, name, description=None):
        return detect_norma({"name": name, "description": description})

    def test_por_nombre(self):
        self.assertEqual(self.detect("NOM_ISO_9001-2015.pdf"), "ISO 9001:2015")
        self.assertEqual(self.detect("ISO 9001.pdf"), "ISO 9001")
        self.assertEqual(self.detect("ISO-IEC_27001_2022.pdf"), "ISO/IEC 27001:2022")
        self.assertEqual(self.detect("UNE-EN ISO 14001 2015.pdf"), "ISO 14001:2015")

    def test_documentos_internos_que_mencionan_una_norma(self):
        self.assertIsNone(self.detect("Manual_Prueba_RAG.pdf"))
        self.assertIsNone(self.detect("Procedimiento auditorías ISO 9001.docx"))
        self.assertIsNone(self.detect("Guia_ISO_9001.pdf"))

    def test_descripcion_tiene_prioridad(self):
        self.assertEqual(
            self.detect("Manual.pdf", "Versión 2\nnorma: ISO 45001:2018"),
            "ISO 45001:2018",
        )
        self.assertIsNone(self.detect("NOM_ISO_9001-2015.pdf", "norma: interno"))


class EligibleTests(unittest.TestCase):
    def test_formatos(self):
        self.assertTrue(eligible(drive_file()))
        self.assertTrue(eligible(drive_file(name="a.DOCX", mimeType="x")))
        self.assertFalse(eligible(drive_file(name="foto.png")))
        self.assertFalse(
            eligible(
                drive_file(mimeType="application/vnd.google-apps.shortcut")
            )
        )
        self.assertFalse(
            eligible(
                drive_file(
                    name="nota.md",
                    mimeType="application/vnd.google-apps.document",
                )
            )
        )


class DecideTests(unittest.TestCase):
    def test_todo_listo(self):
        first = {"A": drive_file()}
        present, apply, deferred = decide(first, dict(first), {})
        self.assertEqual(present, ["A"])
        self.assertEqual([item["id"] for item in apply], ["A"])
        self.assertIsNone(apply[0]["norma"])
        self.assertEqual(apply[0]["pipeline"], PIPELINE_VERSION)
        self.assertEqual(deferred, {})

    def test_fallido_sigue_presente_pero_no_se_aplica(self):
        first = {"A": drive_file(), "B": drive_file(id="B", name="b.pdf")}
        present, apply, _ = decide(first, dict(first), {"B": "sin texto"})
        self.assertEqual(present, ["A", "B"])
        self.assertEqual([item["id"] for item in apply], ["A"])

    def test_cambio_entre_lecturas_se_posterga(self):
        first = {"A": drive_file()}
        final = {"A": drive_file(md5Checksum="xyz")}
        present, apply, deferred = decide(first, final, {})
        self.assertEqual(present, ["A"])
        self.assertEqual(apply, [])
        self.assertIn("A", deferred)

    def test_aparece_entre_lecturas_se_posterga(self):
        first = {"A": drive_file()}
        final = {"A": drive_file(), "B": drive_file(id="B")}
        present, apply, deferred = decide(first, final, {})
        self.assertEqual(present, ["A", "B"])
        self.assertEqual([item["id"] for item in apply], ["A"])
        self.assertIn("B", deferred)

    def test_desaparece_entre_lecturas_queda_fuera(self):
        first = {"A": drive_file(), "B": drive_file(id="B")}
        final = {"A": drive_file()}
        present, apply, _ = decide(first, final, {})
        self.assertEqual(present, ["A"])
        self.assertEqual([item["id"] for item in apply], ["A"])

    def test_nombres_repetidos_con_ids_distintos(self):
        first = {"A": drive_file(), "B": drive_file(id="B")}
        present, apply, _ = decide(first, dict(first), {})
        self.assertEqual(present, ["A", "B"])
        self.assertEqual(len(apply), 2)


if __name__ == "__main__":
    unittest.main()
