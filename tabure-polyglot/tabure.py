#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tabure.py — Puente entre un vault de Obsidian y PolyGlot para la lengua tabure'shi.

Lee las notas del vault (lexemas, fonología, reglas de conjugación y secciones
gramaticales), las valida, y genera los archivos que PolyGlot importa.

Corre con Python 3.8+ y solo la biblioteca estándar. Si tienes PyYAML instalado
lo usa; si no, aplica un lector de frontmatter reducido que cubre el formato
documentado en el README.

Uso rápido:
    python3 tabure.py revisar   --vault ~/Obsidian/Tabure
    python3 tabure.py exportar  --vault ~/Obsidian/Tabure --salida ~/Tabure/polyglot
    python3 tabure.py vigilar   --vault ~/Obsidian/Tabure --salida ~/Tabure/polyglot
    python3 tabure.py inspeccionar --pgd ~/Tabure/Tabure.pgd
    python3 tabure.py importar-cuaderno respaldo.json --vault ~/Obsidian/Tabure
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile

try:
    import yaml as _pyyaml
except Exception:
    _pyyaml = None


# --------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(texto, codigo):
    return "\033[%sm%s\033[0m" % (codigo, texto) if _COLOR else texto


def rojo(t):
    return _c(t, "31")


def ambar(t):
    return _c(t, "33")


def verde(t):
    return _c(t, "32")


def gris(t):
    return _c(t, "90")


def negrita(t):
    return _c(t, "1")


ERROR = "error"
AVISO = "aviso"


class Hallazgo(object):
    """Un problema detectado durante la revisión."""

    def __init__(self, nivel, area, mensaje, origen=None):
        self.nivel = nivel
        self.area = area
        self.mensaje = mensaje
        self.origen = origen

    def linea(self):
        etiqueta = rojo("ERROR") if self.nivel == ERROR else ambar("AVISO")
        cola = gris("  (%s)" % self.origen) if self.origen else ""
        return "  %s  %-12s %s%s" % (etiqueta, self.area, self.mensaje, cola)

    def plano(self):
        cola = " (%s)" % self.origen if self.origen else ""
        return "- **%s** · %s — %s%s" % (self.nivel.upper(), self.area, self.mensaje, cola)


# --------------------------------------------------------------------------
# Lectura de frontmatter
# --------------------------------------------------------------------------

_RE_CLAVE = re.compile(r"^([^:#][^:]*):\s*(.*)$")


def _escalar(bruto):
    """Convierte un valor de frontmatter en str / list / bool."""
    s = bruto.strip()
    if not s:
        return ""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        interior = s[1:-1].strip()
        if not interior:
            return []
        return [_escalar(p) for p in interior.split(",")]
    # Solo true/false se vuelven booleanos: en una lengua "no" o "si" pueden
    # ser glosas legítimas y no deben coercionarse.
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def _bloque(lineas):
    """Interpreta un bloque indentado: lista de escalares o lista de mapas."""
    elementos = []
    actual = None
    for linea in lineas:
        if not linea.strip() or linea.strip().startswith("#"):
            continue
        contenido = linea.strip()
        if contenido.startswith("- "):
            cuerpo = contenido[2:].strip()
            m = _RE_CLAVE.match(cuerpo)
            if m:
                actual = {m.group(1).strip(): _escalar(m.group(2))}
                elementos.append(actual)
            else:
                elementos.append(_escalar(cuerpo))
                actual = None
        elif isinstance(actual, dict):
            m = _RE_CLAVE.match(contenido)
            if m:
                actual[m.group(1).strip()] = _escalar(m.group(2))
    return elementos


def _mini_yaml(texto):
    """Lector reducido de YAML para el frontmatter documentado en el README."""
    raiz = {}
    lineas = texto.split("\n")
    i, n = 0, len(lineas)
    while i < n:
        linea = lineas[i]
        if not linea.strip() or linea.lstrip().startswith("#") or linea[:1] in (" ", "\t"):
            i += 1
            continue
        m = _RE_CLAVE.match(linea)
        if not m:
            i += 1
            continue
        clave, resto = m.group(1).strip(), m.group(2).strip()
        if resto:
            raiz[clave] = _escalar(resto)
            i += 1
            continue
        i += 1
        bloque = []
        while i < n and (not lineas[i].strip() or lineas[i][:1] in (" ", "\t")):
            bloque.append(lineas[i])
            i += 1
        elementos = _bloque(bloque)
        # «clave:» sin nada debajo es un valor vacío, no una lista vacía.
        raiz[clave] = elementos if elementos else ""
    return raiz


def separar_frontmatter(texto):
    """Devuelve (dict_frontmatter, cuerpo_markdown)."""
    if not texto.startswith("---"):
        return {}, texto
    partes = texto.split("\n")
    if partes[0].strip() != "---":
        return {}, texto
    for idx in range(1, len(partes)):
        if partes[idx].strip() in ("---", "..."):
            crudo = "\n".join(partes[1:idx])
            cuerpo = "\n".join(partes[idx + 1:])
            if _pyyaml is not None:
                try:
                    datos = _pyyaml.safe_load(crudo) or {}
                    if isinstance(datos, dict):
                        return datos, cuerpo
                except Exception:
                    pass
            return _mini_yaml(crudo), cuerpo
    return {}, texto


def como_lista(valor):
    if valor is None or valor == "":
        return []
    if isinstance(valor, list):
        return [str(v).strip() for v in valor if str(v).strip()]
    return [p.strip() for p in str(valor).split(",") if p.strip()]


def como_texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor).strip()


# --------------------------------------------------------------------------
# Carga del vault
# --------------------------------------------------------------------------

# Sinónimos aceptados para cada campo, para que puedas escribir en la forma que
# te resulte natural sin romper la herramienta.
ALIAS = {
    "palabra": ["palabra", "lexema", "headword", "termino", "término"],
    "ipa": ["ipa", "fonemico", "fonémico", "pronunciacion", "pronunciación"],
    "romanizacion": ["romanizacion", "romanización", "roman", "transcripcion", "transcripción"],
    "pos": ["pos", "categoria", "categoría", "clase", "tipo_gramatical"],
    "glosa": ["glosa", "definicion", "definición", "significado", "gloss"],
    "etimologia": ["etimologia", "etimología", "origen"],
    "estado": ["estado", "status"],
    "grafema": ["grafema", "caracter", "carácter", "char", "letra"],
    "reemplazo": ["reemplazo", "replacement", "sustitucion", "sustitución"],
    "etiqueta": ["etiqueta", "nombre", "label", "titulo", "título"],
    "buscar": ["buscar", "regex", "patron", "patrón", "find"],
    "reemplazar": ["reemplazar", "replace", "salida"],
    "flags": ["flags", "banderas", "modificadores"],
    "pruebas": ["pruebas", "tests", "casos"],
    "dimensiones": ["dimensiones", "dims", "rasgos", "features"],
    "orden": ["orden", "seccion", "sección", "numero", "número", "order"],
    "notas": ["notas", "nota", "comentario", "comentarios"],
}


