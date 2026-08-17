import base64
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from db import get_db_connection, get_engine
from log_model import DropLogInfoModel
from logger import logger


# ------------------------------------------------------------------ #
#  Low-level cleaners                                                #
# ------------------------------------------------------------------ #
def remove_all_non_ascii(val: str) -> str:
    """Strips every character outside ASCII 0-127."""
    return val.encode("ascii", errors="ignore").decode("ascii")

def remove_non_zip_code_chars(val: str) -> str:
    """Allows only 5-digit or 9-digit zip codes, removes anything else and return None."""
    return val if re.fullmatch(r"\d{5}(-\d{4})?", val) else None

def base64_decode_to_sha256(val: str) -> str:
    """If the value is a base64-encoded string, decode it and return its SHA256 hash. Otherwise, return None."""
    try:
        decoded = base64.b64decode(val)
        #return decoded.hex() # or hashlib.sha256(decoded).hexdigest() if you want the hash instead of hex representation
        return val
    except Exception:
        return None

def normalize_unicode(val: str) -> str:
    """
    Converts accented chars to ASCII equivalent where possible.
    café -> cafe, résumé -> resume
    Non-latin scripts (Chinese, Arabic) that have no ASCII
    equivalent are dropped.
    """
    normalized = unicodedata.normalize("NFKD", val)
    return normalized.encode("ascii", errors="ignore").decode("ascii")


def remove_dangerous_only(val: str) -> str:
    """
    Keeps all readable unicode (Chinese, Arabic, emoji etc.)
    but removes invisible and dangerous control characters.
    """
    val = val.replace("\x00", "")                               # null bytes
    val = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", val) # zero-width chars
    val = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", val)# control chars
    return val.strip()


STRATEGY_MAP = {
    "remove"   : remove_all_non_ascii,
    "normalize": normalize_unicode,
    "safe_only": remove_dangerous_only,
    "zip_code"  : remove_non_zip_code_chars, # for codes we want to be extra strict
}

COLUMN_SANITIZE_CONFIG = {
    "name"        : "normalize",   # café -> cafe
    "email"       : "remove",      # strict ascii
    "description" : "safe_only",   # keep chinese/arabic, strip hidden chars
    "product_code": "remove",      # strict ascii for codes
    "notes"       : "safe_only",   # multilingual ok
}

# override per request or per task if needed
custom_config = {
    "customer_name": "normalize",
    "order_ref"    : "remove",
}

# ------------------------------------------------------------------ #
#  File readers                                                        #
# ------------------------------------------------------------------ #

def read_file(file_path: str) -> tuple[pd.DataFrame, str]:
    """
    Reads CSV or XLSX into a DataFrame.
    Returns (dataframe, detected_extension).
    """
    path = Path(file_path)
    ext  = path.suffix.lower()
    df = pd.DataFrame() # initialize empty DataFrame in case of failure, will be caught by caller
    if ext == ".csv":
        # Read the first 10 lines of the CSV file
        try:
            df = pd.read_csv(
                path,
                #dtype=str,
                keep_default_na=False,
                on_bad_lines="skip"
            )
            if any(
                str(x).isdigit()
                for col, x in df.iloc[0].items()
                if col != "Id"
            ):
                df = pd.read_csv(
                    path,
                    #dtype=str,
                    keep_default_na=False,
                    on_bad_lines="skip",
                    header =None
                )
            if df.empty or df.columns.size == 0:
                raise ValueError("No columns to parse from file.")
        except Exception:
            df = pd.read_csv(
                path,
                #dtype=str,
                keep_default_na=False,
                on_bad_lines="skip",
                encoding="latin-1"
            )
            if df.empty or df.columns.size == 0:
                raise ValueError("The file is empty or has no readable columns.")


    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(
            path,
            sheet_name=0, # Read only the first sheet
            dtype=str,
            keep_default_na=False,
            engine='calamine',       # openpyxl for xlsx, avoids xlrd CVEs
        )
        if any(
            str(x).isdigit()
            for col, x in df.iloc[0].items()
            if col != "Id"
        ):
            df = pd.read_excel(
                path,
                sheet_name=0, # Read only the first sheet
                dtype=str,
                keep_default_na=False,
                engine='calamine',       # openpyxl for xlsx, avoids xlrd CVEs
                header=None
            )
    else:
        raise ValueError(f"Unsupported file type: {ext}. Allowed: .csv, .xlsx, .xls")

    return df, ext


# ------------------------------------------------------------------ #
#  File writers                                                        #
# ------------------------------------------------------------------ #

