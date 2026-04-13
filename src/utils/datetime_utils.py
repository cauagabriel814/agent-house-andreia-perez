from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# Cuiaba/MT - UTC-4 (sem horario de verao desde 2019)
_TZ_CUIABA = ZoneInfo("America/Cuiaba")

BUSINESS_HOURS = {
    # weekday(): (inicio, fim)
    0: (time(8, 0), time(18, 0)),   # Segunda
    1: (time(8, 0), time(18, 0)),   # Terca
    2: (time(8, 0), time(18, 0)),   # Quarta
    3: (time(8, 0), time(18, 0)),   # Quinta
    4: (time(8, 0), time(18, 0)),   # Sexta
    5: (time(9, 0), time(13, 0)),   # Sabado
    # Domingo = 6 -> sem horario
}


def next_business_9h() -> datetime:
    """
    Retorna o proximo dia util as 9h (fuso Cuiaba) como datetime naive UTC,
    pronto para armazenamento no banco (TIMESTAMP WITHOUT TIME ZONE).

    Regras:
      - Avanca pelo menos 1 dia a partir de agora
      - Pula domingos (weekday=6) que nao estao em BUSINESS_HOURS
      - Resultado: naive UTC para compatibilidade com scheduled_for
    """
    now = datetime.now(_TZ_CUIABA)
    candidate = (now + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    while candidate.weekday() not in BUSINESS_HOURS:
        candidate += timedelta(days=1)
    return candidate.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def is_business_hours(dt: datetime | None = None) -> bool:
    """Verifica se o horario esta dentro do horario comercial (fuso Cuiaba/MT)."""
    if dt is None:
        dt = datetime.now(_TZ_CUIABA)
    elif dt.tzinfo is None:
        # Se naive, assume UTC e converte para Cuiaba
        dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(_TZ_CUIABA)

    weekday = dt.weekday()
    if weekday not in BUSINESS_HOURS:
        return False

    start, end = BUSINESS_HOURS[weekday]
    current_time = dt.time()
    return start <= current_time <= end
