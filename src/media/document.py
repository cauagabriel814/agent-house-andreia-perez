import base64
import io

from src.services.uazapi import UazapiService
from src.utils.logger import logger

_MAX_CHARS = 8000  # Limite de caracteres para nao estourar o contexto do LLM


async def process_document(
    media_url: str | None,
    mimetype: str | None = None,
    media_base64: str | None = None,
    uazapi_message_id: str | None = None,
    chat_id: str = "",
) -> str:
    """
    Extrai texto de documentos PDF ou DOCX recebidos via WhatsApp.

    Ordem de tentativa para obter os bytes:
      1. base64 inline do webhook
      2. Download via URL direta
      3. Download via API UAZAPI (POST /download/base64) usando messageId

    Pipeline:
        1. Obtem os bytes do documento
        2. Deteccao do tipo (PDF ou DOCX) pelo mimetype
        3. Extracao do texto com PyPDF2 (PDF) ou python-docx (DOCX)
        4. Retorna o texto extraido (limitado a _MAX_CHARS caracteres)
    """
    doc_bytes, resolved_mime = await _get_document_bytes(
        media_base64, media_url, uazapi_message_id, chat_id, mimetype
    )
    if not doc_bytes:
        return "[Documento recebido mas nao foi possivel obter o conteudo]"

    logger.info("DOCUMENT | Bytes obtidos | bytes=%d", len(doc_bytes))

    effective_mime = resolved_mime or mimetype or ""
    mime = effective_mime.lower()
    url_lower = (media_url or "").lower()

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


async def _get_document_bytes(
    media_base64: str | None,
    media_url: str | None,
    uazapi_message_id: str | None,
    chat_id: str,
    mimetype: str | None,
) -> tuple[bytes | None, str | None]:
    """Tenta obter bytes do documento nas tres fontes disponiveis."""

    # 1. Base64 inline no webhook
    if media_base64:
        try:
            logger.info("DOCUMENT | Decodificando base64 inline do webhook")
            return base64.b64decode(media_base64), mimetype
        except Exception as exc:
            logger.warning("DOCUMENT | base64 invalido | erro=%s", exc)

    # 2. URL direta
    if media_url:
        try:
            logger.info("DOCUMENT | Baixando via URL direta | url=%s", media_url[:80])
            uazapi = UazapiService()
            data = await uazapi.download_media(media_url)
            if data:
                return data, mimetype
        except Exception as exc:
            logger.warning("DOCUMENT | Falha no download por URL | erro=%s", exc)

    # 3. API UAZAPI via messageId
    if uazapi_message_id:
        try:
            logger.info("DOCUMENT | Baixando via API UAZAPI | messageId=%s", uazapi_message_id)
            uazapi = UazapiService()
            data, resolved_mime = await uazapi.download_media_by_id(uazapi_message_id, chat_id)
            if data:
                return data, resolved_mime or mimetype
        except Exception as exc:
            logger.warning("DOCUMENT | Falha no download via API | erro=%s", exc)

    logger.warning(
        "DOCUMENT | Todas as fontes falharam | has_base64=%s | has_url=%s | has_msg_id=%s",
        bool(media_base64), bool(media_url), bool(uazapi_message_id),
    )
    return None, None


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
