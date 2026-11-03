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
from sync_drive import (  # noqa: E402
    FOLDER_MIME, classify, decide, detect_norma, display_name, eligible,
    not_supported,
    select_documents, snapshot,
)


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


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self, num_retries=0):
        return self.result


class FakeFiles:
    """Árbol: raíz/{a.pdf, sub/{b.pdf, otra/c.pdf}}; sub2 se apunta a sub."""
    TREE = {
        "root": [drive_file(id="A", name="a.pdf"),
                 {"id": "sub", "name": "sub", "mimeType": FOLDER_MIME}],
        "sub": [drive_file(id="B", name="b.pdf", md5Checksum="b"),
                {"id": "otra", "name": "otra", "mimeType": FOLDER_MIME},
                {"id": "root", "name": "ciclo", "mimeType": FOLDER_MIME}],
        "otra": [drive_file(id="C", name="c.pdf", md5Checksum="c")],
    }

    def get(self, fileId, fields, supportsAllDrives):
        return FakeRequest({"id": fileId, "name": "Raíz", "mimeType": FOLDER_MIME})

    def list(self, q, **kwargs):
        return FakeRequest({"files": self.TREE[q.split("'")[1]]})


class FakeDrive:
    def files(self):
        return FakeFiles()


class SubcarpetasTests(unittest.TestCase):
    def test_documentos_externos_por_carpeta(self):
        for path in ("01/Documentacion Externa/Ley.pdf", "03/Externas/2019/Inf.docx",
                     "Documentación externa/Ley.pdf"):
            file = drive_file(name=path.split("/")[-1], path=path)
            self.assertEqual(detect_norma(file), "Documento externo")

    def test_norma_en_carpeta_externa_sigue_siendo_norma(self):
        file = drive_file(name="ISO 9001-2015.PDF", path="01/Documentacion Externa/ISO 9001-2015.PDF")
        self.assertEqual(detect_norma(file), "ISO 9001:2015")

    def test_interno_no_se_confunde_con_externo(self):
        file = drive_file(name="Plan.docx", path="03- Auditorias/Internas/Plan.docx")
        self.assertIsNone(detect_norma(file))
        file = drive_file(name="Plan externo.docx", path="Plan externo.docx")
        self.assertIsNone(detect_norma(file))

    def test_descripcion_corrige_el_externo(self):
        file = drive_file(name="Ley.pdf", path="Externas/Ley.pdf", description="norma: interno")
        self.assertIsNone(detect_norma(file))

    def test_nombre_con_anio_de_la_carpeta(self):
        file = drive_file(name="foda.docx", path="02- Liderazgo/2024/foda.docx")
        self.assertEqual(display_name(file), "foda.docx (2024)")

    def test_nombre_sin_carpeta_de_anio(self):
        for path in ("foda.docx", "03- Auditorias/foda.docx", "Rev 2024/foda.docx"):
            file = drive_file(name="foda.docx", path=path)
            self.assertEqual(display_name(file), "foda.docx")

    def test_versiones_de_distintos_anios_se_citan_distinto(self):
        one = drive_file(id="1", name="f.docx", path="2023/f.docx", md5Checksum="x")
        two = drive_file(id="2", name="f.docx", path="2024/f.docx", md5Checksum="y")
        _, apply, _ = decide({"1": one, "2": two}, {"1": one, "2": two}, {})
        self.assertEqual([i["name"] for i in apply], ["f.docx (2023)", "f.docx (2024)"])

    def test_mover_de_carpeta_de_anio_actualiza_solo_metadatos(self):
        file = drive_file(name="f.docx", path="2024/f.docx")
        self.assertEqual(classify(file, state(file_name="f.docx")), "metadatos")

    def test_recorre_subcarpetas_con_ruta(self):
        name, files = snapshot(FakeDrive(), "root")
        self.assertEqual(name, "Raíz")
        self.assertEqual(
            [f["path"] for f in files],
            ["a.pdf", "sub/b.pdf", "sub/otra/c.pdf"],
        )

    def test_temporales_de_word_no_se_procesan_ni_se_informan(self):
        temp = drive_file(name="~$triz Foda.docx", path="x/~$triz Foda.docx")
        self.assertFalse(eligible(temp))
        self.assertEqual(not_supported([temp]), [])

    def test_otros_formatos_se_informan(self):
        excel = drive_file(name="Minuta.xls", path="x/Minuta.xls")
        self.assertEqual(not_supported([excel]), [excel])

    def test_copia_identica_conserva_la_ya_sincronizada(self):
        root = drive_file(id="R", path="manual.pdf")
        nested = drive_file(id="N", path="sub/manual.pdf")
        selected, copies = select_documents([nested, root], {"N": state()})
        self.assertEqual(list(selected), ["N"])
        self.assertEqual(copies[0][0]["id"], "R")

    def test_copia_identica_sin_estado_conserva_la_mas_cercana(self):
        root = drive_file(id="R", path="manual.pdf")
        nested = drive_file(id="N", path="sub/manual.pdf")
        selected, copies = select_documents([nested, root], {})
        self.assertEqual(list(selected), ["R"])
        self.assertEqual(copies[0][0]["id"], "N")

    def test_mismo_nombre_con_contenido_distinto_se_conservan(self):
        one = drive_file(id="1", path="2023/foda.docx", md5Checksum="x")
        two = drive_file(id="2", path="2024/foda.docx", md5Checksum="y")
        selected, copies = select_documents([one, two], {})
        self.assertEqual(sorted(selected), ["1", "2"])
        self.assertEqual(copies, [])


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
