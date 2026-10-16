"""Reconcilia una carpeta de Google Drive con Supabase.

Uso:
    python sync_drive.py            (sincroniza)
    python sync_drive.py --dry-run  (muestra qué haría, sin modificar nada)

Identifica cada archivo por su ID de Drive y decide con la huella MD5
si hay que regenerar embeddings. Cada documento se prepara por separado:
si uno falla, conserva su versión anterior y los demás siguen.
Los archivos retirados de la carpeta se desactivan, sin borrarse.

Tipo de documento (norma o documento interno):
- Si la descripción del archivo en Drive tiene una línea
  "norma: ISO 9001:2015", se usa ese valor; "norma: interno" lo marca
  como documento interno.
- Si no, se reconoce por el nombre: NOM_ISO_9001-2015.pdf → ISO 9001:2015.
- Si tampoco, es un documento interno.

Procesa PDF, DOCX, TXT y MD ubicados directamente en la carpeta.
Si cambia la versión del lector (PIPELINE_VERSION en ingest.py), los
archivos procesados con otra versión se vuelven a procesar.

Requiere supabase/005_sync_integrada.sql y 006_estructura_documental.sql.
"""
import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from ingest import EXTS, PIPELINE_VERSION, prepare_file
from rag.clients import supabase

FIELDS = "id,name,mimeType,modifiedTime,version,md5Checksum,description"
STAGE_BATCH = 100  # fragmentos por petición (~1 MB)


# ---------------------------------------------------------------
# Lectura de Drive
# ---------------------------------------------------------------

def snapshot(drive, folder_id: str) -> tuple[str, list[dict]]:
    """Lista la carpeta completa o falla: nunca devuelve un listado parcial."""
    folder = drive.files().get(
        fileId=folder_id,
        fields="id,name,mimeType,trashed",
        supportsAllDrives=True,
    ).execute(num_retries=3)

    if (
        folder.get("trashed")
        or folder["mimeType"] != "application/vnd.google-apps.folder"
    ):
        raise RuntimeError("La carpeta no está disponible. No se aplicó nada.")

    files, token = [], None
    while True:
        result = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields=f"nextPageToken,incompleteSearch,files({FIELDS})",
            pageSize=100,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute(num_retries=3)

        if result.get("incompleteSearch"):
            raise RuntimeError(
                "Drive devolvió un listado incompleto. No se aplicó nada."
            )

        files.extend(result.get("files", []))
        token = result.get("nextPageToken")
        if not token:
            return folder["name"], files


def eligible(file: dict) -> bool:
    return (
        not file["mimeType"].startswith("application/vnd.google-apps.")
        and Path(file["name"]).suffix.lower() in EXTS
    )


def signature(file: dict) -> tuple:
    return (
        file["name"],
        file.get("modifiedTime"),
        file.get("version"),
        file.get("md5Checksum"),
        file.get("description"),
    )


# El nombre debe EMPEZAR con el código de la norma, con prefijos de
# organismos opcionales en mayúsculas (NOM, NTC, UNE, EN, IRAM...):
#   "ISO 9001", "NOM_ISO_9001-2015", "ISO-IEC_27001_2022", "UNE-EN ISO 14001"
# Así "Procedimiento auditorías ISO 9001" sigue siendo documento interno.
ISO_NAME_RE = re.compile(
    r"^(?:[A-Z]{2,5}[\s_-]+)*(?i:ISO)(?:[\s_/-]*((?i:IEC)))?[\s_-]*(\d{4,5})"
    r"(?:[\s_:.-]+((?:19|20)\d{2}))?(?!\d)"
)
NORMA_LINE_RE = re.compile(r"^\s*norma\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)
INTERNAL_VALUES = {"", "interno", "interna", "documento interno", "ninguna", "no"}


def detect_norma(file: dict) -> str | None:
    """Norma del documento, o None si es un documento interno.

    La descripción del archivo en Drive tiene prioridad sobre el nombre,
    para poder corregir a mano cualquier caso.
    """
    match = NORMA_LINE_RE.search(file.get("description") or "")
    if match:
        value = match.group(1)
        return None if value.lower() in INTERNAL_VALUES else value

    match = ISO_NAME_RE.match(Path(file["name"]).stem)
    if not match:
        return None
    iec, number, year = match.groups()
    norma = f"ISO/IEC {number}" if iec else f"ISO {number}"
    return f"{norma}:{year}" if year else norma


def describe(norma: str | None) -> str:
    return f"norma {norma}" if norma else "documento interno"


def download(drive, file: dict, path: Path) -> None:
    request = drive.files().get_media(
        fileId=file["id"], supportsAllDrives=True
    )
    with path.open("wb") as output:
        downloader = MediaIoBaseDownload(output, request)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=3)

    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    if digest.hexdigest() != file["md5Checksum"]:
        raise RuntimeError(
            "El contenido descargado no coincide con la huella de Drive."
        )


