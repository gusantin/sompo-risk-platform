"""Funções geoespaciais pequenas, sem dependências externas."""

from math import asin, cos, radians, sin, sqrt


def distancia_km(latitude_a, longitude_a, latitude_b, longitude_b):
    """Distância aproximada sobre a Terra pela fórmula de Haversine."""
    raio_terra_km = 6371.0088
    lat_a = radians(latitude_a)
    lat_b = radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = radians(longitude_b - longitude_a)
    termo = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * raio_terra_km * asin(sqrt(termo))


def ponto_no_poligono(longitude, latitude, anel):
    dentro = False
    for i in range(len(anel)):
        x1, y1 = anel[i][:2]
        x2, y2 = anel[(i + 1) % len(anel)][:2]
        if (y1 > latitude) != (y2 > latitude):
            x_intersecao = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude <= x_intersecao:
                dentro = not dentro
    return dentro


def ponto_no_geojson(latitude, longitude, geometria):
    if not geometria:
        return None
    tipo, coordenadas = geometria.get("type"), geometria.get("coordinates")
    if tipo == "Polygon":
        poligonos = [coordenadas]
    elif tipo == "MultiPolygon":
        poligonos = coordenadas
    else:
        raise ValueError("Geometria deve ser Polygon ou MultiPolygon.")
    if not isinstance(poligonos, list):
        raise ValueError("Coordenadas GeoJSON inválidas.")
    for poligono in poligonos:
        if not poligono or not ponto_no_poligono(longitude, latitude, poligono[0]):
            continue
        if not any(ponto_no_poligono(longitude, latitude, buraco) for buraco in poligono[1:]):
            return True
    return False

