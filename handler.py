import os
import json
import uuid
import shutil
import boto3

from sqlalchemy import create_engine, Column, Integer, String, JSON
from sqlalchemy.orm import sessionmaker, declarative_base
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

user = os.getenv("DB_USER")
password = os.getenv("DB_PASSWORD")
host = os.getenv("DB_HOST")
port = os.getenv("DB_PORT")
db_name = os.getenv("DB_NAME")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION")

cadena_conexion = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
engine = create_engine(cadena_conexion)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DataOCR(Base):
    __tablename__ = 'data_ocr'

    id = Column(Integer, primary_key=True)
    id_user = Column(String, nullable=False)
    data_ine = Column(JSON, nullable=True)
    data_domicilio = Column(JSON, nullable=True)
    data_constancia = Column(JSON, nullable=True)
    data_ine_reverso = Column(JSON, nullable=True)


def handler(event, context):
    user_id = event.get("user_id")

    if not user_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Parámetro 'user_id' es requerido"})
        }

    # Conectar a DB
    try:
        db = SessionLocal()
        db_data_ocr = db.query(DataOCR).filter(DataOCR.id_user == str(user_id)).first()
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Error al conectar a la base de datos: {str(e)}"})
        }

    if not db_data_ocr or not db_data_ocr.data_ine:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "No se encontró información del usuario o data_ine está vacío"})
        }

    try:
        curp = db_data_ocr.data_ine["curp"]
    except KeyError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "La CURP no ha sido encontrada en data_ine"})
        }

    download_dir = f"/tmp/descargas_{uuid.uuid4()}"
    os.makedirs(download_dir, exist_ok=True)
    absolute_path = os.path.abspath(download_dir)

    SITE_URL = "https://www.gob.mx/curp/"
    FILE_NAME = f"user_{user_id}/validacion_curp_{user_id}.pdf"
    downloaded_path = os.path.join(download_dir, "curp.pdf")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            page.goto(SITE_URL)
            page.fill("#curpinput", curp)
            page.click("#searchButton")
            page.wait_for_selector("#download", timeout=10000)

            with page.expect_download() as download_info:
                page.click("#download")
            download = download_info.value
            download.save_as(downloaded_path)

            browser.close()

        # Subir a S3
        s3 = boto3.client("s3", region_name=S3_REGION)
        with open(downloaded_path, "rb") as f:
            s3.upload_fileobj(
                f,
                S3_BUCKET_NAME,
                FILE_NAME,
                ExtraArgs={"ContentType": "application/pdf"}
            )

    except Exception as e:
        shutil.rmtree(absolute_path, ignore_errors=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Error durante la automatización o subida a S3: {str(e)}"})
        }

    shutil.rmtree(absolute_path, ignore_errors=True)

    # Generar URL temporal (presigned URL) para acceder al PDF
    try:
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': FILE_NAME},
            ExpiresIn=3600
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Validación CURP exitosa y archivo subido",
                "s3_key": FILE_NAME,
                "download_url": presigned_url
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"No se pudo generar URL de descarga: {str(e)}"})
        }