# ---------------------------------------------------------------
# Comparación con el estado guardado
# ---------------------------------------------------------------

def classify(file: dict, previous: dict | None) -> str:
    """Qué hay que hacer con un archivo presente en Drive.

    previous es su fila de drive_sync_state más 'active' del documento.
    """
    if not file.get("md5Checksum"):
        return "sin huella"
    if (
        previous is None
        or not previous.get("content_md5")
        or previous["content_md5"] != file["md5Checksum"]
    ):
        return "contenido"
    if previous.get("pipeline_version") != PIPELINE_VERSION:
        return "reprocesar"
    if not previous.get("active", True):
        return "reactivar"
    if (
        previous["file_name"] != file["name"]
        or previous["modified_time"] != file["modifiedTime"]
        or previous.get("drive_version") != file.get("version")
        or previous.get("norma") != detect_norma(file)
    ):
        return "metadatos"
    return "sin cambios"


def decide(
    first: dict[str, dict],
    final: dict[str, dict],
    failed: dict[str, str],
) -> tuple[list[str], list[dict], dict[str, str]]:
    """Compara las dos lecturas de Drive y arma la confirmación.

    Devuelve (presentes, a_aplicar, postergados).
    - presentes: todo archivo compatible de la segunda lectura. Lo que
      no figura se desactiva.
    - a_aplicar: archivos que no fallaron y no cambiaron entre lecturas.
    - postergados: cambiaron o aparecieron durante la sincronización;
      conservan su estado anterior hasta la próxima ejecución.
    """
    present = sorted(final)
    apply, deferred = [], {}

    for file_id in present:
        file = final[file_id]
        if file_id in failed:
            continue
        if file_id not in first:
            deferred[file_id] = "apareció durante la sincronización"
        elif signature(first[file_id]) != signature(file):
            deferred[file_id] = "cambió durante la sincronización"
        else:
            apply.append(
                {
                    "id": file_id,
                    "name": file["name"],
                    "md5": file["md5Checksum"],
                    "modifiedTime": file["modifiedTime"],
                    "version": file.get("version"),
                    "norma": detect_norma(file),
                    "pipeline": PIPELINE_VERSION,
                }
            )

    return present, apply, deferred


# ---------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------

