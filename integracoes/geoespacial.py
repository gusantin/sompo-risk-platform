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