def campo(datos, canonico, defecto=""):
    for nombre in ALIAS.get(canonico, [canonico]):
        for clave in datos:
            if str(clave).strip().lower() == nombre:
                return datos[clave]
    return defecto


def _tipo_nota(datos, ruta_rel):
    """Determina qué representa una nota: por 'tipo:' o por su carpeta."""
    declarado = como_texto(campo(datos, "tipo") or datos.get("type", "")).lower()
    mapa = {
        "lexema": "lexema", "palabra": "lexema", "entrada": "lexema",
        "fonologia": "fonologia", "fonología": "fonologia", "fonema": "fonologia",
        "regla": "regla", "conjugacion": "regla", "conjugación": "regla",
        "gramatica": "gramatica", "gramática": "gramatica", "grammar": "gramatica",
        "pos": "pos", "categoria": "pos", "categoría": "pos",
    }
    if declarado in mapa:
        return mapa[declarado]
    carpeta = ruta_rel.replace("\\", "/").split("/")[0].lower()
    por_carpeta = {
        "lexicon": "lexema", "lexico": "lexema", "léxico": "lexema",
        "conjugaciones": "regla", "reglas": "regla",
        "gramatica": "gramatica", "gramática": "gramatica",
        "fonologia": "fonologia", "fonología": "fonologia",
        "categorias": "pos", "categorías": "pos",
    }
    return por_carpeta.get(carpeta)


def _tabla_markdown(cuerpo):
    """Extrae la primera tabla markdown del cuerpo como lista de dicts."""
    filas = []
    encabezado = None
    for linea in cuerpo.split("\n"):
        t = linea.strip()
        if not t.startswith("|"):
            if encabezado:
                break
            continue
        celdas = [c.strip() for c in t.strip("|").split("|")]
        if encabezado is None:
            encabezado = [c.lower() for c in celdas]
            continue
        if all(set(c) <= set("-: ") for c in celdas):
            continue
        if len(celdas) < len(encabezado):
            celdas += [""] * (len(encabezado) - len(celdas))
        filas.append(dict(zip(encabezado, celdas)))
    return filas


def _columna(fila, *nombres):
    for n in nombres:
        for clave in fila:
            if clave.strip().lower() == n:
                return fila[clave].strip()
    return ""


def cargar_vault(ruta_vault):
    """Recorre el vault y devuelve el modelo de datos + errores de lectura."""
    modelo = {"lexemas": [], "fonologia": [], "reglas": [], "gramatica": [], "pos": []}
    hallazgos = []

    if not os.path.isdir(ruta_vault):
        hallazgos.append(Hallazgo(ERROR, "vault", "No existe la carpeta %s" % ruta_vault))
        return modelo, hallazgos

    for base, dirs, archivos in os.walk(ruta_vault):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for nombre in sorted(archivos):
            if not nombre.lower().endswith(".md"):
                continue
            ruta = os.path.join(base, nombre)
            rel = os.path.relpath(ruta, ruta_vault)
            try:
                with io.open(ruta, "r", encoding="utf-8") as fh:
                    texto = fh.read()
            except (IOError, OSError, UnicodeDecodeError) as exc:
                hallazgos.append(Hallazgo(ERROR, "vault", "No se pudo leer: %s" % exc, rel))
                continue

            datos, cuerpo = separar_frontmatter(texto)
            tipo = _tipo_nota(datos, rel)
            if tipo is None:
                continue

            if tipo == "lexema":
                palabra = como_texto(campo(datos, "palabra")) or os.path.splitext(nombre)[0]
                modelo["lexemas"].append({
                    "palabra": palabra,
                    "ipa": como_texto(campo(datos, "ipa")),
                    "romanizacion": como_texto(campo(datos, "romanizacion")),
                    "pos": como_texto(campo(datos, "pos")),
                    "glosa": como_texto(campo(datos, "glosa")),
                    "etimologia": como_texto(campo(datos, "etimologia")),
                    "estado": como_texto(campo(datos, "estado")) or "borrador",
                    "notas": cuerpo.strip(),
                    "origen": rel,
                })

            elif tipo == "regla":
                pruebas = []
                for p in campo(datos, "pruebas", []) or []:
                    if isinstance(p, dict):
                        entrada = como_texto(p.get("entrada", p.get("input", "")))
                        esperado = como_texto(p.get("esperado", p.get("expected", "")))
                        if entrada:
                            pruebas.append({"entrada": entrada, "esperado": esperado})
                modelo["reglas"].append({
                    "etiqueta": como_texto(campo(datos, "etiqueta")) or os.path.splitext(nombre)[0],
                    "pos": como_texto(campo(datos, "pos")),
                    "buscar": como_texto(campo(datos, "buscar")),
                    "reemplazar": como_texto(campo(datos, "reemplazar")),
                    "flags": como_texto(campo(datos, "flags")),
                    "pruebas": pruebas,
                    "origen": rel,
                })

            elif tipo == "pos":
                modelo["pos"].append({
                    "nombre": como_texto(campo(datos, "etiqueta")) or os.path.splitext(nombre)[0],
                    "dimensiones": como_lista(campo(datos, "dimensiones")),
                    "notas": como_texto(campo(datos, "notas")) or cuerpo.strip(),
                    "origen": rel,
                })

            elif tipo == "gramatica":
                orden_bruto = como_texto(campo(datos, "orden"))
                try:
                    orden = int(orden_bruto)
                except (TypeError, ValueError):
                    m = re.match(r"^(\d+)", nombre)
                    orden = int(m.group(1)) if m else 999
                modelo["gramatica"].append({
                    "titulo": como_texto(campo(datos, "etiqueta")) or os.path.splitext(nombre)[0],
                    "orden": orden,
                    "contenido": cuerpo.strip(),
                    "origen": rel,
                })

            elif tipo == "fonologia":
                filas = _tabla_markdown(cuerpo)
                if filas:
                    for fila in filas:
                        grafema = _columna(fila, "grafema", "carácter", "caracter", "letra", "char")
                        if not grafema:
                            continue
                        modelo["fonologia"].append({
                            "grafema": grafema,
                            "ipa": _columna(fila, "ipa", "fonema", "fonémico", "fonemico"),
                            "romanizacion": _columna(fila, "romanización", "romanizacion", "roman"),
                            "reemplazo": _columna(fila, "reemplazo", "replacement", "sustitución"),
                            "notas": _columna(fila, "notas", "nota", "comentario"),
                            "origen": rel,
                        })
                else:
                    grafema = como_texto(campo(datos, "grafema"))
                    if grafema:
                        modelo["fonologia"].append({
                            "grafema": grafema,
                            "ipa": como_texto(campo(datos, "ipa")),
                            "romanizacion": como_texto(campo(datos, "romanizacion")),
                            "reemplazo": como_texto(campo(datos, "reemplazo")),
                            "notas": como_texto(campo(datos, "notas")),
                            "origen": rel,
                        })

    modelo["gramatica"].sort(key=lambda s: (s["orden"], s["titulo"]))
    return modelo, hallazgos


