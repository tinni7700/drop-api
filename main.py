from pathlib import Path
from posixpath import dirname
import subprocess
import time

import requests
import typer
from config import settings
from http_client import HttpClient
from logger import logger
from datetime import datetime
import os

from process import check_table, insert_to_db, read_from_db_to_write, sanitize_file, update_status, drop_table

def upload_csv_file(url, http_client: HttpClient, file_path):

    result = http_client.post(url=url, accept="application/json", file_name=file_path)

    return result


def amend_csv_file(url, http_client: HttpClient, file_path):
    response = http_client.post(
        url=url,
        accept="application/json",
        file_name=file_path
    )
    return response

def download_file(url, http_client: HttpClient, file_path):

    result = http_client.get(
        url=url, accept="application/zip, application/json", file_path=file_path
    )

    return result

def unzip_file(zip_file_path, extract_to_folder):
    import zipfile

    if not os.path.exists(extract_to_folder):
        os.makedirs(extract_to_folder)

    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to_folder)

def generate_file_name(timestamp):
    return f"output-{timestamp}.zip"

def generate_folder_name(timestamp=None):
    folder_name = f"uploads/{timestamp}"
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    return folder_name

url_mapping = {
    "download": f"{settings.BASE_URL}/data/download",
    "upload": f"{settings.BASE_URL}/data/upload",
    "amend": f"{settings.BASE_URL}/data/amend",
}

def exclude_files(folder_name, exclude_names=None, exclude_exts=None):
    # NOTE: "final.csv" (no underscore) because exported files are named
    # <name>_<DDMM>final.csv, which does not end with "_final.csv".
    exclude_names = {
        ".DS_Store",
        "Thumbs.db",
        "final.csv",
        "_removed.csv",
    }
    exclude_exts = exclude_exts or {".zip"}  # add more if needed (e.g., ".tmp", ".log")

    files = [
        f for f in os.listdir(folder_name)
        if f not in exclude_names and os.path.splitext(f)[1].lower() not in exclude_exts and not str(f).endswith(tuple(exclude_names))
    ]
    return files


def request_for_file(url, http_client: HttpClient, file_path=None):

    result = http_client.get(
        url=url, accept="*/*", file_path=file_path
    )

    return result


def create_app_context() -> HttpClient:
    http_client = HttpClient(api_key=settings.X_API_KEY)
    http_client.set_logger(logger)
    return http_client


app = typer.Typer(
    name="drop-api",
    help="DROP BROKER API",
    add_completion=False,
)


# ------------------------------------------------------------------ #
#  Reusable step functions (used by both the CLI commands and main()) #
# ------------------------------------------------------------------ #

POLL_INTERVAL_SECONDS = int(os.getenv("BATCH_POLL_INTERVAL", "180"))   # 3 minutes
MAX_WAIT_SECONDS = int(os.getenv("BATCH_MAX_WAIT", "1800"))            # give up after 30 min
LOCK_FILE = os.getenv("DROP_LOCK_FILE", "/tmp/drop-broker.lock")


def final_name(file, folder, suffix):
    return os.path.join(folder, f"{os.path.splitext(file)[0]}_{suffix}final.csv")


def fix_header_quotes(csv_path):
    """Remove double quotes from the first (header) line only (same as: sed -i '1s/"//g')."""
    subprocess.run(["sed", "-i", '1s/"//g', csv_path], check=True)


def run_request_batch(http_client):
    response = request_for_file(url=url_mapping["download"], http_client=http_client, file_path=None)
    logger.info(f"Requestbatch response: {response}")
    return response


def run_download(http_client):
    """Download + unzip + register in DB. Returns the folder holding the CSVs."""
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    file_path = f"{generate_folder_name(timestamp)}/{generate_file_name(timestamp)}"

    response = download_file(
        url=url_mapping["download"], http_client=http_client, file_path=file_path
    )
    logger.info(f"Download response: {response}")

    if not (isinstance(response, str) and response.startswith("File saved to")):
        raise RuntimeError(f"Download did not return a zip file: {response!r}")

    read_folder = dirname(file_path)
    unzip_file(zip_file_path=file_path, extract_to_folder=read_folder)
    files = exclude_files(read_folder)
    logger.info(f"Files in the folder: {files}")
    insert_to_db(files=files, folder_name=read_folder)
    return read_folder


def wait_and_download(http_client):
    """Request a batch, then poll every POLL_INTERVAL_SECONDS until the zip is ready."""
    run_request_batch(http_client)
    waited = 0
    while True:
        try:
            return run_download(http_client)
        except requests.HTTPError as e:
            # 401/403 will never fix themselves by waiting
            if "HTTP Error: 401" in str(e) or "HTTP Error: 403" in str(e):
                raise
            logger.info(f"Batch not ready yet ({e}).")
        except RuntimeError as e:
            logger.info(f"Batch not ready yet ({e}).")

        if waited >= MAX_WAIT_SECONDS:
            raise TimeoutError(f"Batch not ready after {MAX_WAIT_SECONDS} seconds.")
        logger.info(f"Waiting {POLL_INTERVAL_SECONDS}s before next poll...")
        time.sleep(POLL_INTERVAL_SECONDS)
        waited += POLL_INTERVAL_SECONDS


def run_process(read_folder):
    files = exclude_files(read_folder)
    logger.info(f"Files in the folder: {files}")
    for file in files:
        file_path = os.path.join(read_folder, file)
        table_name = f"DROP_{os.path.splitext(file)[0]}"

        check_result = check_table(table=table_name)
        if check_result.get("status") == True:
            drop_table(table=table_name)
            logger.info(check_result.get("message", f"Table {table_name} already exists. Dropped."))

        result = sanitize_file(
            file_path=file_path,
            output_path=None,  # does not require file here
            table=table_name,
            columns_to_ascii=["Hash"],
        )
        if result.get("success") == True or result.get("status") == True:
            logger.info(f"File {file} sanitized successfully.")
        else:
            raise RuntimeError(f"Sanitize failed for {file}: {result}")


