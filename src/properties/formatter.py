"""
Formatador de imóveis para WhatsApp — tom natural de corretor.
"""


def _fmt_valor(valor: str) -> str:
    try:
        v = float(valor)
        if v >= 1_000_000:
            m = v / 1_000_000
            return f"R$ {m:,.1f} milhão".replace(".", ",").replace(",0 milhão", " milhão")
        if v >= 1_000:
            return f"R$ {v:,.0f}".replace(",", ".")
        return f"R$ {valor}"
    except (ValueError, TypeError):
        return f"R$ {valor}" if valor else ""


def format_property_whatsapp(prop: dict) -> str:
    """
    Formata um imóvel como mensagem WhatsApp no estilo de um corretor.
    Retorna texto pronto para enviar via UAZAPI.
    """
    tipo = prop.get("tipo", "Imóvel")
    bairro = prop.get("bairro", "")
    endereco = prop.get("endereco", "")
    suites = prop.get("suites", "")
    area_privativa = prop.get("area_privativa", "")
    vagas = prop.get("vagas", "")
    valor = prop.get("valor", "")
    condominio = prop.get("condominio", "")
    diferenciais = prop.get("diferenciais", "")
    empreendimento = prop.get("empreendimento", "")
    construtora = prop.get("construtora", "")
    entrega = prop.get("entrega", "")
    aceita_permuta = prop.get("aceita_permuta", "").strip().lower() == "sim"
    aceita_financiamento = prop.get("aceita_financiamento", "").strip().lower() == "sim"
    fotos_url = prop.get("fotos_url", "")
    tour_360 = prop.get("tour_360", "")
    planta_url = prop.get("planta_url", "")
    video_url = prop.get("video_url", "")
    descricao = prop.get("descricao", "")
    eh_lancamento = prop.get("lancamento", "").strip().lower() == "sim"

    valor_fmt = _fmt_valor(valor)

    lines: list[str] = []

    # Introdução natural
    if eh_lancamento:
        lines.append("Olha esse lançamento incrível que temos! 🚀")
    else:
        lines.append("Separei essa opção que combina com o seu perfil! 🏠")

    lines.append("")

    # Nome do empreendimento e localização
    if empreendimento:
        lines.append(f"*{empreendimento}* — {bairro}")
    else:
        lines.append(f"*{tipo}* — {bairro}")

    if endereco:
        lines.append(f"📍 {endereco}")

    lines.append("")

    # Características em linguagem natural
    partes = []
    if suites:
        s = suites
        partes.append(f"{s} suíte{'s' if int(s) > 1 else ''}" if s.isdigit() else f"{s} suítes")
    if area_privativa:
        partes.append(f"{area_privativa} m²")
    if vagas:
        v2 = vagas
        partes.append(f"{v2} vaga{'s' if v2.isdigit() and int(v2) > 1 else ''}" if v2.isdigit() else f"{v2} vagas")

    if partes:
        lines.append(tipo + " com " + ", ".join(partes))

    # Status
    if eh_lancamento:
        info_extra = []
        if construtora:
            info_extra.append(f"Construtora {construtora}")
        if entrega:
            info_extra.append(f"entrega prevista {entrega}")
        if info_extra:
            lines.append("🏗 " + " | ".join(info_extra))
    else:
        lines.append("✅ Pronto para morar")

    lines.append("")

    # Valor
    if valor_fmt:
        lines.append(f"💰 *{valor_fmt}*")
    if condominio:
        lines.append(f"   Cond. {_fmt_valor(condominio)}/mês")

    # Diferenciais
    if diferenciais:
        lines.append("")
        lines.append(f"✨ {diferenciais}")

    # Descrição curta (sem as observações internas)
    if descricao:
        lines.append("")
        lines.append(descricao)

    # Condições comerciais
    condicoes = []
    if aceita_financiamento:
        condicoes.append("financiamento")
    if aceita_permuta:
        condicoes.append("permuta")
    if condicoes:
        lines.append("")
        lines.append("✅ Aceita " + " e ".join(condicoes))

    # Links
    links = []
    if fotos_url:
        links.append(f"📸 Fotos → {fotos_url}")
    if tour_360:
        links.append(f"🔄 Tour 360° → {tour_360}")
    if planta_url:
        links.append(f"📋 Planta → {planta_url}")
    if video_url:
        links.append(f"▶️ Vídeo → {video_url}")
    if links:
        lines.append("")
        lines.append("\n".join(links))

    return "\n".join(lines)
