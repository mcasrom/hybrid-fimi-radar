"""Ingesta de datasets locales (CSV / JSONL / JSON / SQLite) → DataFrame normalizado.

Campos mínimos requeridos: timestamp, author.
Todos los demás (text, url, hashtags, mentions, action, source) son opcionales.
El sistema debe funcionar aunque falten la mayoría de campos.
"""
import json
import sqlite3
from pathlib import Path

import pandas as pd


def load(path):
    """Carga cualquier formato soportado y devuelve DataFrame crudo."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")

    if p.suffix == ".csv":
        df = pd.read_csv(p, encoding="utf-8", encoding_errors="ignore")
    elif p.suffix in (".jsonl", ".ndjson"):
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        df = pd.DataFrame(rows)
    elif p.suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        rows = data if isinstance(data, list) else data.get("events", data.get("posts", []))
        df = pd.DataFrame(rows)
    elif p.suffix in (".db", ".sqlite", ".sqlite3"):
        con = sqlite3.connect(p)
        df = pd.read_sql("SELECT * FROM events", con)
        con.close()
    else:
        raise ValueError(f"Formato no soportado: {p.suffix}")

    if df.empty:
        raise ValueError("Dataset vacío")
    return df


def normalize(df):
    """Normaliza un DataFrame crudo al formato Event.

    - timestamp: se normaliza a epoch (int segundos). Acepta epoch int, ISO string,
      o datetime.
    - author: a string. Si falta, se asigna 'anon' (no debería ocurrir, es requerido).
    - text: a string, "" si falta.
    - url: string. hashtags: string "#a #b". mentions: string "@a @b".
    - action: string 'post' por defecto. source: string.
    Añade columna ts (epoch) para los módulos.
    """
    df = df.copy()
    for col in ["author", "text", "url", "hashtags", "mentions", "action", "source"]:
        if col not in df.columns:
            df[col] = ""
    df = df[["timestamp", "author", "text", "url", "hashtags", "mentions", "action", "source"]]

    df["author"] = df["author"].astype(str).str.strip()
    df["text"] = df["text"].fillna("").astype(str)
    df["url"] = df["url"].fillna("").astype(str)
    df["hashtags"] = df["hashtags"].fillna("").astype(str)
    df["mentions"] = df["mentions"].fillna("").astype(str)
    df["action"] = df["action"].fillna("post").astype(str)
    df["source"] = df["source"].fillna("").astype(str)

    ts = df["timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        df["ts"] = ts.astype(int)
    else:
        df["ts"] = pd.to_datetime(ts, utc=True, errors="coerce").astype("int64") // 10**9

    # descartar filas sin autor o sin timestamp válido
    df = df[df["author"].ne("") & df["ts"].notna()]
    df["ts"] = df["ts"].astype(int)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def load_sqlite(db_path):
    """Lee la tabla events de la BD del radar y la normaliza a formato Event.

    El formato Event espera columnas: timestamp, author, text, url, hashtags,
    mentions, action, source. En la BD centralizada el autor no existe como
    columna: se deriva de source (la fuente es el "actor" a nivel de campaña).
    """
    import sqlite3
    con = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT timestamp, source, title, url, text, language FROM events", con)
    con.close()
    if df.empty:
        return df
    df["author"] = df["source"]
    df["text"] = df["text"].fillna("").astype(str)
    df["url"] = df["url"].fillna("").astype(str)
    df["hashtags"] = ""
    df["mentions"] = ""
    df["action"] = "post"
    df["timestamp"] = df["timestamp"].astype(int)
    df["ts"] = df["timestamp"]
    df = df[["ts", "author", "text", "url", "hashtags", "mentions", "action", "source"]]
    df = df[df["ts"].notna()].sort_values("ts").reset_index(drop=True)
    return df