def run_export(read_folder, suffix):
    """Write each table back to <name>_<suffix>final.csv. Returns the list of outputs."""
    outputs = []
    for file in exclude_files(read_folder):
        table_name = f"DROP_{os.path.splitext(file)[0]}"
        output_path = final_name(file, read_folder, suffix)

        result = check_table(table=table_name)
        if result.get("status") == False:
            logger.info(result.get("message", f"Table {table_name} does not exist. Skipping file {file}."))
            continue

        result = read_from_db_to_write(table_name, output_path)
        if result.get("status") == True:
            logger.info(result.get("message", f"File {file} saved to {output_path}."))
        update_status(file_name=file, status=1)
        outputs.append(output_path)
    return outputs


def run_upload(read_folder, suffix, http_client):
    """Upload each final csv. Returns the list of files that were NOT accepted."""
    failed = []
    for file in exclude_files(read_folder):
        output_path = final_name(file, read_folder, suffix)
        if not os.path.exists(output_path):
            logger.error(f"File {output_path} does not exist. Skipping upload.")
            failed.append(output_path)
            continue

        logger.info(f"Uploading file {output_path}...")
        response = amend_csv_file(
            url=url_mapping["upload"], http_client=http_client, file_path=output_path
        )
        logger.info(f"Upload response for {file}: {response}")

        if response.get("acceptedCount"):
            update_status(file_name=file, status=2)
        else:
            failed.append(output_path)
    return failed


# ------------------------------------------------------------------ #
#  CLI commands (individual steps, unchanged usage)                   #
# ------------------------------------------------------------------ #

def _folder_from_option(file_path):
    path = Path(file_path)
    if not path.exists():
        logger.error(f"File does not exist: {path}")
        raise typer.Exit(code=1)
    return dirname(path)


@app.command()
def requestbatch():
    """Request a batch
    Example: uv run main.py requestbatch
    """
    try:
        run_request_batch(create_app_context())
    except Exception as e:
        logger.error(f"Error in requestbatch: {e}")
        raise


@app.command()
def download():
    """Download file
    Example: uv run main.py download
    """
    try:
        run_download(create_app_context())
        logger.info("--------------- All files downloaded successfully.---------------")
    except Exception as e:
        logger.error(f"Error in downloading file: {e}")
        raise


@app.command()
def processfile(
    file_path: str = typer.Option(..., "--filepath", "-f", help="File path for processing file"),
):
    """Start processing file
    Example: uv run main.py processfile --filepath "uploads/2026-08-19-13-31-19/output-2026-08-19-13-31-19.zip"
    """
    try:
        run_process(_folder_from_option(file_path))
        logger.info("--------------- All files processed successfully.---------------")
    except Exception as e:
        logger.error(f"Error in processing : {e}")
        raise


@app.command()
def exportfile(
    file_path: str = typer.Option(..., "--filepath", "-f", help="File path for processing file"),
):
    """Export file
    Example: uv run main.py exportfile --filepath "uploads/2026-08-19-13-31-19/output-2026-08-19-13-31-19.zip"
    """
    try:
        run_export(_folder_from_option(file_path), datetime.now().strftime("%d%m"))
        logger.info("--------------- All files written successfully.---------------")
    except Exception as e:
        logger.error(f"Error in export file : {e}")
        raise


@app.command()
def uploadfile(
    file_path: str = typer.Option(..., "--filepath", "-f", help="File path for exportfile"),
):
    """Upload file
    Example: uv run main.py uploadfile --filepath "uploads/2026-08-19-13-31-19/output-2026-08-19-13-31-19.zip"
    """
    try:
        run_upload(_folder_from_option(file_path), datetime.now().strftime("%d%m"), create_app_context())
        logger.info("--------------- All files processed and uploaded successfully.---------------")
    except Exception as e:
        logger.error(f"Error in upload file : {e}")
        raise


# ------------------------------------------------------------------ #
#  Full pipeline (cron entry point)                                   #
# ------------------------------------------------------------------ #

def main():
    """request -> poll (3 min) -> download -> process -> export -> fix header -> upload.
    Any failure raises, so nothing is uploaded after a failed step."""
    http_client = create_app_context()
    suffix = datetime.now().strftime("%d%m")  # computed once so every step agrees

    logger.info("=============== DROP pipeline started ===============")
    read_folder = wait_and_download(http_client)

    run_process(read_folder)

    outputs = run_export(read_folder, suffix)
    expected = [final_name(f, read_folder, suffix) for f in exclude_files(read_folder)]
    missing = [p for p in expected if p not in outputs]
    if missing:
        raise RuntimeError(f"Export did not produce: {missing}")

    for path in outputs:
        fix_header_quotes(path)
        logger.info(f"Header fixed: {path}")

    failed = run_upload(read_folder, suffix, http_client)
    if failed:
        raise RuntimeError(f"Upload not accepted for: {failed}")

    logger.info("=============== DROP pipeline finished successfully ===============")


@app.command()
def run():
    """Run the whole pipeline (for cron).
    Example: uv run main.py run
    """
    lock = None
    try:
        try:
            import fcntl
            lock = open(LOCK_FILE, "w")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("Another run is already in progress. Exiting.")
            raise typer.Exit(code=1)
        except ImportError:
            pass  # no fcntl (Windows): run without a lock

        main()
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise typer.Exit(code=1)
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    app()
