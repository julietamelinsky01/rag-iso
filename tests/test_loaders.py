"""Pruebas de lectura y fragmentación (rag/loaders.py y rag/chunker.py).

Crean un Word de ejemplo con la estructura de un procedimiento real
(encabezado, títulos en negrita, tabla e historial). No usan red.
Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document  # noqa: E402

from rag.chunker import Block, chunk_blocks  # noqa: E402
from ingest import read_file  # noqa: E402
from rag.loaders import (  # noqa: E402
    _check_pdf_text, _decode_pdf_text, load_document,
)


def bold(document, text):
    document.add_paragraph().add_run(text).bold = True


def build_procedure(path: Path) -> None:
    document = Document()
    header = document.sections[0].header
    table = header.add_table(rows=2, cols=3, width=document.sections[0].page_width)
    table.cell(0, 0).text = "Liderazgo"
    table.cell(0, 1).text = "Código PRO - 02"
    table.cell(0, 2).text = "Emisión 24/07/2008"
    table.cell(1, 0).text = "Rev. 07 Fecha 12/11/2020"
    table.cell(1, 1).text = "Realizado por: Responsable de Calidad"
    table.cell(1, 2).text = "Aprobado por: Dirección"

    bold(document, "Descripción del Proceso")
    bold(document, "Revisión por la Dirección")
    document.add_paragraph(
        "Las reuniones de revisión se realizan al menos una vez al año."
    )
    bold(document, "Objetivos")
    document.add_paragraph("La revisión de objetivos se realiza semestralmente.")

    bold(document, "Registros")
    records = document.add_table(rows=3, cols=3)
    for j, title in enumerate(("Identificación", "Soporte", "Tiempo")):
        records.cell(0, j).paragraphs[0].add_run(title).bold = True
    for i, row in enumerate(
        (("Matriz FODA", "Electrónico", "Permanente"),
         ("Minuta de Reunión", "Papel", "5 años")),
        start=1,
    ):
        for j, value in enumerate(row):
            records.cell(i, j).text = value

    bold(document, "Historial de Cambios")
    history = document.add_table(rows=2, cols=2)
    history.cell(0, 0).paragraphs[0].add_run("Versión").bold = True
    history.cell(0, 1).paragraphs[0].add_run("Descripción").bold = True
    history.cell(1, 0).text = "07"
    history.cell(1, 1).text = "La revisión de objetivos pasa a ser semestral."
    document.save(path)


class DocxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = path = Path(cls.tmp.name) / "PRO-02.docx"
        build_procedure(path)
        cls.meta, blocks = load_document(str(path))
        cls.chunks = chunk_blocks(blocks)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def find(self, text):
        return next(c for c in self.chunks if text in c.content)

    def test_encabezado(self):
        self.assertEqual(self.meta.codigo, "PRO-02")
        self.assertEqual(self.meta.revision, "07")
        self.assertEqual(self.meta.fecha_revision, "12/11/2020")
        self.assertEqual(self.meta.emision, "24/07/2008")
        self.assertEqual(self.meta.realizado, "Responsable de Calidad")
        self.assertEqual(self.meta.aprobado, "Dirección")
        self.assertEqual(self.meta.label(), "PRO-02 Liderazgo (Rev. 07, 12/11/2020)")

    def test_frecuencias_en_secciones_distintas(self):
        annual = self.find("al menos una vez al año")
        semester = self.find("semestralmente")
        self.assertIsNot(annual, semester)
        self.assertTrue(annual.titulo.endswith("Revisión por la Dirección"))
        self.assertTrue(semester.titulo.endswith("Objetivos"))

    def test_tabla_fila_por_fila_con_columnas(self):
        chunk = self.find("Matriz FODA")
        self.assertIn(
            "Identificación: Matriz FODA\n - Soporte: Electrónico\n - Tiempo: Permanente",
            chunk.content,
        )
        self.assertEqual(chunk.titulo, "Registros")

    def test_historial_marcado(self):
        chunk = self.find("pasa a ser semestral")
        self.assertEqual(chunk.tipo, "historial")

    def test_ficha_del_encabezado_se_puede_buscar(self):
        _, chunks = read_file(self.path)
        self.assertEqual(chunks[0].titulo, "Ficha del documento")
        self.assertIn("Aprobado por: Dirección", chunks[0].content)
        self.assertIn("Revisión: 07 del 12/11/2020", chunks[0].content)

    def test_word_sin_paginas(self):
        self.assertTrue(all(c.pagina is None for c in self.chunks))


class TablasConVariosTitulosTests(unittest.TestCase):
    def read(self, rows):
        document = Document()
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.cell(i, j).text = value
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tabla.docx"
            document.save(path)
            _, blocks = load_document(str(path))
        return blocks[0].text

    def test_titulos_a_mitad_de_tabla_rigen_para_lo_que_sigue(self):
        text = self.read([
            ["INTERNO", "DEBILIDADES", "FORTALEZAS"],
            ["INTERNO", "Poca innovación", "Trayectoria"],
            ["EXTERNO", "AMENAZAS", "OPORTUNIDADES"],
            ["EXTERNO", "Competencia", "Mercado nuevo"],
        ])
        self.assertIn("DEBILIDADES: Poca innovación", text)
        self.assertIn("AMENAZAS: Competencia", text)
        self.assertIn("OPORTUNIDADES: Mercado nuevo", text)
        self.assertNotIn("DEBILIDADES: Competencia", text)

    def test_titulo_de_tabla_no_se_usa_como_columna(self):
        document = Document()
        table = document.add_table(rows=3, cols=2)
        table.cell(0, 0).merge(table.cell(0, 1)).text = "RESUMEN DE AUDITORÍA"
        table.cell(1, 0).text, table.cell(1, 1).text = "EMPRESA", "PROCESO"
        table.cell(2, 0).text, table.cell(2, 1).text = "AR", "Ventas"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.docx"
            document.save(path)
            _, blocks = load_document(str(path))
        self.assertIn("RESUMEN DE AUDITORÍA", blocks[0].text)
        self.assertNotIn("RESUMEN DE AUDITORÍA: ", blocks[0].text)

    def test_formulario_de_datos_y_valores(self):
        text = self.read_three_columns_form()
        self.assertIn("Dirección: Crisol 31", text)
        self.assertIn("Sitios: 1", text)
        self.assertNotIn("Nombre: Dirección", text)

    def read_three_columns_form(self):
        document = Document()
        table = document.add_table(rows=4, cols=3)
        for i, (label, value) in enumerate((
            ("Nombre", "AR"), ("Dirección", "Crisol 31"),
            ("Sitios", "1"), ("Código", "PQC 33"),
        )):
            table.cell(i, 0).paragraphs[0].add_run(label).bold = True
            table.cell(i, 1).merge(table.cell(i, 2)).text = value
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.docx"
            document.save(path)
            _, blocks = load_document(str(path))
        return blocks[0].text

    def test_filas_sin_titulos_no_inventan_columnas(self):
        text = self.read([
            ["Alto", "Todos los procesos de gestión están integrados en un sistema", ""],
            ["Medio", "Parte de los procesos de gestión están integrados en el sistema", ""],
            ["No Aplica", "Los sistemas no están integrados entre sí en la organización", "X"],
        ])
        self.assertNotIn("Alto: Medio", text)
        self.assertIn("Medio", text)
        self.assertIn("Parte de los procesos", text)

    def test_conserva_valores_iguales_en_una_fila(self):
        text = self.read([
            ["N° de no conformidades de la auditoría", "Mayor", "0", "Menor", "0"],
            ["N° de no conformidades cerradas", "Mayor", "0", "Menor", "0"],
        ])
        self.assertIn("Mayor | 0 | Menor | 0", text)

    def test_filas_repetidas_quedan_una_sola_vez(self):
        text = self.read([
            ["Registro", "Lugar", "Tiempo"],
            ["Minuta", "Servidor", "Permanente"],
            ["Minuta", "Servidor", "Permanente"],
            ["Matriz", "Papel", "Un año"],
        ])
        self.assertEqual(text.count("Minuta"), 1)

    def test_datos_en_mayusculas_de_una_sola_celda_no_son_titulos(self):
        text = self.read([
            ["Sigla", "Nombre", "Área"],
            ["SGC", "", ""],
            ["BVC", "Certificadora", "Externa"],
        ])
        self.assertIn("Nombre: Certificadora", text)


class ClausulasTests(unittest.TestCase):
    def test_articulos_de_una_ley(self):
        chunks = chunk_blocks([
            Block("text", "ARTICULO 1° — (Objeto).\nProtección de los datos.", page=1),
            Block("text", "2 No será necesario el consentimiento cuando:\nTexto.", page=2),
            Block("text", "Art. 44. — El contrato terminará.\nSegún el Art. 5 de la ley.", page=8),
        ])
        self.assertEqual(
            [(c.clausula, c.pagina) for c in chunks],
            [("Art. 1", 1), ("Art. 44", 8)],
        )
        self.assertIn("2 No será necesario", chunks[0].content)

    def test_cita_a_otro_articulo_no_abre_uno_nuevo(self):
        chunks = chunk_blocks([
            Block("text", "Art. 3. — Primero.\nArt. 5 de la presente ley se aplica.", page=1),
        ])
        self.assertEqual([c.clausula for c in chunks], ["Art. 3"])

    def test_titulo_sin_numero_cierra_la_clausula(self):
        chunks = chunk_blocks([
            Block("heading", "10. Conclusiones", 9),
            Block("text", "Se verificó la conformidad."),
            Block("heading", "Modificaciones al sistema", 9),
            Block("text", "Debe avisarse a la certificadora."),
        ])
        self.assertEqual([c.clausula for c in chunks], ["10", None])

    def test_item_de_lista_no_es_clausula(self):
        chunks = chunk_blocks([Block(
            "text",
            "ARTICULO 4 Calidad de los datos\n"
            "1 Los datos personales que se recojan a los efectos de su tratamiento\n"
            "texto de la ley",
            page=1,
        )])
        self.assertTrue(all(c.clausula != "1" for c in chunks))

    def test_clausulas_cortas_y_con_subnivel_siguen_valiendo(self):
        chunks = chunk_blocks([Block(
            "text", "10 Mejora\nTexto de mejora.\n"
            "10.2.1 Cuando ocurra una no conformidad, incluida cualquiera originada por quejas, la organización\n"
            "debe reaccionar.", page=1,
        )])
        self.assertEqual([c.clausula for c in chunks], ["10", "10.2.1"])


class PdfTests(unittest.TestCase):
    def test_documento_sin_clausulas_conserva_cada_pagina(self):
        pages = [Block("text", f"Texto de la página {n}. " * 60, page=n) for n in (1, 2, 3)]
        chunks = chunk_blocks(pages)
        self.assertEqual(chunks[0].pagina, 1)
        for chunk in chunks:
            first = re.search(r"página (\d)", chunk.content).group(1)
            self.assertEqual(chunk.pagina, int(first))
        self.assertEqual(chunks[-1].pagina, 3)

    def test_clausula_que_sigue_en_otra_pagina_empieza_en_la_suya(self):
        chunks = chunk_blocks([
            Block("text", "4.1 Alcance\nTexto corto del alcance.", page=7),
            Block("text", "Sigue el alcance en la otra hoja.", page=8),
        ])
        self.assertEqual([(c.clausula, c.pagina) for c in chunks], [("4.1", 7)])

    def test_texto_con_codigos_se_decodifica(self):
        self.assertEqual(
            _decode_pdf_text("/uni004C/uni0045/uni0059/uni0020/uni00ED 1"), "LEY í 1"
        )

    def test_texto_normal_no_cambia(self):
        self.assertEqual(_decode_pdf_text("Ley 11.723"), "Ley 11.723")

    def test_pdf_ilegible_se_rechaza(self):
        with self.assertRaises(ValueError):
            _check_pdf_text([Block("text", "004C 0045 0059 / 0031 0031 / 0037 " * 5, page=1)])

    def test_pdf_legible_se_acepta(self):
        _check_pdf_text([Block("text", "Artículo 1. Las obras científicas.", page=1)])

    def test_clausulas_con_pagina(self):
        chunks = chunk_blocks([
            Block("text", "3.3 Auditorías internas\nSe realizan cada cuatro meses.", page=3),
        ])
        self.assertEqual(chunks[0].clausula, "3.3")
        self.assertEqual(chunks[0].pagina, 3)

    def test_pagina_de_indice_se_omite(self):
        toc = "\n".join(
            f"{n}.1 Título de la sección número {n} {n + 10}" for n in range(1, 8)
        )
        chunks = chunk_blocks([
            Block("text", f"Índice\n{toc}", page=2),
            Block("text", "1.1 Título de la sección número 1\nTexto real.", page=11),
        ])
        self.assertEqual([(c.clausula, c.pagina) for c in chunks], [("1.1", 11)])


if __name__ == "__main__":
    unittest.main()
