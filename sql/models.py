from sqlalchemy import Column, Integer, String, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class DataOCR(Base):
    __tablename__ = "data_ocr"

    id = Column(Integer, primary_key=True, index=True)
    id_user = Column(String, nullable=False, index=True)
    data_ine = Column(JSON, nullable=True)
    data_domicilio = Column(JSON, nullable=True)
    data_constancia = Column(JSON, nullable=True)
    data_ine_reverso = Column(JSON, nullable=True)
