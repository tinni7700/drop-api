from posixpath import dirname
import random
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
    exclude_names = {
        ".DS_Store",
        "Thumbs.db",
        "_final.csv",
        "_removed.csv",
    }
    exclude_exts = exclude_exts or {".zip"}  # add more if needed (e.g., ".tmp", ".log")

    files = [
        f for f in os.listdir(folder_name)
        if f not in exclude_names and os.path.splitext(f)[1].lower() not in exclude_exts and not str(f).endswith(tuple(exclude_names))
    ]
    return files




def main():

    # config setting
    # logger info
    
    http_client = HttpClient(api_key=settings.X_API_KEY)
    http_client.set_logger(logger)


    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    file_path = f"{generate_folder_name(timestamp)}/{generate_file_name(timestamp)}"   
    file_path = "uploads/2026-08-10-14-29-53/output-2026-08-10-14-29-53.zip"  # for testing purpose

    # response = download_file(
    #     url=url_mapping["download"],
    #     http_client=http_client,
    #     file_path=file_path,
    # )
    # logger.info(f"Download response: {response}")

    # if isinstance(response, str) and response.startswith("File saved to"):
    #     unzip_file(zip_file_path=file_path, extract_to_folder=dirname(file_path))

    # log the files in the folder and display to user and stored into db for further processing
    read_folder = dirname(file_path)
    files = exclude_files(read_folder)
    logger.info(f"Files in the folder: {files}")

    # # do you want to upload file into cloud azureblob
    # insert_to_db(
    #     files=files,
    #     folder_name=read_folder

    # )

    # logger.info("--------------- All files downloaded successfully.---------------")


    # Check if Table is already exists into db
    # log the files in the db to process for matching and uploading
    # # read file into pandas and generate table for it
    # for file in files:
    #     file_path = os.path.join(read_folder, file)
    #     output_path = os.path.join(read_folder, f"{os.path.splitext(file)[0]}_final.csv")
    #     table_name = f"DROP_{os.path.splitext(file)[0]}"
    #     # read file into pandas and generate table for it 
    #     # update the status of the file in the db to processing


    #     # log table into db for processing...
    #     check_result = check_table(
    #         table=table_name
    #     )

    #     if check_result.get("status") == True:

    #         result= drop_table(
    #             table=table_name
    #         )
    #         logger.info(
    #             check_result.get("message", f"Table {table_name} already exists. Skipping file {file}.")
    #         )

    #     result = sanitize_file(
    #         file_path=file_path,
    #         output_path=output_path,
    #         table= table_name,
    #         columns_to_ascii=["Hash"]
    #     )

    #     if result.get("status") == True:
    #         logger.info(f"File {file} sanitized successfully.")
    #         # update the status of the file in the db to processed
        
    
    # logger.info("--------------- All files processed successfully.---------------")
    random_num = random.randint(1, 100)
    # # prepare file for write
    # for file in files:
    #     file_path = os.path.join(read_folder, file)
    #     table_name = f"DROP_{os.path.splitext(file)[0]}"
        

    #     output_path = os.path.join(read_folder, f"{os.path.splitext(file)[0]}_{random_num}_final.csv")

    #     result = check_table(
    #         table=table_name
    #     )

    #     if result.get("status") == False:
    #         logger.info(
    #             result.get("message", f"Table {table_name} does not exist. Skipping file {file}.")
    #         )
    #         continue

    #     result = read_from_db_to_write(
    #         table_name,
    #         output_path
    #     )
    #     if result.get("status") == True:
    #         logger.info(
    #             result.get("message", f"File {file} read successfully and saved to {output_path}.")
    #         )

    #     # update the status of the file in the db to ready for upload
    #     update_status(
    #         file_name=file,
    #         status=1
    #     )
    
    # logger.info("--------------- All files written successfully.---------------")



            

    # Upload files
    random_num = 50
    for file in files:
        output_path = os.path.join(read_folder, f"{os.path.splitext(file)[0]}_{random_num}_final.csv")

        if not os.path.exists(output_path):
            logger.error(f"File {output_path} does not exist. Skipping upload.")
            continue

        logger.info(f"Uploading file {output_path}...")
        response = amend_csv_file(
            url=url_mapping["upload"],
            http_client=http_client,
            file_path=output_path
        )
        logger.info(f"Upload response for {file}: {response}")

        if response.get("acceptedCount"):
            # update the status of the file in the db to uploaded
            update_status(
                file_name=file,
                status=2
            )

    logger.info("--------------- All files processed and uploaded successfully.---------------")

    # Amend files if your file is not uploaded successfully or you want to amend the file and reupload the file

    

    # upload file into cloud and update the status of the file in the db to uploaded
    # update table using join or call it stored procedure to update status
    # reprocess the file if possible by deleting the old table and reprocess the table






    

# 1. dowload file and store it
# 2. unzip file
# 3. start process file one by one and match it
# 4. upload file one by one
# 5. log all the steps and errors
# 6. if any error occurs, log the error and stop the process and amend the files

if __name__ == "__main__":
    main()
