"""Sincroniza archivos de una carpeta de Drive con el RAG.

Uso:
    python sync_drive.py

Procesa PDF, DOCX, TXT y MD directamente dentro de la carpeta.
Omite archivos sin cambios después de una carga exitosa.
No retira documentos eliminados de Drive ni recorre subcarpetas.
"""
import json
import os
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from ingest import EXTS, ingest_file

DOWNLOAD_DIR = BASE_DIR / "docs" / "drive"
STATE_PATH = DOWNLOAD_DIR / "sync_state.json"


def save_state(state: dict) -> None:
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def list_files(drive, folder_id: str) -> list[dict]:
    files = []
    token = None

    while True:
        result = drive.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields=(
                "nextPageToken,"
                "files(id,name,mimeType,modifiedTime,version)"
            ),
            pageSize=100,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute(num_retries=3)

        files.extend(result.get("files", []))
        token = result.get("nextPageToken")
        if not token:
            return files


def download_file(drive, file: dict, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".part")
    try:
        request = drive.files().get_media(
            fileId=file["id"],
            supportsAllDrives=True,
        )
        with temporary.open("wb") as output:
            downloader = MediaIoBaseDownload(output, request)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=3)

        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    folder_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"].strip()
    credential_path = Path(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    ).expanduser()
    if not credential_path.is_absolute():
        credential_path = BASE_DIR / credential_path

    credentials = service_account.Credentials.from_service_account_file(
        str(credential_path),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    drive = build("drive", "v3", credentials=credentials)

    folder = drive.files().get(
        fileId=folder_id,
        fields="name,mimeType",
        supportsAllDrives=True,
    ).execute(num_retries=3)
    if folder["mimeType"] != "application/vnd.google-apps.folder":
        raise RuntimeError("El ID configurado no corresponde a una carpeta.")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    state = (
        json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if STATE_PATH.exists()
        else {}
    )
    records = state.setdefault(folder_id, {})

    files = list_files(drive, folder_id)
    supported = [
        file for file in files
        if not file["mimeType"].startswith("application/vnd.google-apps.")
        and Path(file["name"]).suffix.lower() in EXTS
    ]

    # ingest_file identifica los documentos por nombre:
    # dos archivos con igual nombre se reemplazarían entre sí.
    counts = Counter(file["name"] for file in supported)
    duplicates = [name for name, count in counts.items() if count > 1]
    if duplicates:
        raise RuntimeError(
            "Renombrá estos archivos repetidos antes de sincronizar: "
            + ", ".join(duplicates)
        )

    loaded = skipped = errors = 0
    print(f"Carpeta: {folder['name']}", flush=True)
    print(f"Documentos compatibles: {len(supported)}", flush=True)

    for file in sorted(supported, key=lambda item: item["name"]):
        name = file["name"]
        previous = records.get(file["id"])
        fingerprint = {
            "name": name,
            "modifiedTime": file["modifiedTime"],
            "version": file.get("version"),
        }

        try:
            if Path(name).name != name or "\\" in name:
                raise RuntimeError("Nombre de archivo no válido.")

            if previous and previous["name"] != name:
                raise RuntimeError(
                    f"El archivo antes se llamaba {previous['name']}. "
                    "Hay que resolver el cambio de nombre en Supabase."
                )

            if previous == fingerprint:
                print(f"⏭ Sin cambios: {name}", flush=True)
                skipped += 1
                continue

            # Cada ID tiene su directorio para evitar conflictos locales.
            directory = DOWNLOAD_DIR / file["id"]
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / name

            print(f"⬇ Descargando: {name}", flush=True)
            download_file(drive, file, destination)
            ingest_file(destination)

            # Solo registrar el cambio si la carga terminó correctamente.
            records[file["id"]] = fingerprint
            save_state(state)
            loaded += 1

        except Exception as error:
            errors += 1
            print(f"❌ {name}: {error}", flush=True)

    print(
        f"\nCargados: {loaded} | Sin cambios: {skipped} | Errores: {errors}",
        flush=True,
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()