def load_state(db, folder_id: str) -> dict[str, dict]:
    rows, offset = [], 0
    while True:
        page = (
            db.table("drive_sync_state")
            .select("*")
            .eq("folder_id", folder_id)
            .order("file_id")
            .range(offset, offset + 499)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < 500:
            break
        offset += 500

    ids = [row["document_id"] for row in rows]
    docs = {}
    for start in range(0, len(ids), 200):
        for doc in (
            db.table("documents")
            .select("id,active,norma")
            .in_("id", ids[start:start + 200])
            .execute()
            .data
        ):
            docs[doc["id"]] = doc

    for row in rows:
        doc = docs.get(row["document_id"], {})
        row["active"] = doc.get("active", True)
        row["norma"] = doc.get("norma")
    return {row["file_id"]: row for row in rows}


def staged_complete(db, folder_id: str, file: dict) -> bool:
    """True si esta versión del archivo ya quedó preparada con este lector."""
    docs = (
        db.table("drive_staged_documents")
        .select("chunk_total")
        .eq("folder_id", folder_id)
        .eq("file_id", file["id"])
        .eq("content_md5", file["md5Checksum"])
        .eq("pipeline_version", PIPELINE_VERSION)
        .execute()
        .data
    )
    if not docs:
        return False
    chunks = (
        db.table("drive_staged_chunks")
        .select("chunk_index", count="exact")
        .eq("folder_id", folder_id)
        .eq("file_id", file["id"])
        .eq("content_md5", file["md5Checksum"])
        .limit(1)
        .execute()
    )
    return chunks.count == docs[0]["chunk_total"]


def stage(
    db, folder_id: str, file: dict, doc_meta: dict, rows: list[dict]
) -> None:
    """Sube los fragmentos de un documento por lotes."""
    for start in range(0, len(rows), STAGE_BATCH):
        batch = [
            {"chunk_index": start + offset, **row}
            for offset, row in enumerate(rows[start:start + STAGE_BATCH])
        ]
        db.rpc(
            "stage_drive_chunks",
            {
                "p_folder_id": folder_id,
                "p_file_id": file["id"],
                "p_md5": file["md5Checksum"],
                "p_pipeline_version": PIPELINE_VERSION,
                "p_doc_meta": doc_meta,
                "p_total": len(rows),
                "p_chunks": batch,
            },
        ).execute()


# ---------------------------------------------------------------
# Proceso principal
# ---------------------------------------------------------------

def connect_drive():
    key = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]).expanduser()
    if not key.is_absolute():
        key = BASE_DIR / key
    credentials = service_account.Credentials.from_service_account_file(
        str(key),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=credentials)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza la carpeta de Drive con Supabase"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostrar la comparación sin descargar ni modificar Supabase",
    )
    args = parser.parse_args()

    folder_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"].strip()
    drive = connect_drive()
    db = supabase()

    # Se lee antes que todo lo demás: si otra ejecución confirma
    # mientras tanto, la confirmación de esta será rechazada.
    control = (
        db.table("drive_sync_control")
        .select("generation")
        .eq("folder_id", folder_id)
        .execute()
        .data
    )
    generation = control[0]["generation"] if control else 0
    previous = load_state(db, folder_id)

    folder_name, files = snapshot(drive, folder_id)
    first = {f["id"]: f for f in files if eligible(f)}

    print(f"Carpeta: {folder_name} | Compatibles: {len(first)}", flush=True)

    plan = {}
    for file in sorted(first.values(), key=lambda f: f["name"].lower()):
        plan[file["id"]] = classify(file, previous.get(file["id"]))
        print(
            f"  {plan[file['id']]}: {file['name']} "
            f"({describe(detect_norma(file))})",
            flush=True,
        )

    removed = [
        row for file_id, row in previous.items()
        if file_id not in first and row["active"]
    ]
    for row in sorted(removed, key=lambda r: r["file_name"].lower()):
        print(f"  se desactivará: {row['file_name']}", flush=True)

    if args.dry_run:
        print("Simulación terminada. No se descargó ni modificó nada.")
        return 0

    failed: dict[str, str] = {}
    prepared = reused = 0

    with tempfile.TemporaryDirectory(prefix="rag-drive-") as work:
        for file_id, action in plan.items():
            file = first[file_id]
            name = file["name"]

            if action == "sin huella":
                failed[file_id] = "Drive no informó la huella MD5."
                continue
            if action not in ("contenido", "reprocesar"):
                continue

            try:
                if staged_complete(db, folder_id, file):
                    print(f"♻ Reutiliza preparación: {name}", flush=True)
                    reused += 1
                    continue

                # Nombre local fijo: no depende del nombre remoto.
                path = Path(work) / f"{file_id}{Path(name).suffix.lower()}"
                print(f"⬇ Descargando: {name}", flush=True)
                download(drive, file, path)
                doc_meta, rows = prepare_file(path, label=name)
                stage(db, folder_id, file, doc_meta, rows)
                prepared += 1
            except Exception as error:
                failed[file_id] = str(error) or type(error).__name__
                print(f"   ❌ {name}: {failed[file_id]}", flush=True)
            finally:
                for leftover in Path(work).iterdir():
                    leftover.unlink(missing_ok=True)

    # Segunda lectura: Drive no ofrece una foto transaccional.
    _, final_files = snapshot(drive, folder_id)
    final = {f["id"]: f for f in final_files if eligible(f)}

    present, apply, deferred = decide(first, final, failed)

    result = db.rpc(
        "reconcile_drive_folder",
        {
            "p_folder_id": folder_id,
            "p_expected_generation": generation,
            "p_present": present,
            "p_apply": apply,
        },
    ).execute().data

    names = {**{i: f["name"] for i, f in first.items()},
             **{i: f["name"] for i, f in final.items()}}

    print("\n✅ Sincronización confirmada", flush=True)
    print(
        f"   Aplicados: {result['aplicados']} "
        f"(contenido nuevo: {result['contenido_nuevo']}; "
        f"preparados ahora: {prepared}, reutilizados: {reused})\n"
        f"   Desactivados: {result['desactivados']}",
        flush=True,
    )

    for file_id, reason in sorted(deferred.items(), key=lambda i: names[i[0]]):
        print(f"   ⏸ Postergado: {names[file_id]} ({reason})", flush=True)

    for file_id, reason in sorted(failed.items(), key=lambda i: names[i[0]]):
        print(
            f"   ❌ Sin actualizar: {names[file_id]}: {reason} "
            "(conserva su versión anterior, si tenía)",
            flush=True,
        )

    if deferred:
        print("   Volvé a ejecutar para procesar los postergados.", flush=True)

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(f"❌ No se confirmó la sincronización: {error}", flush=True)
        print(
            "La búsqueda quedó como estaba. Si el corte fue durante la "
            "confirmación, ejecutá de nuevo: el estado se reconcilia solo."
        )
        raise SystemExit(1)
