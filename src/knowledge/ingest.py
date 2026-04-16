from pathlib import Path

from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.knowledge.vectorstore import get_vectorstore, _COLLECTION


def _load_docx(path: str) -> str:
    """Extrai texto de um arquivo .docx."""
    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _load_pdf(path: str) -> str:
    """Extrai texto de um arquivo .pdf usando PyPDF2."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        from pypdf import PdfReader  # fallback para versoes mais novas

    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text and text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def _load_file(path: str) -> str:
    """Carrega texto de DOCX ou PDF conforme extensão."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _load_pdf(path)
    return _load_docx(path)


def ingest_text(text: str, source: str = "manual", clear: bool = True) -> int:
    """
    Ingere texto puro na vector store.

    Args:
        text: Conteúdo a ser indexado
        source: Identificador da fonte (usado nos metadados)
        clear: Se True, limpa a coleção antes de reinserir (evita duplicatas)

    Returns:
        Número de chunks inseridos
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(text)

    vs = get_vectorstore()

    if clear:
        try:
            vs.delete_collection()
            vs = get_vectorstore()
        except Exception:
            pass

    vs.add_texts(chunks, metadatas=[{"source": source}] * len(chunks))
    return len(chunks)


def ingest_document(file_path: str, clear: bool = True) -> int:
    """
    Ingere um documento (DOCX ou PDF) na vector store.

    Args:
        file_path: Caminho para o arquivo (.docx ou .pdf)
        clear: Se True, limpa a coleção antes de reinserir (evita duplicatas)

    Returns:
        Número de chunks inseridos
    """
    text = _load_file(file_path)
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(text)

    vs = get_vectorstore()

    if clear:
        try:
            vs.delete_collection()
            vs = get_vectorstore()
        except Exception:
            pass

    vs.add_texts(chunks, metadatas=[{"source": Path(file_path).name}] * len(chunks))
    return len(chunks)