# --------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------

def tokenizar(palabra, grafemas, ignorar=" -"):
    """Segmenta una palabra con los grafemas declarados (coincidencia más larga)."""
    orden = sorted([g for g in grafemas if g], key=len, reverse=True)
    tokens, desconocidos = [], []
    i = 0
    while i < len(palabra):
        if palabra[i] in ignorar:
            i += 1
            continue
        for g in orden:
            if palabra.startswith(g, i):
                tokens.append(g)
                i += len(g)
                break
        else:
            desconocidos.append(palabra[i])
            tokens.append(palabra[i])
            i += 1
    return tokens, desconocidos


def aplicar_regla(regla, entrada):
    """Aplica la regla regex. Devuelve (ok, resultado_o_mensaje_de_error)."""
    banderas = 0
    texto_flags = (regla.get("flags") or "").lower()
    if "i" in texto_flags:
        banderas |= re.IGNORECASE
    if "m" in texto_flags:
        banderas |= re.MULTILINE
    try:
        patron = re.compile(regla["buscar"], banderas)
    except re.error as exc:
        return False, "regex inválida: %s" % exc
    cuenta = 0 if "g" in texto_flags else 1
    try:
        return True, patron.sub(regla.get("reemplazar", ""), entrada, count=cuenta)
    except re.error as exc:
        return False, "reemplazo inválido: %s" % exc


def revisar(modelo, ignorar=" -"):
    """Corre todas las validaciones y devuelve la lista de hallazgos."""
    h = []

    # ---- Fonología -------------------------------------------------------
    vistos_grafema, vistos_roman = {}, {}
    for f in modelo["fonologia"]:
        g = f["grafema"]
        if g in vistos_grafema:
            h.append(Hallazgo(ERROR, "fonología",
                              "Grafema duplicado «%s» (ya definido en %s)" % (g, vistos_grafema[g]),
                              f["origen"]))
        else:
            vistos_grafema[g] = f["origen"]

        if not f["ipa"]:
            h.append(Hallazgo(AVISO, "fonología",
                              "«%s» no tiene fonema IPA asignado" % g, f["origen"]))

        r = f["romanizacion"]
        if r:
            if r in vistos_roman and vistos_roman[r] != g:
                h.append(Hallazgo(ERROR, "fonología",
                                  "Romanización ambigua «%s»: la usan «%s» y «%s»"
                                  % (r, vistos_roman[r], g), f["origen"]))
            else:
                vistos_roman[r] = g

    # ---- Teclas de sustitución -------------------------------------------
    # PolyGlot solo admite UN carácter como entrada de sustitución, así que
    # cada grafema no tecleable necesita una tecla propia y sin choques.
    inventario = set(f["grafema"] for f in modelo["fonologia"])
    vistas_tecla = {}
    for f in modelo["fonologia"]:
        g, tecla = f["grafema"], f["reemplazo"]
        if not tecla:
            if any(ord(c) > 126 for c in g):
                h.append(Hallazgo(AVISO, "teclas",
                                  "«%s» no se teclea directamente y no tiene tecla asignada" % g,
                                  f["origen"]))
            continue

        if len(tecla) > 1:
            h.append(Hallazgo(ERROR, "teclas",
                              "La tecla de «%s» es «%s»: PolyGlot solo admite un carácter de entrada"
                              % (g, tecla), f["origen"]))

        if tecla in vistas_tecla:
            h.append(Hallazgo(ERROR, "teclas",
                              "Tecla repetida «%s»: la usan «%s» y «%s»"
                              % (tecla, vistas_tecla[tecla], g), f["origen"]))
        else:
            vistas_tecla[tecla] = g

        if tecla in inventario:
            h.append(Hallazgo(ERROR, "teclas",
                              "La tecla «%s» es también un grafema de la lengua: se sustituiría sola" % tecla,
                              f["origen"]))

    for tecla, duenio in sorted(vistas_tecla.items()):
        afectadas = [l["palabra"] for l in modelo["lexemas"] if tecla in l["palabra"]]
        if afectadas:
            muestra = ", ".join(afectadas[:3]) + ("…" if len(afectadas) > 3 else "")
            h.append(Hallazgo(ERROR, "teclas",
                              "La tecla «%s» (de «%s») aparece dentro de palabras del léxico (%s): "
                              "al teclearlas se sustituiría" % (tecla, duenio, muestra)))

    # ---- Cobertura: caracteres usados vs. inventario ---------------------
    grafemas = [f["grafema"] for f in modelo["fonologia"]]
    if grafemas:
        faltantes = {}
        usados = set()
        for lex in modelo["lexemas"]:
            tokens, desconocidos = tokenizar(lex["palabra"], grafemas, ignorar)
            usados.update(tokens)
            for d in desconocidos:
                faltantes.setdefault(d, []).append(lex["palabra"])
        for caracter, palabras in sorted(faltantes.items()):
            muestra = ", ".join(palabras[:4]) + ("…" if len(palabras) > 4 else "")
            nombre_uni = ""
            try:
                nombre_uni = " [%s]" % unicodedata.name(caracter)
            except ValueError:
                pass
            h.append(Hallazgo(ERROR, "cobertura",
                              "El carácter «%s»%s aparece en el léxico pero no está en Phonology (%s)"
                              % (caracter, nombre_uni, muestra)))
        for g in grafemas:
            if g not in usados and modelo["lexemas"]:
                h.append(Hallazgo(AVISO, "cobertura",
                                  "El grafema «%s» está declarado pero ningún lexema lo usa" % g))
    elif modelo["lexemas"]:
        h.append(Hallazgo(AVISO, "cobertura",
                          "No hay inventario fonológico: no se puede verificar la cobertura de caracteres"))

    # ---- Parts of Speech -------------------------------------------------
    declaradas = set(p["nombre"].lower() for p in modelo["pos"])
    usadas = {}
    for lex in modelo["lexemas"]:
        if lex["pos"]:
            usadas.setdefault(lex["pos"].lower(), lex["pos"])
        else:
            h.append(Hallazgo(AVISO, "pos",
                              "«%s» no tiene Part of Speech asignado" % lex["palabra"], lex["origen"]))
    if declaradas:
        for clave, original in sorted(usadas.items()):
            if clave not in declaradas:
                h.append(Hallazgo(ERROR, "pos",
                                  "El léxico usa la categoría «%s» pero no está declarada" % original))
        for p in modelo["pos"]:
            if p["nombre"].lower() not in usadas:
                h.append(Hallazgo(AVISO, "pos",
                                  "La categoría «%s» no tiene ningún lexema" % p["nombre"], p["origen"]))
            if not p["dimensiones"]:
                h.append(Hallazgo(AVISO, "pos",
                                  "«%s» no declara dimensiones de conjugación" % p["nombre"], p["origen"]))

    # ---- Reglas de conjugación ------------------------------------------
    for r in modelo["reglas"]:
        if not r["buscar"]:
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s» no tiene patrón de búsqueda" % r["etiqueta"], r["origen"]))
            continue

        ok, _ = aplicar_regla(r, "prueba")
        if not ok:
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s»: %s" % (r["etiqueta"], _), r["origen"]))
            continue

        if not r["buscar"].startswith("^") and not r["buscar"].endswith("$"):
            h.append(Hallazgo(AVISO, "conjugación",
                              "«%s» no está anclada (sin ^ ni $): puede alterar el interior de la palabra"
                              % r["etiqueta"], r["origen"]))

        if r["pos"] and declaradas and r["pos"].lower() not in declaradas:
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s» apunta a la categoría «%s», que no está declarada"
                              % (r["etiqueta"], r["pos"]), r["origen"]))

        if not r["pruebas"]:
            h.append(Hallazgo(AVISO, "conjugación",
                              "«%s» no tiene casos de prueba: no se puede verificar" % r["etiqueta"],
                              r["origen"]))
        for prueba in r["pruebas"]:
            ok, salida = aplicar_regla(r, prueba["entrada"])
            if not ok:
                h.append(Hallazgo(ERROR, "conjugación",
                                  "«%s»: %s" % (r["etiqueta"], salida), r["origen"]))
            elif salida != prueba["esperado"]:
                h.append(Hallazgo(ERROR, "conjugación",
                                  "«%s»: %s → %s, se esperaba %s"
                                  % (r["etiqueta"], prueba["entrada"], salida, prueba["esperado"]),
                                  r["origen"]))

        # Regla muerta: no cambia ningún lexema de su categoría.
        candidatos = [l for l in modelo["lexemas"]
                      if not r["pos"] or l["pos"].lower() == r["pos"].lower()]
        if candidatos:
            toco_algo = False
            for lex in candidatos:
                ok, salida = aplicar_regla(r, lex["palabra"])
                if ok and salida != lex["palabra"]:
                    toco_algo = True
                    break
            if not toco_algo:
                h.append(Hallazgo(AVISO, "conjugación",
                                  "«%s» no modifica ningún lexema existente de su categoría"
                                  % r["etiqueta"], r["origen"]))

    # ---- Gramática -------------------------------------------------------
    ordenes = {}
    for s in modelo["gramatica"]:
        if not s["contenido"]:
            h.append(Hallazgo(AVISO, "gramática",
                              "La sección «%s» está vacía" % s["titulo"], s["origen"]))
        if s["orden"] in ordenes and s["orden"] != 999:
            h.append(Hallazgo(AVISO, "gramática",
                              "Orden %s repetido: «%s» y «%s»"
                              % (s["orden"], ordenes[s["orden"]], s["titulo"]), s["origen"]))
        else:
            ordenes[s["orden"]] = s["titulo"]

    return h