def write_file(df: pd.DataFrame, output_path: str, ext: str) -> str:
    """
    Writes cleaned DataFrame back to the same format it was read from.
    """
    path = Path(output_path)

    if ext == ".csv":
        df.to_csv(path, index=False, encoding="utf-8", mode="w", quoting=csv.QUOTE_ALL)

    elif ext in {".xlsx", ".xls"}:
        df.to_excel(path, index=False, engine="calamine")

    # Generate paraqueut file if needed for downstream processing, can be extended to support more formats in the future
    elif ext == ".parquet":
        df.to_parquet(path.with_suffix(".parquet"), index=False)

    elif ext == ".json":
        df.reset_index().to_json(path.with_suffix(".json"), orient="records", lines=True)

    return str(path)


# ------------------------------------------------------------------ #
#  Column-level sanitizer                                              #
# ------------------------------------------------------------------ #

def sanitize_dataframe(
    df              : pd.DataFrame,
    strategy        : str       = "normalize",
    columns_to_ascii: list[str] = None,
) -> pd.DataFrame:
    """
    Applies character sanitization to all string columns.

    Args:
        df:               Input DataFrame (all columns should be str dtype).
        strategy:         "remove" | "normalize" | "safe_only"
        columns_to_ascii: Columns that must be strict ASCII regardless of strategy
                          (useful for IDs, codes, reference numbers).
    """
    if strategy not in STRATEGY_MAP:
        raise ValueError(f"Invalid strategy '{strategy}'. Choose: {list(STRATEGY_MAP)}")

    clean_fn         = STRATEGY_MAP[strategy]
    columns_to_ascii = set(columns_to_ascii or [])
    str_cols         = df.select_dtypes(include="object").columns

    for col in str_cols:
        if col in columns_to_ascii:
            # always force strict ASCII on these columns
            df[col] = df[col].apply(
                # lambda v: remove_all_non_ascii(v) if isinstance(v, str) else v
                lambda v: base64_decode_to_sha256(v) if isinstance(v, str) else v
            )
        else:
            df[col] = df[col].apply(
                lambda v: clean_fn(v) if isinstance(v, str) else v
            )

    return df

# ------------------------------------------------------------------ #
#  SQL Server Loading                                                    #
# ------------------------------------------------------------------ #
def load_to_sql(df: pd.DataFrame, table: str, schema_name: str="input"):
    # never use f-strings for table names — whitelist them
    ALLOWED_TABLES = {"users", "orders", "payments"} # extend this set with all allowed table names
    if table in ALLOWED_TABLES:
        raise ValueError(f"Table '{table}' is not allowed")

    try:            
        # use chunksize to avoid memory issues on large files
        df.to_sql(
            name=table,
            con=get_engine(),
            schema=schema_name,
            if_exists="append",      # never "replace" in production
            index=False,
            chunksize=20_000,           # insert 500 rows at a time
            #method="multi",          # faster batch insert
        )
    except Exception as exc:
        # catch-all for anything else
        logger.error(f"Unexpected error during load: {exc}", exc_info=True)
        raise

def call_stored_procedure(params: dict|None, table: str= None):
    # never use f-strings for procedure names — whitelist them
    db = get_db_connection()
    try:
        # Build parameter placeholders for the stored procedure
        query = text(f"""
        SET NOCOUNT ON;
        DECLARE @RC int
        DECLARE @InputTableName nvarchar(261)
        DECLARE @SummaryJson nvarchar(max)

        -- TODO: Set parameter values here.
        SET @InputTableName = :table_name
        EXECUTE @RC = [dbo].[ProcessCalInput] 
        @InputTableName
        ,@SummaryJson OUTPUT

        SELECT @SummaryJson AS SummaryJson

        """)
        
        result = db.execute(query, {"table_name": table }).fetchone()

        # -- Test code
        # query = text(f"UPDATE {table} SET code = 3 WHERE code = 0")  # Example query, replace with your actual stored procedure call
        # result = db.execute(query)

        # #id_in = [(80716,), (80726,), (80736,), (80773,), (80787,)]
        # query = text(f"UPDATE {table} SET code = 2 WHERE Id IN (80716, 80726, 80736, 80773, 80787)")  # Updated query for IN clause
        # result = db.execute(query)
        # -- Test code End        

        db.commit()
        return result
        #return {"SummaryJson": "Success"}
    except Exception as exc:
        logger.exception(f"Error calling stored procedure {table}")
        raise
    finally:
        db.close()


# ------------------------------------------------------------------ #
#  Main entry point                                                  #
# ------------------------------------------------------------------ #

