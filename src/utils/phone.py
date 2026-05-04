"""
phone.py — Utilitarios de normalizacao de numeros de telefone.

No Brasil, numeros moveis passaram a exigir o nono digito (9) a partir de 2012.
O WhatsApp e sistemas externos podem enviar o numero com ou sem esse digito,
causando inconsistencias na blocklist e em outras comparacoes.

Exemplos:
    Com 9:    5541998582309  (13 digitos: 55 + DDD 41 + 9 + 98582309)
    Sem 9:    554198582309   (12 digitos: 55 + DDD 41 + 98582309)
"""

import re


def phone_variants(phone: str) -> list[str]:
    """
    Retorna ambas as variantes do numero (com e sem o nono digito brasileiro).

    Util para consultas na blocklist e outras comparacoes onde o numero
    pode estar armazenado em formato diferente do recebido.

    Exemplos:
        phone_variants("5541998582309") -> ["5541998582309", "554198582309"]
        phone_variants("554198582309")  -> ["554198582309", "5541998582309"]
        phone_variants("1234567890")    -> ["1234567890"]  # nao-brasileiro
    """
    digits = re.sub(r"\D", "", phone)
    variants: set[str] = {digits}

    if digits.startswith("55"):
        suffix = digits[2:]  # Remove o codigo do pais

        if len(suffix) == 11 and suffix[2] == "9":
            # 13 digitos: tem o 9 -> gera variante sem o 9
            ddd = suffix[:2]
            number = suffix[3:]  # 8 digitos
            variants.add("55" + ddd + number)

        elif len(suffix) == 10:
            # 12 digitos: sem o 9 -> gera variante com o 9
            ddd = suffix[:2]
            number = suffix[2:]  # 8 digitos
            variants.add("55" + ddd + "9" + number)

    return list(variants)