# --------------------------------------------------------------------------
# Exportación
# --------------------------------------------------------------------------

def escribir_csv(ruta, encabezados, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(encabezados)
        for fila in filas:
            escritor.writerow(fila)


def exportar(modelo, hallazgos, salida):
    """Genera los archivos para PolyGlot. Devuelve la lista de rutas escritas."""
    if not os.path.isdir(salida):
        os.makedirs(salida)
    escritos = []

    ruta = os.path.join(salida, "lexicon.csv")
    escribir_csv(ruta,
                 ["Glosa", "Palabra", "Categoria", "Pronunciacion", "Romanizacion", "Etimologia", "Estado"],
                 [[l["glosa"], l["palabra"], l["pos"], l["ipa"], l["romanizacion"],
                   l["etimologia"], l["estado"]] for l in modelo["lexemas"]])
    escritos.append(ruta)

    ruta = os.path.join(salida, "fonologia.csv")
    escribir_csv(ruta,
                 ["Grafema", "IPA", "Romanizacion", "Reemplazo", "Notas"],
                 [[f["grafema"], f["ipa"], f["romanizacion"], f["reemplazo"], f["notas"]]
                  for f in modelo["fonologia"]])
    escritos.append(ruta)

    ruta = os.path.join(salida, "conjugaciones.csv")
    escribir_csv(ruta,
                 ["Etiqueta", "Categoria", "Buscar", "Reemplazar", "Flags"],
                 [[r["etiqueta"], r["pos"], r["buscar"], r["reemplazar"], r["flags"]]
                  for r in modelo["reglas"]])
    escritos.append(ruta)

    ruta = os.path.join(salida, "gramatica.md")
    piezas = ["# Gramática de tabure'shi", ""]
    for s in modelo["gramatica"]:
        piezas.append("## %s" % s["titulo"])
        piezas.append("")
        piezas.append(s["contenido"] or "_Sin contenido._")
        piezas.append("")
    with io.open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(piezas))
    escritos.append(ruta)

    ruta = os.path.join(salida, "informe.md")
    errores = [x for x in hallazgos if x.nivel == ERROR]
    avisos = [x for x in hallazgos if x.nivel == AVISO]
    piezas = [
        "# Informe de revisión — tabure'shi",
        "",
        "_Generado el %s_" % time.strftime("%Y-%m-%d %H:%M"),
        "",
        "| Área | Cantidad |",
        "|---|---|",
        "| Lexemas | %d |" % len(modelo["lexemas"]),
        "| Grafemas | %d |" % len(modelo["fonologia"]),
        "| Categorías | %d |" % len(modelo["pos"]),
        "| Reglas de conjugación | %d |" % len(modelo["reglas"]),
        "| Secciones de gramática | %d |" % len(modelo["gramatica"]),
        "| Errores | %d |" % len(errores),
        "| Avisos | %d |" % len(avisos),
        "",
    ]
    if errores:
        piezas += ["## Errores", ""] + [x.plano() for x in errores] + [""]
    if avisos:
        piezas += ["## Avisos", ""] + [x.plano() for x in avisos] + [""]
    if not hallazgos:
        piezas += ["Sin hallazgos: todo consistente.", ""]
    with io.open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(piezas))
    escritos.append(ruta)

    return escritos


