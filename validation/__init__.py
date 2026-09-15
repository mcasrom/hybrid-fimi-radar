"""validation — motor de ablación/consistencia (Fase 0: spike). Solo lectura.

NO usa overall_score para decidir (solo para comparar). NO toca producción.
Lee los eventos reales de `cluster_events` y contrasta 3 dimensiones contra un
modelo nulo (permutación con seed) para medir EXCESO SOBRE AZAR.
"""