def sanitize_file(
    file_path       : str,
    output_path     : str = None,
    strategy        : str       = "normalize",
    columns_to_ascii: list[str] = None,
    table           : str = None
) -> dict:
    """
    Full pipeline:
      1. Detect file type (csv / xlsx)
      2. Read into DataFrame
      3. Sanitize all string columns
      4. Write back to same format

    Returns summary dict with row count and output path.
    """
    if not table:
        raise ValueError("Table name must be provided for SQL loading.")

    df, ext = read_file(file_path)

    original_rows = len(df)

    df = sanitize_dataframe(
        df,
        strategy=strategy,
        columns_to_ascii=columns_to_ascii,
    )


    # drop rows that became completely empty after sanitization
    df.replace("", pd.NA, inplace=True)
    df.dropna(how="all", inplace=True)
    df.fillna("", inplace=True)

    # path = Path(output_path)
    # ext = path.suffix.lower() or ext # use output extension if provided, else keep original
    # saved_to = write_file(df, output_path, ext) # always save as csv for simplicity, can be extended to keep original format if needed
    # append column to df

    df.rename(
        columns={"Hash": "hashInput"},
        inplace=True
    )
    df["code"] = 5 # This is default # 5	Not found	No match found after completing the matching process
    logger.info(f"Loading into Table: {table}")
    load_to_sql(df, table , "input")
    logger.info(f"Processing Query: {table}")

    # call stored procedure here....
    table = f"input.{table}"
    result = call_stored_procedure({}, table=table)
    logger.info(f"Result : {result}")


    return {
        "original_rows": original_rows,
        "success": True,
    }

def drop_table(table: str, schema_name: str="input"):
    db = get_db_connection()
    try:
        drop_query = text(f"DROP TABLE {schema_name}.{table}")
        db.execute(drop_query)
        db.commit()
        return {
            "status": True,
            "message": f"Table {schema_name}.{table} existed and was dropped successfully."
        }
    except Exception as exc:
        logger.exception(f"Error dropping table {schema_name}.{table}")
        raise
    finally:
        db.close()

def check_table(table: str, schema_name: str="input"):
    db = get_db_connection()
    try:
        query = text(f"""
        SELECT CASE 
            WHEN OBJECT_ID(:full_table_name, 'U') IS NOT NULL THEN 1
            ELSE 0
        END AS TableExists
        """)
        full_table_name = f"{schema_name}.{table}"
        result = db.execute(query, {"full_table_name": full_table_name}).scalar()
        if result:
            return {
                "status": True,
                "message": f"Table {schema_name}.{table} exist."
            }
        return {
            "status": False,
            "message": f"Table {schema_name}.{table} does not exist."
        }
    except Exception as exc:
        logger.exception(f"Error checking/dropping table {schema_name}.{table}")
        raise
    finally:
        db.close()


def insert_to_db(files: list[str], folder_name: str):
    db = get_db_connection()
    try:

        for file_name in files:
            data = {
                "file_name": file_name,
                "folder_name": folder_name
            }

            result = db.query(
                DropLogInfoModel
            ).filter(
                DropLogInfoModel.file_name == file_name
            ).first()

            if result:
                logger.info(f"File {file_name} already exists in table. Skipping insertion.")
                continue
            
            drop_log_info_model = DropLogInfoModel(
                **data
            )
            db.add(drop_log_info_model)
            db.commit()
            logger.info(f"File {file_name} insert into table successfully.")

    except Exception as exc:
        logger.exception(f"Error inserting into table")
        raise
    finally:
        db.close()

# read from table using pandas and write into file for processing and upload to azure blob
def read_from_db_to_write(table: str, output_path: str, schema_name: str="input"):
    db = get_db_connection()
    try:
        query = text(f"SELECT Id,code AS Status FROM {schema_name}.{table}")
        df = pd.read_sql(query, db.connection())
        result = write_file(df, output_path, ".csv")
        if result:
            return {
                "status": True,
                "message": f"Data read from table {schema_name}.{table} and written to {output_path} successfully."
            }

        return {
            "status": True,
            "message": f"Data read from table {schema_name}.{table} and written to {output_path} successfully."
        }
    except Exception as exc:
        logger.exception(f"Error reading from table {schema_name}.{table}")
        raise
    finally:
        db.close()

def update_status(file_name: str, status: int):
    db = get_db_connection()
    try:
        result = db.query(DropLogInfoModel).filter(DropLogInfoModel.file_name == file_name).update({"status": status})
        db.commit()
        if result == 0:
            logger.warning(f"No record found for file_name {file_name} to update status.")
            return {
                "status": False
            }

        logger.info(f"Status updated to {status} for file_name {file_name} in table .")
        return {
            "status": True
        }
    except Exception as exc:
        logger.exception(f"Error updating status in table")
        raise
    finally:
        db.close()