# --------------------------------------------------------------------------
# Extracción del .pgd de PolyGlot (solo lectura)
# --------------------------------------------------------------------------
#
# Esquema verificado contra PolyGlot 3.6.1. Los nombres de etiqueta salen de
# `inspeccionar`; si tu versión difiere, vuelve a correrlo y compara.

_RE_ETIQUETAS = re.compile(r"<[^>]+>")
_ENTIDADES = [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
              ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]


def _texto_plano(bruto):
    """Las notas de PolyGlot vienen envueltas en HTML; deja solo el texto."""
    if not bruto:
        return ""
    limpio = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", bruto)
    limpio = re.sub(r"(?i)<br\s*/?>", "\n", limpio)
    limpio = re.sub(r"(?i)</p\s*>", "\n", limpio)
    limpio = _RE_ETIQUETAS.sub("", limpio)
    for entidad, valor in _ENTIDADES:
        limpio = limpio.replace(entidad, valor)
    limpio = re.sub(r"[ \t]+", " ", limpio)
    limpio = re.sub(r"\n\s*\n\s*\n+", "\n\n", limpio)
    return limpio.strip()


def _sin_barras(texto):
    """PolyGlot guarda los fonemas como /b/; aquí interesa la b."""
    return (texto or "").replace("/", "").strip()


def _hijo(nodo, etiqueta, defecto=""):
    hijo = nodo.find(etiqueta)
    return (hijo.text or defecto) if hijo is not None and hijo.text is not None else defecto


def _abrir_xml(ruta_pgd):
    """Devuelve la raíz del PGDictionary.xml, sin modificar el archivo."""
    import xml.etree.ElementTree as ET
    if zipfile.is_zipfile(ruta_pgd):
        with zipfile.ZipFile(ruta_pgd) as z:
            candidatos = [n for n in z.namelist()
                          if n.lower().endswith(".xml") and not n.startswith("reversion/")]
            if not candidatos:
                raise ValueError("El .pgd no contiene ningún XML principal")
            crudo = z.read(candidatos[0])
    else:
        with open(ruta_pgd, "rb") as fh:
            crudo = fh.read()
    return ET.fromstring(crudo)


def extraer_pgd(ruta_pgd):
    """Convierte el contenido del .pgd al formato de paquete del cuaderno."""
    raiz = _abrir_xml(ruta_pgd)
    paquete = {}
    avisos = []

    # ---- Categorías gramaticales, y el mapa id -> nombre para el léxico ----
    nombre_pos = {}
    lista_pos = []
    for nodo in raiz.findall("./partsOfSpeech/partOfSpeechNode"):
        pos_id = _hijo(nodo, "partOfSpeechId")
        nombre = _hijo(nodo, "partOfSpeechName")
        if not nombre:
            continue
        nombre_pos[pos_id] = nombre
        lista_pos.append({"name": nombre, "dims": [],
                          "notes": _texto_plano(_hijo(nodo, "partOfSpeechNotes")),
                          "status": "draft"})

    # Las dimensiones viven en declensionNode, enlazadas por declensionRelatedId.
    for nodo in raiz.findall("./declensionCollection/declensionNode"):
        rel = _hijo(nodo, "declensionRelatedId")
        dims = [_hijo(d, "dimensionName") for d in nodo.findall("./dimensionNode")]
        dims = [d for d in dims if d]
        destino = nombre_pos.get(rel)
        if destino and dims:
            for p in lista_pos:
                if p["name"] == destino:
                    for d in dims:
                        if d not in p["dims"]:
                            p["dims"].append(d)
    if lista_pos:
        paquete["pos"] = lista_pos

    # ---- Fonología: pronunciación + romanización + teclas ------------------
    # proGuide da grafema -> fonema; romGuide da grafema -> romanización;
    # langPropCharRep da tecla -> grafema (ojo, en ese sentido).
    romanizacion = {}
    for nodo in raiz.findall("./romGuide/romGuideNode"):
        base = _sin_barras(_hijo(nodo, "romGuideBase"))
        if base:
            romanizacion[base] = _hijo(nodo, "romGuidePhon")

    tecla_de = {}
    for nodo in raiz.findall("./languageProperties/langPropCharRep/langPropCharRepNode"):
        tecla = _hijo(nodo, "langPropCharRepCharacter")
        grafema = _hijo(nodo, "langPropCharRepValue")
        if grafema:
            tecla_de[grafema] = tecla

    fonologia, vistos = [], set()
    for nodo in raiz.findall("./pronunciationCollection/proGuide"):
        base = _hijo(nodo, "proGuideBase")
        if not base or base in vistos:
            continue
        vistos.add(base)
        fonologia.append({
            "char": base,
            "ipa": _sin_barras(_hijo(nodo, "proGuidePhon")),
            "roman": romanizacion.get(base, ""),
            "replacement": tecla_de.get(base, ""),
            "notes": ""
        })
    # Grafemas que solo aparecen en las sustituciones de teclado.
    for grafema, tecla in tecla_de.items():
        if grafema not in vistos:
            vistos.add(grafema)
            fonologia.append({"char": grafema, "ipa": "",
                              "roman": romanizacion.get(grafema, ""),
                              "replacement": tecla, "notes": ""})
    if fonologia:
        paquete["phonology"] = fonologia

    sin_pareja = [b for b in romanizacion if b not in vistos]
    if sin_pareja:
        avisos.append("%d regla(s) de romanización no casan con ningún grafema del "
                      "guion de pronunciación: %s" % (len(sin_pareja), " ".join(sorted(sin_pareja)[:8])))

    # ---- Léxico ------------------------------------------------------------
    lexico = []
    for nodo in raiz.findall("./lexicon/word"):
        palabra = _hijo(nodo, "conWord")
        if not palabra:
            continue
        lexico.append({
            "headword": palabra,
            "ipa": _sin_barras(_hijo(nodo, "pronunciation")),
            "roman": "",
            "pos": nombre_pos.get(_hijo(nodo, "wordPosId"), ""),
            "gloss": _hijo(nodo, "localWord"),
            "etymology": _texto_plano(_hijo(nodo, "wordEtymologyNotes")),
            "status": "verified"
        })
    if lexico:
        paquete["lexicon"] = lexico

    # ---- Reglas de conjugación --------------------------------------------
    reglas = []
    for nodo in raiz.findall("./declensionCollection/decGenRule"):
        etiqueta = _hijo(nodo, "decGenRuleName")
        pos = nombre_pos.get(_hijo(nodo, "decGenRuleTypeId"), "")
        transformaciones = nodo.findall("./decGenTrans")
        for i, trans in enumerate(transformaciones, start=1):
            buscar = _hijo(trans, "decGenTransRegex")
            if not buscar:
                continue
            sufijo = "" if len(transformaciones) == 1 else " (%d)" % i
            reglas.append({
                "label": (etiqueta or "Regla sin nombre") + sufijo,
                "pos": pos,
                "find": buscar,
                "replace": _hijo(trans, "decGenTransReplace"),
                "flags": "",
                "tests": []
            })
    if reglas:
        paquete["rules"] = reglas

    # ---- Gramática ---------------------------------------------------------
    gramatica = []
    for capitulo in raiz.findall("./grammarCollection/grammarChapterNode"):
        nombre_cap = _hijo(capitulo, "grammarChapterName")
        for seccion in capitulo.findall("./grammarSectionsList/grammarSectionNode"):
            titulo = _hijo(seccion, "grammarSectionName") or nombre_cap
            gramatica.append({
                "title": titulo,
                "content": _texto_plano(_hijo(seccion, "grammarSectionText"))
            })
    if gramatica:
        paquete["grammar"] = gramatica

    return paquete, avisos


