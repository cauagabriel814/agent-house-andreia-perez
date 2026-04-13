import io

from src.services.uazapi import UazapiService
from src.utils.logger import logger

_MAX_CHARS = 8000  # Limite de caracteres para nao estourar o contexto do LLM


async def process_document(media_url: str, mimetype: str | None = None) -> str:
    """
    Extrai texto de documentos PDF ou DOCX recebidos via WhatsApp.

    Pipeline:
        1. Download do documento via UAZAPI
        2. Deteccao do tipo (PDF ou DOCX) pelo mimetype ou extensao da URL
        3. Extracao do texto com PyPDF2 (PDF) ou python-docx (DOCX)
        4. Retorna o texto extraido (limitado a _MAX_CHARS caracteres)
    """
    if not media_url:
        return "[Documento recebido sem URL de midia]"

    logger.info("DOCUMENT | Iniciando download | url=%s", media_url)
    uazapi = UazapiService()
    doc_bytes = await uazapi.download_media(media_url)

    if not doc_bytes:
        return "[Erro: documento vazio ou inacessivel]"

    logger.info("DOCUMENT | Download concluido | bytes=%d", len(doc_bytes))

    mime = (mimetype or "").lower()
    url_lower = media_url.lower()

    if "pdf" in mime or url_lower.endswith(".pdf"):
        text = _extract_pdf(doc_bytes)
    elif "docx" in mime or "word" in mime or url_lower.endswith(".docx"):
        text = _extract_docx(doc_bytes)
    elif url_lower.endswith(".doc"):
        return "[Formato .doc antigo nao suportado. Por favor, envie em PDF ou DOCX.]"
    else:
        # Tentar PDF primeiro, depois DOCX
        text = _try_all(doc_bytes)

    if not text:
        return "[Documento sem conteudo textual extraivel]"

    # Truncar se muito longo
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + f"\n\n[... texto truncado. Total original: {len(text)} caracteres]"

    logger.info("DOCUMENT | Extracao concluida | chars=%d", len(text))
    return text


def _extract_pdf(data: bytes) -> str:
    """Extrai texto de um PDF usando PyPDF2."""
    import PyPDF2

    reader = PyPDF2.PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                pages.append(f"--- Pagina {i + 1} ---\n{page_text.strip()}")
        except Exception:
            continue

    return "\n\n".join(pages)


def _extract_docx(data: bytes) -> str:
    """Extrai texto de um DOCX usando python-docx."""
    import docx

    doc = docx.Document(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _try_all(data: bytes) -> str:
    """Tenta extrair texto testando todos os formatos suportados."""
    for extractor in (_extract_pdf, _extract_docx):
        try:
            result = extractor(data)
            if result.strip():
                return result
        except Exception:
            continue
    return ""
