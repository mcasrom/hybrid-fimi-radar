#!/usr/bin/env python3
"""Fuente ÚNICA de las bandas de score (evita la deriva entre 6 copias).

`scoring.band_for` sigue siendo la versión config-driven (lee `bands` de
config.yaml); este módulo fija los cortes POR DEFECTO y las etiquetas en
llano, para que verifica/informe/panorama/dashboard/datasets no diverjan.
"""

BANDAS = [(0, 'NORMAL'), (20, 'WATCH'), (40, 'ANOMALOUS'), (60, 'HIGH'),
          (80, 'CRITICAL')]

BAND_ES = {'NORMAL': 'Normal', 'WATCH': 'En observación',
           'ANOMALOUS': 'Amplificación anómala', 'HIGH': 'Amplificación alta',
           'CRITICAL': 'Amplificación muy alta'}


def banda(score):
    """Banda para un score 0-100: la última cuyo límite inferior <= score."""
    out = 'NORMAL'
    for lo, name in BANDAS:
        if (score or 0) >= lo:
            out = name
    return out