def cmd_extraer(args):
    try:
        paquete, avisos = extraer_pgd(args.pgd)
    except (IOError, OSError, ValueError) as exc:
        print(rojo("No se pudo leer el .pgd: %s" % exc))
        return 1
    except Exception as exc:                      # XML corrupto o esquema distinto
        print(rojo("No se pudo interpretar el .pgd: %s" % exc))
        print(gris("Corre `inspeccionar` sobre el mismo archivo y comparte la salida."))
        return 1

    # Aceptar tanto una carpeta como un archivo: si apuntas a una carpeta, se
    # le pone el nombre por defecto en vez de fallar.
    destino = os.path.expanduser(args.salida)
    if os.path.isdir(destino) or destino.endswith(("/", os.sep)):
        destino = os.path.join(destino, "paquete.json")

    carpeta = os.path.dirname(os.path.abspath(destino))
    if not os.path.isdir(carpeta):
        print(rojo("No existe la carpeta %s" % carpeta))
        print(gris("Créala primero, o arrastra la carpeta desde el Finder a la Terminal "
                   "para ver su ruta exacta."))
        return 1

    texto = json.dumps(paquete, ensure_ascii=False, indent=2)
    try:
        with io.open(destino, "w", encoding="utf-8") as fh:
            fh.write(texto)
    except (IOError, OSError) as exc:
        print(rojo("No se pudo escribir en %s: %s" % (destino, exc)))
        return 1
    args.salida = destino

    print(negrita("\nExtraído de %s" % os.path.basename(args.pgd)))
    for clave in ("phonology", "lexicon", "pos", "rules", "grammar"):
        if clave in paquete:
            print("  %-11s %d" % (clave, len(paquete[clave])))
    for a in avisos:
        print(ambar("  AVISO  ") + a)
    print("")
    print(verde("Guardado en %s" % os.path.abspath(args.salida)))
    print(gris("Ábrelo, copia todo el contenido y pégalo en el cuaderno → "
               "Copia de seguridad → Traer novedades → Actualizar."))
    print(gris("El .pgd no se ha modificado."))
    return 0


# --------------------------------------------------------------------------
# Inspección del archivo .pgd de PolyGlot
# --------------------------------------------------------------------------

def inspeccionar_pgd(ruta_pgd, destino=None):
    """Lee (sin modificar) un .pgd y describe su estructura XML real."""
    import xml.etree.ElementTree as ET

    if not os.path.isfile(ruta_pgd):
        print(rojo("No existe el archivo: %s" % ruta_pgd))
        return 1

    lineas = ["# Estructura de %s" % os.path.basename(ruta_pgd), ""]
    xml_crudo = None

    if zipfile.is_zipfile(ruta_pgd):
        with zipfile.ZipFile(ruta_pgd) as z:
            nombres = z.namelist()
            lineas.append("Contenedor ZIP con %d entrada(s):" % len(nombres))
            lineas.append("")
            for n in nombres:
                info = z.getinfo(n)
                lineas.append("- `%s` — %d bytes" % (n, info.file_size))
            lineas.append("")
            candidatos = [n for n in nombres if n.lower().endswith(".xml")]
            if candidatos:
                xml_crudo = z.read(candidatos[0])
                lineas.append("XML principal: `%s`" % candidatos[0])
                lineas.append("")
    else:
        lineas.append("Archivo XML plano (sin contenedor ZIP).")
        lineas.append("")
        with open(ruta_pgd, "rb") as fh:
            xml_crudo = fh.read()

    if xml_crudo:
        try:
            raiz = ET.fromstring(xml_crudo)
        except ET.ParseError as exc:
            lineas.append("No se pudo interpretar el XML: %s" % exc)
        else:
            conteo, muestras = {}, {}

            def recorrer(nodo, camino):
                ruta = camino + "/" + nodo.tag
                conteo[ruta] = conteo.get(ruta, 0) + 1
                texto = (nodo.text or "").strip()
                if texto and ruta not in muestras:
                    muestras[ruta] = texto[:60]
                for hijo in nodo:
                    recorrer(hijo, ruta)

            recorrer(raiz, "")
            lineas.append("## Árbol de etiquetas")
            lineas.append("")
            lineas.append("| Ruta | Veces | Ejemplo de contenido |")
            lineas.append("|---|---|---|")
            for ruta in sorted(conteo):
                ejemplo = muestras.get(ruta, "").replace("|", "\\|")
                lineas.append("| `%s` | %d | %s |" % (ruta, conteo[ruta], ejemplo))
            lineas.append("")

    reporte = "\n".join(lineas)
    print(reporte)
    if destino:
        with io.open(destino, "w", encoding="utf-8") as fh:
            fh.write(reporte)
        print(verde("\nGuardado en %s" % destino))
        print(gris("Comparte ese archivo si quieres que se añada escritura directa al .pgd."))
    return 0


# --------------------------------------------------------------------------
# Importar el respaldo JSON del cuaderno web
# --------------------------------------------------------------------------

def _slug(texto):
    limpio = re.sub(r"[^\w\s'-]", "", texto, flags=re.UNICODE).strip()
    limpio = re.sub(r"\s+", "-", limpio)
    return limpio or "sin-titulo"


def _escribir_nota(ruta, frontmatter, cuerpo=""):
    carpeta = os.path.dirname(ruta)
    if carpeta and not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    lineas = ["---"]
    for clave, valor in frontmatter:
        if isinstance(valor, list):
            lineas.append("%s: [%s]" % (clave, ", ".join(valor)))
        else:
            texto = como_texto(valor)
            if texto and (":" in texto or texto[0] in "[{#&*!|>%@`\"'"):
                texto = '"%s"' % texto.replace('"', '\\"')
            lineas.append("%s: %s" % (clave, texto))
    lineas.append("---")
    lineas.append("")
    lineas.append(cuerpo)
    with io.open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas))


