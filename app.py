import os
import uuid
import time
import io
import shutil
import boto3
import requests

from fastapi import FastAPI, APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright
from sql.database import get_db
from sql import models

# Configuración de variables de entorno
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET")
API_KEY_RECAPTCHA = os.getenv("API_KEY_RECAPTCHA")

app = FastAPI(
    title="Servicio de Validación con Playwright",
    version="1.0.0"
)

# Habilitar CORS si es necesario
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Definir router y montarlo
router = APIRouter()

@app.get("/")
def root():
    return {"message": "API de validación de CURP e INE con Playwright"}

@router.get("/validate_ine_playwright")
def get_validate_ine_playwright(user_id: int = None, db: Session = Depends(get_db)):
    db_data_ocr = db.query(models.DataOCR).filter(models.DataOCR.id_user == user_id).first()
    if not db_data_ocr or not db_data_ocr.data_ine_reverso:
        raise HTTPException(status_code=404, detail='No se encontró información del usuario')
    try:
        CIC = db_data_ocr.data_ine_reverso["identificador"][:-1]
        ID_CIUDADANO = db_data_ocr.data_ine_reverso["code_ocr"][4:]
    except KeyError:
        raise HTTPException(status_code=400, detail='Los datos del INE están incompletos')
    SITE_URL = "https://listanominal.ine.mx/scpln/"
    SITE_KEY = "6LdAe1sUAAAAACrdhVFHK5KmZ5TA8ZJ0iWQ6i64b"
    resp = requests.post("http://2captcha.com/in.php", data={
        'key': API_KEY_RECAPTCHA,
        'method': 'userrecaptcha',
        'googlekey': SITE_KEY,
        'pageurl': SITE_URL,
        'json': 1
    }).json()
    if resp["status"] != 1:
        raise HTTPException(status_code=502, detail=f"Error al enviar CAPTCHA: {resp['request']}")
    captcha_id = resp["request"]
    recaptcha_response = None
    for _ in range(20):
        time.sleep(5)
        poll = requests.get("http://2captcha.com/res.php", params={
            "key": API_KEY_RECAPTCHA,
            "action": "get",
            "id": captcha_id,
            "json": 1
        }).json()
        if poll["status"] == 1:
            recaptcha_response = poll["request"]
            break
        elif poll["request"].startswith("ERROR_"):
            raise HTTPException(status_code=502, detail=f"Error de CAPTCHA: {poll['request']}")
    if not recaptcha_response:
        raise HTTPException(status_code=504, detail="Tiempo agotado esperando el CAPTCHA")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(SITE_URL)
            page.fill('input[name="cic"]', CIC)
            page.fill('input[name="idCiudadano"]', ID_CIUDADANO)
            page.evaluate("""
                (token) => {
                    document.getElementById("g-recaptcha-response").style.display = "block";
                    document.getElementById("g-recaptcha-response").value = token;
                }
            """, recaptcha_response)
            time.sleep(2)
            page.locator("#formEFGH").evaluate("form => form.submit()")
            time.sleep(15)
            pdf_bytes = page.pdf(format="A4", print_background=True)
            pdf_file = io.BytesIO(pdf_bytes)
            FILE_NAME = f"user_{user_id}/validacion_ine_{user_id}.pdf"
            s3 = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
            s3.upload_fileobj(
                pdf_file,
                S3_BUCKET_NAME,
                FILE_NAME,
                ExtraArgs={"ContentType": "application/pdf"}
            )
            browser.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error durante la automatización o generación de PDF: {str(e)}")
    try:
        s3_response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=FILE_NAME)
        file_stream = s3_response["Body"]
        response = StreamingResponse(
            file_stream,
            media_type=s3_response.get("ContentType", "application/octet-stream")
        )
        response.headers["Content-Disposition"] = f"attachment; filename=validacion_ine_{user_id}.pdf"
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo recuperar el archivo desde S3: {str(e)}")


@router.get("/validate_curp_playwright")
def get_validate_curp_playwright(user_id: int = None, db: Session = Depends(get_db)):
    db_data_ocr = db.query(models.DataOCR).filter(models.DataOCR.id_user == user_id).first()
    if not db_data_ocr or not db_data_ocr.data_ine:
        raise HTTPException(status_code=404, detail="No se encontró información del usuario")
    try:
        curp = db_data_ocr.data_ine["curp"]
    except KeyError:
        raise HTTPException(status_code=400, detail="La CURP no ha sido encontrada")
    download_dir = f"./descargas_{uuid.uuid4()}"
    os.makedirs(download_dir, exist_ok=True)
    absolute_path = os.path.abspath(download_dir)
    SITE_URL = "https://www.gob.mx/curp/"
    FILE_NAME = f"user_{user_id}/validacion_curp_{user_id}.pdf"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False,  args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.goto(SITE_URL)
            page.fill("#curpinput", curp)
            page.click("#searchButton")
            page.wait_for_selector("#download", timeout=10000)
            with page.expect_download() as download_info:
                page.click("#download")
            download = download_info.value
            downloaded_path = os.path.join(download_dir, "curp.pdf")
            download.save_as(downloaded_path)
            s3 = boto3.client(
            "s3",
            region_name=S3_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
            with open(downloaded_path, "rb") as f:
                s3.upload_fileobj(
                    f,
                    S3_BUCKET_NAME,
                    FILE_NAME,
                    ExtraArgs={"ContentType": "application/pdf"}
                )
            browser.close()
    except Exception as e:
        shutil.rmtree(absolute_path, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Error durante la automatización o descarga del PDF: {str(e)}")
    try:
        s3_response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=FILE_NAME)
        file_stream = s3_response["Body"]
        response = StreamingResponse(
            file_stream,
            media_type=s3_response.get("ContentType", "application/octet-stream")
        )
        response.headers["Content-Disposition"] = f"attachment; filename=validacion_curp_{user_id}.pdf"
        shutil.rmtree(absolute_path, ignore_errors=True)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo recuperar el archivo desde S3: {str(e)}")


app.include_router(router)
