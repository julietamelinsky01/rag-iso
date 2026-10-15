"""Pruebas del criterio de comparación de sync_drive.py.

No usan red, claves ni Supabase.
Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync_drive import classify, decide, eligible  # noqa: E402


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