def importar_cuaderno(ruta_json, ruta_vault, sobrescribir=False):
    """Convierte el respaldo JSON del cuaderno web en notas de Obsidian."""
    try:
        with io.open(ruta_json, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        print(rojo("No se pudo leer el JSON: %s" % exc))
        return 1

    creadas, omitidas = 0, 0

    def crear(ruta, frontmatter, cuerpo=""):
        nonlocal creadas, omitidas
        if os.path.exists(ruta) and not sobrescribir:
            omitidas += 1
            return
        _escribir_nota(ruta, frontmatter, cuerpo)
        creadas += 1

    for w in datos.get("lexicon", []):
        palabra = como_texto(w.get("headword"))
        if not palabra:
            continue
        crear(os.path.join(ruta_vault, "Lexicon", _slug(palabra) + ".md"), [
            ("tipo", "lexema"),
            ("palabra", palabra),
            ("ipa", w.get("ipa", "")),
            ("romanizacion", w.get("roman", "")),
            ("pos", w.get("pos", "")),
            ("glosa", w.get("gloss", "")),
            ("etimologia", w.get("etymology", "")),
            ("estado", w.get("status", "borrador")),
        ])

    for p in datos.get("pos", []):
        nombre = como_texto(p.get("name"))
        if not nombre:
            continue
        crear(os.path.join(ruta_vault, "Categorias", _slug(nombre) + ".md"), [
            ("tipo", "pos"),
            ("etiqueta", nombre),
            ("dimensiones", [como_texto(d) for d in (p.get("dims") or [])]),
        ], como_texto(p.get("notes")))

    for r in datos.get("rules", []):
        etiqueta = como_texto(r.get("label"))
        if not etiqueta:
            continue
        fm = [
            ("tipo", "regla"),
            ("etiqueta", etiqueta),
            ("pos", r.get("pos", "")),
            ("buscar", r.get("find", "")),
            ("reemplazar", r.get("replace", "")),
            ("flags", r.get("flags", "")),
        ]
        cuerpo_pruebas = ""
        pruebas = r.get("tests") or []
        if pruebas:
            bloque = ["pruebas:"]
            for t in pruebas:
                bloque.append("  - entrada: %s" % como_texto(t.get("input")))
                bloque.append("    esperado: %s" % como_texto(t.get("expected")))
            cuerpo_pruebas = "\n".join(bloque)
        ruta = os.path.join(ruta_vault, "Conjugaciones", _slug(etiqueta) + ".md")
        if os.path.exists(ruta) and not sobrescribir:
            omitidas += 1
        else:
            carpeta = os.path.dirname(ruta)
            if not os.path.isdir(carpeta):
                os.makedirs(carpeta)
            lineas = ["---"]
            for clave, valor in fm:
                texto = como_texto(valor)
                if texto and (":" in texto or texto[:1] in "[{#&*!|>%@`\"'"):
                    texto = '"%s"' % texto.replace('"', '\\"')
                lineas.append("%s: %s" % (clave, texto))
            if cuerpo_pruebas:
                lineas.append(cuerpo_pruebas)
            lineas += ["---", ""]
            with io.open(ruta, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lineas))
            creadas += 1

    for i, s in enumerate(datos.get("grammar", []), start=1):
        titulo = como_texto(s.get("title"))
        if not titulo:
            continue
        crear(os.path.join(ruta_vault, "Gramatica", "%02d-%s.md" % (i, _slug(titulo))), [
            ("tipo", "gramatica"),
            ("etiqueta", titulo),
            ("orden", i),
        ], como_texto(s.get("content")))

    fonologia = datos.get("phonology", [])
    if fonologia:
        ruta = os.path.join(ruta_vault, "Fonologia.md")
        if os.path.exists(ruta) and not sobrescribir:
            omitidas += 1
        else:
            filas = ["| Grafema | IPA | Romanización | Reemplazo | Notas |",
                     "|---|---|---|---|---|"]
            for f in fonologia:
                filas.append("| %s | %s | %s | %s | %s |" % (
                    como_texto(f.get("char")), como_texto(f.get("ipa")),
                    como_texto(f.get("roman")), como_texto(f.get("replacement")),
                    como_texto(f.get("notes")).replace("|", "\\|")))
            _escribir_nota(ruta, [("tipo", "fonologia"), ("etiqueta", "Inventario fonológico")],
                           "\n".join(filas))
            creadas += 1

    print(verde("Notas creadas: %d" % creadas))
    if omitidas:
        print(ambar("Omitidas por ya existir: %d  (usa --sobrescribir para reemplazarlas)" % omitidas))
    return 0


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

def _resumen(modelo):
    return "%d lexemas · %d grafemas · %d categorías · %d reglas · %d secciones" % (
        len(modelo["lexemas"]), len(modelo["fonologia"]), len(modelo["pos"]),
        len(modelo["reglas"]), len(modelo["gramatica"]))


def _imprimir_hallazgos(hallazgos):
    errores = [x for x in hallazgos if x.nivel == ERROR]
    avisos = [x for x in hallazgos if x.nivel == AVISO]
    for x in errores:
        print(x.linea())
    for x in avisos:
        print(x.linea())
    if not hallazgos:
        print(verde("  Sin hallazgos: todo consistente."))
    else:
        print("")
        print("  %s errores, %s avisos" % (
            rojo(str(len(errores))) if errores else "0",
            ambar(str(len(avisos))) if avisos else "0"))
    return len(errores)


def cmd_revisar(args):
    modelo, hallazgos = cargar_vault(args.vault)
    hallazgos += revisar(modelo, args.ignorar)
    print(negrita("\nVault: %s" % args.vault))
    print(gris("  " + _resumen(modelo)))
    print("")
    errores = _imprimir_hallazgos(hallazgos)
    print("")
    return 1 if errores else 0


def cmd_exportar(args):
    modelo, hallazgos = cargar_vault(args.vault)
    hallazgos += revisar(modelo, args.ignorar)
    print(negrita("\nVault: %s" % args.vault))
    print(gris("  " + _resumen(modelo)))
    print("")
    errores = _imprimir_hallazgos(hallazgos)
    escritos = exportar(modelo, hallazgos, args.salida)
    print("")
    print(negrita("Archivos generados en %s:" % args.salida))
    for ruta in escritos:
        print("  " + os.path.basename(ruta))
    print("")
    print(gris("En PolyGlot: Archivo → Import from File, y mapea las columnas de lexicon.csv."))
    return 1 if errores and not args.forzar else 0


