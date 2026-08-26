"""Métricas determinísticas de séries temporais."""

import math


def metricas_tendencia(amostras, minimo_amostras=3, estabilidade=0.5):
    valores = [float(v) for v in amostras if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    if len(valores) < minimo_amostras:
        return {"status": "insufficient_data", "direction": "unknown", "samples": len(valores)}
    n = len(valores); xs = list(range(n)); media_x = sum(xs) / n; media = sum(valores) / n
    denominador = sum((x - media_x) ** 2 for x in xs)
    slope = sum((x - media_x) * (y - media) for x, y in zip(xs, valores)) / denominador if denominador else 0
    delta = valores[-1] - valores[0]
    direction = "stable" if abs(delta) <= estabilidade else "rising" if delta > 0 else "falling"
    return {"status": "ok", "direction": direction, "delta": round(delta, 2), "slopePerSample": round(slope, 3),
            "average": round(media, 2), "minimum": min(valores), "maximum": max(valores), "samples": n}

