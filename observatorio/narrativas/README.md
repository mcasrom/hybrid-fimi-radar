# Narrativas · código y muestra

Esta carpeta prepara la codificación **manual** de marcos narrativos.

- `codigo.json`: definiciones, inclusiones y exclusiones por tema.
- `muestra.csv`: 60 publicaciones (15 por tema), con `narrativa` vacío.
- `gen_narrativas.py`: valida códigos, cuenta lo codificado y regenera la página.
- `narrativas.json`: estado y recuentos; no se publican recuentos inventados.
- `index.html`: página pública con el código y el estado.

## Flujo

1. Descargar `muestra.csv`.
2. Rellenar `narrativa` con un código del tema; dejar vacío si no encaja.
3. No cambiar `id`, `topic` ni `titular`.
4. Devolver el CSV; ejecutar:

```bash
python3 observatorio/narrativas/gen_narrativas.py
```

No se usa IA ni reglas de palabras clave para asignar marcos. Una publicación sin marco no es un error.