def cmd_vigilar(args):
    print(negrita("Vigilando %s" % args.vault))
    print(gris("Ctrl+C para detener.\n"))
    huella_previa = None
    try:
        while True:
            huella = []
            for base, dirs, archivos in os.walk(args.vault):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for nombre in archivos:
                    if nombre.lower().endswith(".md"):
                        ruta = os.path.join(base, nombre)
                        try:
                            huella.append((ruta, os.path.getmtime(ruta)))
                        except OSError:
                            pass
            huella = sorted(huella)
            if huella != huella_previa:
                huella_previa = huella
                print(gris("[%s] cambio detectado" % time.strftime("%H:%M:%S")))
                modelo, hallazgos = cargar_vault(args.vault)
                hallazgos += revisar(modelo, args.ignorar)
                print(gris("  " + _resumen(modelo)))
                _imprimir_hallazgos(hallazgos)
                exportar(modelo, hallazgos, args.salida)
                print(gris("  exportado a %s\n" % args.salida))
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("\n" + gris("Detenido."))
        return 0


def cmd_probar(args):
    """Aplica cada regla a las palabras reales de su categoría y muestra el efecto."""
    modelo, hallazgos = cargar_vault(args.vault)
    if not modelo["reglas"]:
        print(ambar("No hay reglas de conjugación en el vault."))
        return 0

    resumen = {"activa": 0, "inerte": 0, "error": 0, "sin-lexico": 0}
    print(negrita("\nEnsayo de %d regla(s) contra %d lexema(s)\n"
                  % (len(modelo["reglas"]), len(modelo["lexemas"]))))

    for r in modelo["reglas"]:
        if r["pos"]:
            objetivo = r["pos"].strip().lower()
            candidatos = [l for l in modelo["lexemas"]
                          if l["pos"].strip().lower() == objetivo]
        else:
            candidatos = modelo["lexemas"]

        error, muestras, afectadas = None, [], 0
        for lex in candidatos:
            ok, salida = aplicar_regla(r, lex["palabra"])
            if not ok:
                error = salida
                break
            if salida != lex["palabra"]:
                afectadas += 1
                if len(muestras) < args.muestras:
                    muestras.append((lex["palabra"], salida))

        if error:
            estado, color = "error", rojo
        elif not candidatos:
            estado, color = "sin-lexico", gris
        elif afectadas == 0:
            estado, color = "inerte", ambar
        else:
            estado, color = "activa", verde
        resumen[estado] += 1

        cabecera = "  %s  %s" % (color("%-11s" % estado), r["etiqueta"])
        if r["pos"]:
            cabecera += gris(" · " + r["pos"])
        print(cabecera)
        print(gris("      /%s/ → \"%s\"" % (r["buscar"], r["reemplazar"])))
        if error:
            print("      " + rojo(error))
        elif estado == "inerte":
            print(gris("      ninguna de las %d palabras de su categoría cambia" % len(candidatos)))
        elif estado == "sin-lexico":
            print(gris("      su categoría no tiene palabras"))
        else:
            for entrada, salida in muestras:
                print("      %s → %s" % (entrada, salida))
            print(gris("      afecta a %d de %d" % (afectadas, len(candidatos))))
        print("")

    print(negrita("Resumen: ") +
          "%s activas · %s inertes · %s con error · %s sin léxico" % (
              verde(str(resumen["activa"])),
              ambar(str(resumen["inerte"])) if resumen["inerte"] else "0",
              rojo(str(resumen["error"])) if resumen["error"] else "0",
              resumen["sin-lexico"]))
    print(gris("Una regla inerte o con error no hace lo que crees: revísala antes de aplicarla en PolyGlot.\n"))
    return 1 if resumen["error"] else 0


def cmd_inspeccionar(args):
    return inspeccionar_pgd(args.pgd, args.salida)


def cmd_importar(args):
    return importar_cuaderno(args.json, args.vault, args.sobrescribir)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="tabure",
        description="Puente entre un vault de Obsidian y PolyGlot para tabure'shi.")
    sub = p.add_subparsers(dest="comando")

    def con_vault(sp):
        sp.add_argument("--vault", required=True, help="Carpeta del vault de Obsidian")
        sp.add_argument("--ignorar", default=" -",
                        help="Caracteres que no se validan contra la fonología (por defecto: espacio y guion)")

    sp = sub.add_parser("revisar", help="Valida el vault sin escribir nada")
    con_vault(sp)
    sp.set_defaults(func=cmd_revisar)

    sp = sub.add_parser("exportar", help="Valida y genera los archivos para PolyGlot")
    con_vault(sp)
    sp.add_argument("--salida", required=True, help="Carpeta donde escribir los archivos")
    sp.add_argument("--forzar", action="store_true", help="Salir con código 0 aunque haya errores")
    sp.set_defaults(func=cmd_exportar)

    sp = sub.add_parser("vigilar", help="Revisa y exporta automáticamente al detectar cambios")
    con_vault(sp)
    sp.add_argument("--salida", required=True, help="Carpeta donde escribir los archivos")
    sp.add_argument("--intervalo", type=float, default=2.0, help="Segundos entre revisiones")
    sp.set_defaults(func=cmd_vigilar)

    sp = sub.add_parser("probar", help="Aplica cada regla al léxico real y muestra qué produce")
    con_vault(sp)
    sp.add_argument("--muestras", type=int, default=4, help="Ejemplos a mostrar por regla")
    sp.set_defaults(func=cmd_probar)

    sp = sub.add_parser("extraer", help="Saca el contenido de un .pgd al formato del cuaderno (solo lectura)")
    sp.add_argument("--pgd", required=True, help="Ruta al archivo .pgd de PolyGlot")
    sp.add_argument("--salida", default="paquete.json", help="Archivo JSON a escribir")
    sp.set_defaults(func=cmd_extraer)

    sp = sub.add_parser("inspeccionar", help="Describe la estructura real de un archivo .pgd")
    sp.add_argument("--pgd", required=True, help="Ruta al archivo .pgd de PolyGlot")
    sp.add_argument("--salida", help="Guardar el informe en este archivo")
    sp.set_defaults(func=cmd_inspeccionar)

    sp = sub.add_parser("importar-cuaderno", help="Crea notas del vault desde el respaldo JSON del cuaderno web")
    sp.add_argument("json", help="Archivo JSON exportado desde el cuaderno")
    sp.add_argument("--vault", required=True, help="Carpeta del vault de Obsidian")
    sp.add_argument("--sobrescribir", action="store_true", help="Reemplazar notas que ya existan")
    sp.set_defaults(func=cmd_importar)

    args = p.parse_args(argv)

    # El shell expande ~ solo si va fuera de comillas; hacerlo aquí también
    # evita que una ruta entrecomillada falle con un "no existe el archivo".
    for campo in ("vault", "salida", "pgd", "json"):
        valor = getattr(args, campo, None)
        if isinstance(valor, str) and valor.startswith("~"):
            setattr(args, campo, os.path.expanduser(valor))

    if not getattr(args, "func", None):
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
