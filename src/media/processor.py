from src.media.audio import process_audio
from src.media.document import process_document
from src.media.image import process_image
from src.media.spreadsheet import process_spreadsheet
from src.utils.logger import logger

# Tipos que requerem download e processamento de arquivo
_FILE_TYPES = {"audio", "image", "document", "spreadsheet"}

# Tipos que chegam como dados estruturados no payload
_STRUCTURED_TYPES = {"sticker", "location", "contact"}


async def process_media(
    media_type: str,
    media_url: str | None = None,
    mimetype: str | None = None,
    content: dict | None = None,
) -> str:
    """
    Roteia o processamento de midia para o handler correto.

    Args:
        media_type: Tipo da midia (audio, image, document, spreadsheet,
                    sticker, location, contact)
        media_url:  URL do arquivo de midia (necessario para file types)
        mimetype:   MIME type do arquivo (ex: audio/ogg, image/jpeg)
        content:    Dados estruturados para location/contact (do raw_payload)

    Returns:
        String com o conteudo processado/descrito, pronto para o agente.
    """
    logger.info(
        "MEDIA | Iniciando processamento | type=%s | mimetype=%s | has_url=%s",
        media_type,
        mimetype,
        bool(media_url),
    )

    try:
        if media_type == "audio":
            result = await process_audio(media_url, mimetype)

        elif media_type == "image":
            result = await process_image(media_url, mimetype)

        elif media_type == "document":
            result = await process_document(media_url, mimetype)

        elif media_type == "spreadsheet":
            result = await process_spreadsheet(media_url, mimetype)

        elif media_type == "sticker":
            result = "[Lead enviou um sticker/figurinha]"

        elif media_type == "location":
            result = _format_location(content)

        elif media_type == "contact":
            result = _format_contact(content)

        else:
            result = f"[Tipo de midia nao suportado: {media_type}]"

        logger.info(
            "MEDIA | Processamento concluido | type=%s | chars=%d | preview=%s",
            media_type,
            len(result),
            result[:60].replace("\n", " "),
        )
        return result

    except Exception as exc:
        logger.error(
            "MEDIA | Erro no processamento | type=%s | erro=%s",
            media_type,
            exc,
            exc_info=True,
        )
        return f"[Erro ao processar {media_type}: {exc}]"


def _format_location(content: dict | None) -> str:
    """Formata dados de localizacao em texto legivel."""
    if not content:
        return "[Localizacao recebida sem dados]"

    lat = content.get("latitude") or content.get("lat")
    lng = content.get("longitude") or content.get("lng") or content.get("long")
    name = content.get("name", "")
    address = content.get("address", "")

    parts = ["Localizacao compartilhada:"]
    if lat is not None and lng is not None:
        parts.append(f"Coordenadas: {lat}, {lng}")
    if name:
        parts.append(f"Local: {name}")
    if address:
        parts.append(f"Endereco: {address}")

    return " | ".join(parts)


def _format_contact(content: dict | None) -> str:
    """Formata dados de contato (vCard) em texto legivel."""
    if not content:
        return "[Contato recebido sem dados]"

    name = content.get("name", "") or content.get("full_name", "")
    phone = content.get("phone", "") or content.get("number", "")
    email = content.get("email", "")

    parts = ["Contato compartilhado:"]
    if name:
        parts.append(f"Nome: {name}")
    if phone:
        parts.append(f"Telefone: {phone}")
    if email:
        parts.append(f"Email: {email}")

    return " | ".join(parts)
