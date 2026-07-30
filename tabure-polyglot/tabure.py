#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tabure.py — Puente entre el cuaderno de tabure'shi y PolyGlot.

Un solo formato de datos, el paquete JSON, y cinco comandos alrededor:

    extraer       .pgd  → paquete.json     (solo lectura)
    revisar       paquete.json → informe   (no escribe)
    probar        paquete.json → ensayo de reglas contra el léxico
    inyectar      paquete.json → .pgd nuevo
    inspeccionar  .pgd  → estructura interna (solo lectura)

El paquete es el mismo JSON que consume el cuaderno web, con las claves
phonology, pos, classes, lexicon, rules y grammar.

Requiere Python 3.8+ y solo la biblioteca estándar. Verificado contra
PolyGlot 3.6.1.
"""

import argparse
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET


# --------------------------------------------------------------------------
# Presentación
# --------------------------------------------------------------------------

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(t, code):
    return "\033[%sm%s\033[0m" % (code, t) if _COLOR else t


def rojo(t): return _c(t, "31")
def ambar(t): return _c(t, "33")
def verde(t): return _c(t, "32")
def gris(t): return _c(t, "90")
def negrita(t): return _c(t, "1")


ERROR, AVISO = "error", "aviso"


class Hallazgo(object):
    def __init__(self, nivel, area, mensaje):
        self.nivel, self.area, self.mensaje = nivel, area, mensaje

    def linea(self):
        etiqueta = rojo("ERROR") if self.nivel == ERROR else ambar("AVISO")
        return "  %s  %-12s %s" % (etiqueta, self.area, self.mensaje)


# --------------------------------------------------------------------------
# El paquete
# --------------------------------------------------------------------------

SECCIONES = ["phonology", "pos", "classes", "lexicon", "rules", "grammar"]


def resolver_paquete(ruta):
    """Acepta un archivo o una carpeta.

    Si es carpeta, elige el paquete*.json más reciente que contenga. Eso permite
    apuntar a Descargas sin preocuparse de que el navegador haya guardado el
    archivo como paquete-1.json en la segunda descarga.
    """
    p = os.path.expanduser(ruta)
    if os.path.isdir(p):
        candidatos = [os.path.join(p, n) for n in os.listdir(p)
                      if n.startswith("paquete") and n.endswith(".json")
                      and not n.endswith("-anterior.json")]
        if not candidatos:
            raise IOError("no hay ningún paquete*.json en %s" % p)
        return max(candidatos, key=os.path.getmtime)
    return p


def cargar_paquete(ruta):
    with io.open(resolver_paquete(ruta), "r", encoding="utf-8") as fh:
        datos = json.load(fh)
    if not isinstance(datos, dict):
        raise ValueError("el JSON no es un objeto con las claves del paquete")
    for k in SECCIONES:
        datos.setdefault(k, [])
        if not isinstance(datos[k], list):
            raise ValueError("la clave \"%s\" debería ser una lista" % k)
    return datos


def ruta_anterior(destino):
    raiz, ext = os.path.splitext(destino)
    return raiz + "-anterior" + ext


def guardar_paquete(datos, ruta):
    """Escribe el paquete rotando el anterior: solo quedan dos archivos, el de
    trabajo y su versión previa, para poder volver atrás si algo sale mal."""
    destino = os.path.expanduser(ruta)
    if os.path.isdir(destino) or destino.endswith(("/", os.sep)):
        destino = os.path.join(destino, "paquete.json")
    carpeta = os.path.dirname(os.path.abspath(destino))
    if not os.path.isdir(carpeta):
        raise IOError("no existe la carpeta %s" % carpeta)
    rotado = None
    if os.path.exists(destino):
        rotado = ruta_anterior(destino)
        if os.path.exists(rotado):
            os.remove(rotado)
        os.rename(destino, rotado)
    with io.open(destino, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(datos, ensure_ascii=False, indent=1))
    return destino, rotado


# --------------------------------------------------------------------------
# Reglas regex
# --------------------------------------------------------------------------

def _a_retro_python(reemplazo):
    """PolyGlot es Java y usa $1; Python usa \\1. Se traduce para que una regla
    escrita como la espera PolyGlot dé aquí el mismo resultado."""
    salida, i = "", 0
    while i < len(reemplazo):
        c = reemplazo[i]
        if c == "$" and i + 1 < len(reemplazo) and reemplazo[i + 1].isdigit():
            salida += "\\" + reemplazo[i + 1]
            i += 2
        elif c == "\\" and i + 1 < len(reemplazo):
            salida += reemplazo[i:i + 2]
            i += 2
        else:
            salida += c
            i += 1
    return salida


def aplicar_regla(regla, entrada):
    """Devuelve (ok, resultado_o_error)."""
    flags = (regla.get("flags") or "").lower()
    banderas = (re.IGNORECASE if "i" in flags else 0) | (re.MULTILINE if "m" in flags else 0)
    try:
        patron = re.compile(regla.get("find") or "", banderas)
    except re.error as exc:
        return False, "regex inválida: %s" % exc
    try:
        return True, patron.sub(_a_retro_python(regla.get("replace") or ""),
                                entrada, count=0 if "g" in flags else 1)
    except re.error as exc:
        return False, "reemplazo inválido: %s" % exc


def valor_clase(lex, nombre):
    return (lex.get("classes") or {}).get(nombre, "")


def lexemas_de(paquete, regla):
    """Palabras a las que alcanza una regla: por categoría y por clase léxica."""
    lista = paquete["lexicon"]
    pos = (regla.get("pos") or "").strip().lower()
    if pos:
        lista = [w for w in lista if (w.get("pos") or "").strip().lower() == pos]
    clase, valor = regla.get("claseFiltro"), regla.get("valorFiltro")
    if clase and valor:
        lista = [w for w in lista if valor_clase(w, clase) == valor]
    return lista


def ensayar(paquete, limite=4):
    """Aplica cada regla a su léxico real y la clasifica."""
    salida = []
    for r in paquete["rules"]:
        candidatos = lexemas_de(paquete, r)
        error, muestras, afectadas = None, [], 0
        for w in candidatos:
            ok, res = aplicar_regla(r, w.get("headword") or "")
            if not ok:
                error = res
                break
            if res != w.get("headword"):
                afectadas += 1
                if len(muestras) < limite:
                    muestras.append((w["headword"], res))
        estado = ("error" if error else
                  "sin-lexico" if not candidatos else
                  "inerte" if afectadas == 0 else "activa")
        salida.append({"regla": r, "estado": estado, "error": error,
                       "muestras": muestras, "afectadas": afectadas,
                       "candidatos": len(candidatos)})
    return salida


# --------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------

# El apóstrofe es marca ortográfica de límite morfológico (§3.5), no un
# fonema: se ignora al comprobar la cobertura del inventario.
IGNORAR_POR_DEFECTO = " -'"

IPA_VOCALES = "aeiouɑɐɒæəɘɛɜɞɨɪøɵœɶʊʉʌɔɤɯyʏ"
IPA_MODIF = re.compile("[ːˑˈˌ̀-ͯʰ-˿]")


def parece_vocal(fila):
    texto = IPA_MODIF.sub("", unicodedata.normalize("NFD", fila.get("ipa") or fila.get("char") or ""))
    letras = list(texto)
    nucleo = [c for c in letras if c in IPA_VOCALES]
    return bool(nucleo) and len(nucleo) == len(letras)


def tokenizar(palabra, grafemas, ignorar=IGNORAR_POR_DEFECTO):
    orden = sorted([g for g in grafemas if g], key=len, reverse=True)
    tokens, desconocidos, i = [], [], 0
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


def revisar(paquete, ignorar=IGNORAR_POR_DEFECTO):
    h = []
    fon, pos, lex, reglas = (paquete["phonology"], paquete["pos"],
                             paquete["lexicon"], paquete["rules"])

    # ---- Fonología -------------------------------------------------------
    vistos, romans = {}, {}
    for f in fon:
        g = f.get("char") or ""
        if g in vistos:
            h.append(Hallazgo(ERROR, "fonología", "Grafema duplicado «%s»" % g))
        vistos[g] = True
        if not f.get("ipa"):
            h.append(Hallazgo(AVISO, "fonología", "«%s» sin fonema AFI" % g))
        r = f.get("roman")
        if r:
            if r in romans and romans[r] != g:
                h.append(Hallazgo(ERROR, "fonología",
                                  "Romanización ambigua «%s»: la usan «%s» y «%s»" % (r, romans[r], g)))
            romans[r] = g

    # ---- Teclas de sustitución -------------------------------------------
    inventario = set(vistos)
    teclas = {}
    for f in fon:
        g, t = f.get("char") or "", f.get("replacement") or ""
        if not t:
            if any(ord(c) > 126 for c in g):
                h.append(Hallazgo(AVISO, "teclas", "«%s» no se teclea y no tiene tecla asignada" % g))
            continue
        if len(t) > 1:
            h.append(Hallazgo(ERROR, "teclas",
                              "La tecla de «%s» es «%s»: PolyGlot admite un solo carácter" % (g, t)))
        if t in teclas:
            h.append(Hallazgo(ERROR, "teclas",
                              "Tecla repetida «%s»: la usan «%s» y «%s»" % (t, teclas[t], g)))
        else:
            teclas[t] = g
        if t in inventario:
            h.append(Hallazgo(ERROR, "teclas",
                              "La tecla «%s» es también un grafema: se sustituiría sola" % t))
    for t, duenio in sorted(teclas.items()):
        afectadas = [w["headword"] for w in lex if t in (w.get("headword") or "")]
        if afectadas:
            h.append(Hallazgo(ERROR, "teclas",
                              "La tecla «%s» (de «%s») aparece dentro de %s: al teclearlas se sustituiría"
                              % (t, duenio, ", ".join(afectadas[:3]))))

    # ---- Cobertura de caracteres -----------------------------------------
    grafemas = list(vistos)
    if grafemas:
        faltan, usados = {}, set()
        for w in lex:
            tk, desc = tokenizar(w.get("headword") or "", grafemas, ignorar)
            usados.update(tk)
            for d in desc:
                faltan.setdefault(d, []).append(w["headword"])
        for ch, palabras in sorted(faltan.items()):
            try:
                nombre = " [%s]" % unicodedata.name(ch)
            except ValueError:
                nombre = ""
            h.append(Hallazgo(ERROR, "cobertura",
                              "El carácter «%s»%s aparece en el léxico pero no está en Phonology (%s)"
                              % (ch, nombre, ", ".join(palabras[:4]))))
        for g in grafemas:
            if g not in usados and lex:
                h.append(Hallazgo(AVISO, "cobertura",
                                  "El grafema «%s» está declarado y ningún lexema lo usa" % g))

    # ---- Categorías -------------------------------------------------------
    declaradas = {(p.get("name") or "").strip(): p for p in pos}
    for w in lex:
        p = (w.get("pos") or "").strip()
        if not p:
            h.append(Hallazgo(AVISO, "pos", "«%s» sin categoría" % w.get("headword")))
        elif p not in declaradas:
            h.append(Hallazgo(ERROR, "pos", "«%s» usa la categoría «%s», no declarada"
                              % (w.get("headword"), p)))
    for nombre, p in declaradas.items():
        if not any((w.get("pos") or "").strip() == nombre for w in lex):
            h.append(Hallazgo(AVISO, "pos", "La categoría «%s» no tiene lexemas" % nombre))
        if not p.get("notes"):
            h.append(Hallazgo(AVISO, "pos", "La categoría «%s» no tiene descripción" % nombre))

    # ---- Clases léxicas ---------------------------------------------------
    for cl in paquete["classes"]:
        nombre, valores = cl.get("name") or "", cl.get("values") or []
        if len(valores) < 2:
            h.append(Hallazgo(ERROR, "clases", "La clase «%s» necesita al menos dos valores" % nombre))
        alcance = [w for w in lex if not cl.get("appliesTo")
                   or (w.get("pos") or "") in cl["appliesTo"]]
        sin = [w["headword"] for w in alcance if valor_clase(w, nombre) not in valores]
        if sin:
            h.append(Hallazgo(AVISO, "clases",
                              "%d palabra(s) en alcance de «%s» sin valor asignado (%s)"
                              % (len(sin), nombre, ", ".join(sin[:4]))))
        for n in cl.get("appliesTo") or []:
            if n not in declaradas:
                h.append(Hallazgo(ERROR, "clases",
                                  "«%s» aplica a «%s», que no es una categoría declarada" % (nombre, n)))

    # ---- Reglas -----------------------------------------------------------
    nombres_clase = {c.get("name"): (c.get("values") or []) for c in paquete["classes"]}
    for r in reglas:
        etiqueta = r.get("label") or "(sin etiqueta)"
        if not r.get("find"):
            h.append(Hallazgo(ERROR, "conjugación", "«%s» sin patrón de búsqueda" % etiqueta))
            continue
        ok, msg = aplicar_regla(r, "prueba")
        if not ok:
            h.append(Hallazgo(ERROR, "conjugación", "«%s»: %s" % (etiqueta, msg)))
            continue
        find = r["find"]
        if not find.startswith("^") and not find.endswith("$"):
            h.append(Hallazgo(AVISO, "conjugación",
                              "«%s» no está anclada (sin ^ ni $): puede alterar el interior" % etiqueta))
        if "\\1" in (r.get("replace") or ""):
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s» usa \\1 en el reemplazo: PolyGlot es Java y espera $1" % etiqueta))
        p = (r.get("pos") or "").strip()
        if p and p not in declaradas:
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s» apunta a la categoría «%s», no declarada" % (etiqueta, p)))
        clase, valor = r.get("claseFiltro"), r.get("valorFiltro")
        if clase and clase not in nombres_clase:
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s» filtra por la clase «%s», que no existe" % (etiqueta, clase)))
        elif clase and valor and valor not in nombres_clase[clase]:
            h.append(Hallazgo(ERROR, "conjugación",
                              "«%s» filtra por «%s = %s», valor inexistente" % (etiqueta, clase, valor)))
        if not r.get("tests"):
            h.append(Hallazgo(AVISO, "conjugación", "«%s» sin casos de prueba" % etiqueta))
        for t in r.get("tests") or []:
            ok, salida = aplicar_regla(r, t.get("input") or "")
            if not ok:
                h.append(Hallazgo(ERROR, "conjugación", "«%s»: %s" % (etiqueta, salida)))
            elif salida != t.get("expected"):
                h.append(Hallazgo(ERROR, "conjugación",
                                  "«%s»: %s → %s, se esperaba %s"
                                  % (etiqueta, t.get("input"), salida, t.get("expected"))))

    # ---- Gramática --------------------------------------------------------
    titulos = {}
    for s in paquete["grammar"]:
        t = (s.get("title") or "").strip()
        if not s.get("content"):
            h.append(Hallazgo(AVISO, "gramática", "La sección «%s» está vacía" % t))
        if t in titulos:
            h.append(Hallazgo(ERROR, "gramática", "Título de sección repetido: «%s»" % t))
        titulos[t] = True

    return h


# --------------------------------------------------------------------------
# Lectura del .pgd
# --------------------------------------------------------------------------

_RE_TAGS = re.compile(r"<[^>]+>")
_ENTIDADES = [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
              ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]


def _texto_plano(bruto):
    if not bruto:
        return ""
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", bruto)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</p\s*>", "\n", t)
    t = _RE_TAGS.sub("", t)
    for a, b in _ENTIDADES:
        t = t.replace(a, b)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", t).strip()


def _sin_barras(t):
    return (t or "").replace("/", "").strip()


def _hijo(nodo, etiqueta, defecto=""):
    x = nodo.find(etiqueta)
    return x.text if x is not None and x.text is not None else defecto


def _abrir(ruta_pgd):
    """Devuelve (raíz_xml, nombre_del_xml, entradas_del_zip)."""
    ruta = os.path.expanduser(ruta_pgd)
    if not os.path.isfile(ruta):
        raise IOError("no existe el archivo %s" % ruta)
    if zipfile.is_zipfile(ruta):
        with zipfile.ZipFile(ruta) as z:
            entradas = [(n, z.read(n)) for n in z.namelist()]
        candidatos = [n for n, _ in entradas
                      if n.lower().endswith(".xml") and not n.startswith("reversion/")]
        if not candidatos:
            raise ValueError("el .pgd no contiene un XML principal")
        return ET.fromstring(dict(entradas)[candidatos[0]]), candidatos[0], entradas
    with open(ruta, "rb") as fh:
        crudo = fh.read()
    return ET.fromstring(crudo), None, [(None, crudo)]


def declinaciones_de(raiz):
    """Mapa id_de_categoría -> lista de ejes, cada eje con sus dimensiones.

    Es lo que permite atar una regla a la casilla que genera: PolyGlot guarda
    ese enlace en decGenRuleComb, y sin él la regla no se aplica a nada.
    """
    ejes = {}
    for nodo in raiz.findall("./declensionCollection/declensionNode"):
        pos_id = _hijo(nodo, "declensionRelatedId")
        eje = {
            "id": _hijo(nodo, "declensionId"),
            "nombre": _hijo(nodo, "declensionText"),
            "dimensiones": [{"id": _hijo(d, "dimensionId"),
                             "nombre": _hijo(d, "dimensionName")}
                            for d in nodo.findall("./dimensionNode")],
        }
        ejes.setdefault(pos_id, []).append(eje)
    for lista in ejes.values():
        lista.sort(key=lambda e: (len(e["id"]), e["id"]))
    return ejes


def extraer(ruta_pgd):
    raiz, _, _ = _abrir(ruta_pgd)
    paquete = dict((k, []) for k in SECCIONES)
    avisos = []

    # Categorías y sus dimensiones
    nombre_pos, por_id = {}, {}
    for nodo in raiz.findall("./partsOfSpeech/partOfSpeechNode"):
        pid, nombre = _hijo(nodo, "partOfSpeechId"), _hijo(nodo, "partOfSpeechName")
        if not nombre:
            continue
        nombre_pos[pid] = nombre
        entrada = {"name": nombre, "dims": [],
                   "notes": _texto_plano(_hijo(nodo, "partOfSpeechNotes")),
                   "status": "verified"}
        por_id[pid] = entrada
        paquete["pos"].append(entrada)
    ejes = declinaciones_de(raiz)
    for pid, lista in ejes.items():
        if pid in por_id:
            for eje in lista:
                for d in eje["dimensiones"]:
                    if d["nombre"] and d["nombre"] not in por_id[pid]["dims"]:
                        por_id[pid]["dims"].append(d["nombre"])

    # Fonología
    romanizacion = {}
    for nodo in raiz.findall("./romGuide/romGuideNode"):
        base = _sin_barras(_hijo(nodo, "romGuideBase"))
        if base:
            romanizacion[base] = _hijo(nodo, "romGuidePhon")
    tecla_de = {}
    for nodo in raiz.findall("./languageProperties/langPropCharRep/langPropCharRepNode"):
        grafema = _hijo(nodo, "langPropCharRepValue")
        if grafema:
            tecla_de[grafema] = _hijo(nodo, "langPropCharRepCharacter")
    vistos = set()
    for nodo in raiz.findall("./pronunciationCollection/proGuide"):
        base = _hijo(nodo, "proGuideBase")
        if not base or base in vistos:
            continue
        vistos.add(base)
        paquete["phonology"].append({
            "char": base, "ipa": _sin_barras(_hijo(nodo, "proGuidePhon")),
            "roman": romanizacion.get(base, ""), "replacement": tecla_de.get(base, ""),
            "notes": ""})
    for grafema, tecla in tecla_de.items():
        if grafema not in vistos:
            vistos.add(grafema)
            paquete["phonology"].append({"char": grafema, "ipa": "",
                                         "roman": romanizacion.get(grafema, ""),
                                         "replacement": tecla, "notes": ""})

    # Léxico
    for nodo in raiz.findall("./lexicon/word"):
        palabra = _hijo(nodo, "conWord")
        if not palabra:
            continue
        paquete["lexicon"].append({
            "headword": palabra, "ipa": _sin_barras(_hijo(nodo, "pronunciation")),
            "roman": "", "pos": nombre_pos.get(_hijo(nodo, "wordPosId"), ""),
            "gloss": _hijo(nodo, "localWord"),
            "etymology": _texto_plano(_hijo(nodo, "wordEtymologyNotes")),
            "status": "verified"})

    # Reglas, con su enlace a la casilla y el nombre de la dimensión
    nombre_dim = {}
    for lista in ejes.values():
        for eje in lista:
            for d in eje["dimensiones"]:
                nombre_dim[d["id"]] = d["nombre"]
    for n, nodo in enumerate(raiz.findall("./declensionCollection/decGenRule")):
        etiqueta = _hijo(nodo, "decGenRuleName")
        comb = _hijo(nodo, "decGenRuleComb")
        ids = [x for x in comb.split(",") if x]
        dimension = " · ".join(nombre_dim.get(x, x) for x in ids)
        meta = {"pos": nombre_pos.get(_hijo(nodo, "decGenRuleTypeId"), ""),
                "dimension": dimension, "pgComb": comb,
                "pgIndex": _hijo(nodo, "decGenRuleIndex"),
                "pgRegex": _hijo(nodo, "decGenRuleRegex"),
                "pgGrupo": "r%03d" % n}
        trans = nodo.findall("./decGenTrans")
        for i, tr in enumerate(trans, start=1):
            buscar = _hijo(tr, "decGenTransRegex")
            if not buscar:
                continue
            fila = {"label": (etiqueta or "Regla sin nombre") +
                             ("" if len(trans) == 1 else " (%d)" % i),
                    "find": buscar, "replace": _hijo(tr, "decGenTransReplace"),
                    "flags": "", "tests": []}
            fila.update(meta)
            paquete["rules"].append(fila)

    # Gramática
    for cap in raiz.findall("./grammarCollection/grammarChapterNode"):
        nombre_cap = _hijo(cap, "grammarChapterName")
        for sec in cap.findall("./grammarSectionsList/grammarSectionNode"):
            paquete["grammar"].append({
                "title": _hijo(sec, "grammarSectionName") or nombre_cap,
                "content": _texto_plano(_hijo(sec, "grammarSectionText"))})

    sin_pareja = [b for b in romanizacion if b not in vistos]
    if sin_pareja:
        avisos.append("%d regla(s) de romanización sin grafema correspondiente: %s"
                      % (len(sin_pareja), " ".join(sorted(sin_pareja)[:8])))
    return paquete, avisos


# --------------------------------------------------------------------------
# Escritura en el .pgd
# --------------------------------------------------------------------------

def _xesc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _html(texto, fuente="Charis SIL"):
    return ('<font face="%s"size="12"color="black">%s</font>'
            % (fuente, _xesc(texto or "").replace("\n", "<br>")))


def _vaciar(padre, etiqueta):
    for viejo in padre.findall(etiqueta):
        padre.remove(viejo)


def _sub(padre, etiqueta, texto=""):
    nodo = ET.SubElement(padre, etiqueta)
    nodo.text = texto or ""
    return nodo


def _asegurar(raiz, etiqueta):
    nodo = raiz.find("./" + etiqueta)
    return nodo if nodo is not None else ET.SubElement(raiz, etiqueta)


def _comb_para(ejes_pos, dimension):
    """Construye el decGenRuleComb que ata una regla a una casilla.

    El formato se dedujo de los valores que guarda PolyGlot 3.6.1: una ranura
    por eje de declinación, separadas y envueltas en comas, con el id de la
    dimensión elegida en la ranura de su eje y el resto vacías.
    """
    if not ejes_pos or not dimension:
        return None
    # La etiqueta de una regla suele llevar un calificador tras «·»
    # («Acusativo · tema vocálico»); la casilla la determina lo que va antes.
    objetivo = dimension.split("·")[0].strip().lower()
    ranuras = []
    encontrado = False
    for eje in ejes_pos:
        elegido = ""
        for d in eje["dimensiones"]:
            if (d["nombre"] or "").strip().lower() == objetivo:
                elegido = d["id"]
                encontrado = True
                break
        ranuras.append(elegido)
    return ("," + ",".join(ranuras) + ",").replace(",,,", ",,") if encontrado else None


def inyectar(ruta_pgd, paquete, destino, secciones, fuente="Charis SIL"):
    raiz, nombre_xml, entradas = _abrir(ruta_pgd)
    if nombre_xml is None:
        raise ValueError("solo se escribe en .pgd con contenedor ZIP")
    informe = dict((k, 0) for k in secciones)
    avisos, detalle_comb = [], []

    if "pos" in secciones and paquete["pos"]:
        col = _asegurar(raiz, "partsOfSpeech")
        # Los ids se conservan por nombre: renumerarlos desconectaría las
        # declinaciones, que apuntan a la categoría por su id.
        previos = {}
        for nodo in col.findall("partOfSpeechNode"):
            n = _hijo(nodo, "partOfSpeechName").strip()
            if n:
                previos[n] = _hijo(nodo, "partOfSpeechId")
        usados = set(previos.values())
        siguiente = [max([int(x) for x in usados if x.isdigit()] or [0]) + 1]

        def id_para(nombre):
            if nombre in previos:
                return previos[nombre]
            while str(siguiente[0]) in usados:
                siguiente[0] += 1
            nuevo = str(siguiente[0])
            usados.add(nuevo)
            return nuevo

        _vaciar(col, "partOfSpeechNode")
        for p in paquete["pos"]:
            nombre = (p.get("name") or "").strip()
            if not nombre:
                continue
            nodo = _sub(col, "partOfSpeechNode")
            _sub(nodo, "partOfSpeechId", id_para(nombre))
            _sub(nodo, "partOfSpeechName", nombre)
            _sub(nodo, "partOfSpeechNotes", _html(p.get("notes"), fuente))
            _sub(nodo, "partOfSpeechGloss")
            _sub(nodo, "partOfSpeechPattern")
            _sub(nodo, "definitionMandatoryPartOfSpeech", "F")
            _sub(nodo, "pronunciationMandatoryPartOfSpeech", "F")
            informe["pos"] += 1

    mapa_pos = {}
    for nodo in raiz.findall("./partsOfSpeech/partOfSpeechNode"):
        n = _hijo(nodo, "partOfSpeechName").strip()
        if n:
            mapa_pos[n] = _hijo(nodo, "partOfSpeechId")

    if "phonology" in secciones and paquete["phonology"]:
        pro = _asegurar(raiz, "pronunciationCollection")
        _vaciar(pro, "proGuide")
        rom = _asegurar(raiz, "romGuide")
        _vaciar(rom, "romGuideNode")
        props = _asegurar(raiz, "languageProperties")
        charrep = props.find("./langPropCharRep")
        if charrep is None:
            charrep = _sub(props, "langPropCharRep")
        _vaciar(charrep, "langPropCharRepNode")
        for f in paquete["phonology"]:
            g = (f.get("char") or "").strip()
            if not g:
                continue
            nodo = _sub(pro, "proGuide")
            _sub(nodo, "proGuideBase", g)
            ipa = (f.get("ipa") or "").strip()
            _sub(nodo, "proGuidePhon", "/%s/" % ipa if ipa else "")
            informe["phonology"] += 1
            if (f.get("roman") or "").strip():
                r = _sub(rom, "romGuideNode")
                _sub(r, "romGuideBase", g)
                _sub(r, "romGuidePhon", f["roman"].strip())
            if (f.get("replacement") or "").strip():
                c = _sub(charrep, "langPropCharRepNode")
                _sub(c, "langPropCharRepCharacter", f["replacement"].strip())
                _sub(c, "langPropCharRepValue", g)

    if "lexicon" in secciones and paquete["lexicon"]:
        col = _asegurar(raiz, "lexicon")
        _vaciar(col, "word")
        huerfanas = set()
        for i, w in enumerate(paquete["lexicon"], start=1):
            palabra = (w.get("headword") or "").strip()
            if not palabra:
                continue
            nombre_pos = (w.get("pos") or "").strip()
            pid = mapa_pos.get(nombre_pos, "")
            if nombre_pos and not pid:
                huerfanas.add(nombre_pos)
            nodo = _sub(col, "word")
            _sub(nodo, "wordId", str(i))
            _sub(nodo, "conWord", palabra)
            _sub(nodo, "localWord", w.get("gloss"))
            _sub(nodo, "wordPosId", pid)
            _sub(nodo, "pronunciation", w.get("ipa"))
            _sub(nodo, "definition", _html(w.get("gloss"), fuente))
            _sub(nodo, "wordEtymologyNotes", _html(w.get("etymology"), fuente))
            _sub(nodo, "autoDeclOverride", "F")
            _sub(nodo, "wordProcOverride", "F")
            _sub(nodo, "wordRuleOverride", "F")
            _sub(nodo, "wordClassCollection")
            _sub(nodo, "wordClassTextValueCollection")
            informe["lexicon"] += 1
        if huerfanas:
            avisos.append("Categorías no declaradas, sus palabras quedan sin asignar: "
                          + ", ".join(sorted(huerfanas)))

    if "rules" in secciones and paquete["rules"]:
        ejes = declinaciones_de(raiz)
        col = _asegurar(raiz, "declensionCollection")
        _vaciar(col, "decGenRule")
        grupos, orden = {}, []
        for r in paquete["rules"]:
            clave = r.get("pgGrupo") or "%s|%s|%s" % (r.get("label"), r.get("pos"),
                                                      r.get("dimension"))
            if clave not in grupos:
                grupos[clave] = []
                orden.append(clave)
            grupos[clave].append(r)
        sin_casilla = []
        for clave in orden:
            filas = grupos[clave]
            cab = filas[0]
            pos_nombre = (cab.get("pos") or "").strip()
            pid = mapa_pos.get(pos_nombre, "")
            etiqueta = re.sub(r"\s*\(\d+\)$", "", cab.get("label") or "")
            # Prioridad: el comb original; si no, se resuelve por el nombre de
            # la dimensión; si tampoco, se busca por la etiqueta de la regla.
            comb = cab.get("pgComb") or ""
            if not comb:
                comb = (_comb_para(ejes.get(pid), cab.get("dimension"))
                        or _comb_para(ejes.get(pid), etiqueta) or "")
                if comb:
                    detalle_comb.append("%s → %s" % (etiqueta, comb))
            if not comb:
                sin_casilla.append(etiqueta)
            nodo = _sub(col, "decGenRule")
            _sub(nodo, "decGenRuleName", etiqueta)
            _sub(nodo, "decGenRuleTypeId", pid)
            _sub(nodo, "decGenRuleComb", comb)
            _sub(nodo, "decGenRuleIndex", cab.get("pgIndex") or "1")
            _sub(nodo, "decGenRuleRegex", cab.get("pgRegex") or ".*")
            _sub(nodo, "decGenRuleApplyToClasses")
            for r in filas:
                tr = _sub(nodo, "decGenTrans")
                _sub(tr, "decGenTransRegex", r.get("find"))
                _sub(tr, "decGenTransReplace", r.get("replace"))
                informe["rules"] += 1
        if sin_casilla:
            avisos.append("%d regla(s) sin casilla de declinación: PolyGlot las guarda "
                          "pero no las aplica. Renombra la regla o su campo \"dimension\" "
                          "para que coincida con una dimensión de su categoría (%s)"
                          % (len(sin_casilla), ", ".join(sin_casilla[:5])))

    if "grammar" in secciones and paquete["grammar"]:
        col = _asegurar(raiz, "grammarCollection")
        _vaciar(col, "grammarChapterNode")
        capitulos, orden_cap = {}, []
        for s in paquete["grammar"]:
            t = (s.get("title") or "").strip()
            m = re.match(r"^(\d+)", t)
            clave = m.group(1) if m else "Sin capítulo"
            if clave not in capitulos:
                capitulos[clave] = []
                orden_cap.append(clave)
            capitulos[clave].append(s)
        for clave in orden_cap:
            nombre_cap = clave
            for s in capitulos[clave]:
                t = (s.get("title") or "").strip()
                if re.match(r"^" + re.escape(clave) + r"\s+\S", t):
                    nombre_cap = t
                    break
            cap = _sub(col, "grammarChapterNode")
            _sub(cap, "grammarChapterName", nombre_cap)
            lista = _sub(cap, "grammarSectionsList")
            for s in capitulos[clave]:
                t = (s.get("title") or "").strip()
                if t == nombre_cap and not (s.get("content") or "").strip():
                    continue
                nodo = _sub(lista, "grammarSectionNode")
                _sub(nodo, "gptSelected", "F")
                _sub(nodo, "grammarSectionName", t)
                _sub(nodo, "grammarSectionRecordingXID", "-1")
                _sub(nodo, "grammarSectionText", _html(s.get("content"), fuente))
                informe["grammar"] += 1

    if "classes" in secciones:
        avisos.append("Las clases léxicas no se escriben: su contenedor está vacío en el "
                      "archivo de origen y su estructura interna no es conocida.")

    nuevo = ET.tostring(raiz, encoding="UTF-8", xml_declaration=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in entradas:
            z.writestr(nombre, nuevo if nombre == nombre_xml else datos)
    return informe, avisos, detalle_comb


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------

def _resumen(paquete):
    return " · ".join("%d %s" % (len(paquete[k]), k) for k in SECCIONES if paquete[k])


def _imprimir(hallazgos):
    errores = [x for x in hallazgos if x.nivel == ERROR]
    avisos = [x for x in hallazgos if x.nivel == AVISO]
    for x in errores + avisos:
        print(x.linea())
    if not hallazgos:
        print(verde("  Sin hallazgos: todo consistente."))
    else:
        print("\n  %s errores, %s avisos" % (
            rojo(str(len(errores))) if errores else "0",
            ambar(str(len(avisos))) if avisos else "0"))
    return len(errores)


def cmd_extraer(args):
    try:
        paquete, avisos = extraer(args.pgd)
    except Exception as exc:
        print(rojo("No se pudo leer el .pgd: %s" % exc))
        print(gris("Corre `inspeccionar` sobre el mismo archivo y comparte la salida."))
        return 1
    try:
        destino, rotado = guardar_paquete(paquete, args.salida)
    except IOError as exc:
        print(rojo(str(exc)))
        return 1
    print(negrita("\nExtraído de %s" % os.path.basename(os.path.expanduser(args.pgd))))
    print("  " + _resumen(paquete))
    con_casilla = sum(1 for r in paquete["rules"] if r.get("pgComb"))
    if paquete["rules"]:
        print("  %d de %d reglas traen su casilla de declinación" % (con_casilla, len(paquete["rules"])))
    for a in avisos:
        print(ambar("  AVISO  ") + a)
    print("\n" + verde("Guardado en %s" % destino))
    if rotado:
        print(gris("La versión anterior quedó en %s" % os.path.basename(rotado)))
    print(gris("El .pgd no se ha modificado."))
    return 0


def cmd_revisar(args):
    try:
        paquete = cargar_paquete(args.paquete)
    except Exception as exc:
        print(rojo("No se pudo leer el paquete: %s" % exc))
        return 1
    print(negrita("\n" + os.path.basename(os.path.expanduser(args.paquete))))
    print(gris("  " + _resumen(paquete)) + "\n")
    errores = _imprimir(revisar(paquete, args.ignorar))
    print("")
    return 1 if errores else 0


def cmd_probar(args):
    try:
        paquete = cargar_paquete(args.paquete)
    except Exception as exc:
        print(rojo("No se pudo leer el paquete: %s" % exc))
        return 1
    if not paquete["rules"]:
        print(ambar("El paquete no trae reglas."))
        return 0
    resultados = ensayar(paquete, args.muestras)
    cuenta = {"activa": 0, "inerte": 0, "error": 0, "sin-lexico": 0}
    print(negrita("\nEnsayo de %d regla(s) contra %d lexema(s)\n"
                  % (len(paquete["rules"]), len(paquete["lexicon"]))))
    for x in resultados:
        cuenta[x["estado"]] += 1
        if args.solo and x["estado"] != args.solo:
            continue
        color = {"activa": verde, "inerte": ambar, "error": rojo, "sin-lexico": gris}[x["estado"]]
        linea = "  %s  %s" % (color("%-11s" % x["estado"]), x["regla"].get("label"))
        if x["regla"].get("pos"):
            linea += gris(" · " + x["regla"]["pos"])
        if x["regla"].get("claseFiltro"):
            linea += gris(" [%s = %s]" % (x["regla"]["claseFiltro"], x["regla"].get("valorFiltro")))
        print(linea)
        print(gris("      /%s/ → \"%s\"" % (x["regla"].get("find"), x["regla"].get("replace"))))
        if x["error"]:
            print("      " + rojo(x["error"]))
        elif x["estado"] == "inerte":
            print(gris("      ninguna de las %d palabras de su alcance cambia" % x["candidatos"]))
        elif x["estado"] == "sin-lexico":
            print(gris("      su alcance no tiene palabras"))
        else:
            for a, b in x["muestras"]:
                print("      %s → %s" % (a, b))
            print(gris("      afecta a %d de %d" % (x["afectadas"], x["candidatos"])))
        print("")
    print(negrita("Resumen: ") + "%s activas · %s inertes · %s con error · %s sin léxico" % (
        verde(str(cuenta["activa"])),
        ambar(str(cuenta["inerte"])) if cuenta["inerte"] else "0",
        rojo(str(cuenta["error"])) if cuenta["error"] else "0",
        cuenta["sin-lexico"]))
    print(gris("Una regla inerte o con error no hace lo que crees.\n"))
    return 1 if cuenta["error"] else 0


def cmd_inyectar(args):
    try:
        paquete = cargar_paquete(args.paquete)
    except Exception as exc:
        print(rojo("No se pudo leer el paquete: %s" % exc))
        return 1
    pedidas = [s.strip() for s in args.secciones.split(",") if s.strip()]
    if "todo" in pedidas:
        pedidas = list(SECCIONES)
    malas = [s for s in pedidas if s not in SECCIONES]
    if malas:
        print(rojo("Sección desconocida: %s" % ", ".join(malas)))
        print(gris("Válidas: %s, todo" % ", ".join(SECCIONES)))
        return 1

    destino = os.path.expanduser(args.salida)
    if os.path.isdir(destino) or destino.endswith(("/", os.sep)):
        base, ext = os.path.splitext(os.path.basename(os.path.expanduser(args.pgd)))
        destino = os.path.join(destino, base + " (inyectado)" + ext)
    if os.path.abspath(destino) == os.path.abspath(os.path.expanduser(args.pgd)):
        print(rojo("La salida no puede ser el archivo de entrada."))
        return 1
    if os.path.exists(destino) and not args.sobrescribir:
        print(rojo("Ya existe %s" % destino))
        print(gris("Usa --sobrescribir para reemplazarlo."))
        return 1

    if not args.sin_revisar:
        hallazgos = [x for x in revisar(paquete) if x.nivel == ERROR]
        if hallazgos:
            print(negrita("\nEl paquete tiene %d error(es); no se escribe nada:\n" % len(hallazgos)))
            for x in hallazgos[:12]:
                print(x.linea())
            print(gris("\nCorrígelos, o usa --sin-revisar para escribir de todos modos.\n"))
            return 1

    try:
        informe, avisos, combs = inyectar(args.pgd, paquete, destino, pedidas, args.fuente)
    except Exception as exc:
        print(rojo("No se pudo escribir: %s" % exc))
        return 1

    print(negrita("\nEscrito %s" % destino))
    for k in SECCIONES:
        if k in pedidas:
            print("  %s %-11s %d" % (verde("✓") if informe.get(k) else gris("·"), k, informe.get(k, 0)))
    if combs:
        print(gris("\n  casillas resueltas por nombre de dimensión:"))
        for c in combs[:10]:
            print(gris("    " + c))
        if len(combs) > 10:
            print(gris("    … y %d más" % (len(combs) - 10)))
    for a in avisos:
        print(ambar("\n  AVISO  ") + a)
    print("\n" + gris("Cada sección escrita reemplaza la que hubiera. Tu .pgd de origen no se toca."))
    return 0


def cmd_ordenar(args):
    """Deja en la carpeta solo el .pgd, el paquete y su versión anterior."""
    carpeta = os.path.expanduser(args.carpeta)
    if not os.path.isdir(carpeta):
        print(rojo("No existe la carpeta %s" % carpeta))
        return 1

    conservar, sobrantes = [], []
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if nombre.startswith(".") or os.path.isdir(ruta):
            continue
        # Se conserva el diccionario de trabajo, el paquete y su respaldo.
        if nombre.endswith(".pgd") and "(" not in nombre:
            conservar.append((nombre, "diccionario de trabajo"))
        elif nombre in ("paquete.json", "paquete-anterior.json"):
            conservar.append((nombre, "paquete" if nombre == "paquete.json" else "respaldo"))
        else:
            sobrantes.append(nombre)

    print(negrita("\n%s" % carpeta))
    for nombre, papel in conservar:
        print("  %s %-46s %s" % (verde("conservar"), nombre[:46], gris(papel)))
    if not sobrantes:
        print(gris("\n  No hay nada de sobra.\n"))
        return 0
    for nombre in sobrantes:
        tam = os.path.getsize(os.path.join(carpeta, nombre))
        print("  %s %-46s %s" % (ambar("sobrante "), nombre[:46], gris("%.0f KB" % (tam / 1024))))

    if not args.borrar:
        print(gris("\n  Nada se ha borrado. Añade --borrar para eliminar los sobrantes.\n"))
        return 0
    for nombre in sobrantes:
        os.remove(os.path.join(carpeta, nombre))
    print("\n" + verde("%d archivo(s) eliminados." % len(sobrantes)) + "\n")
    return 0


def cmd_inspeccionar(args):
    try:
        raiz, nombre_xml, entradas = _abrir(args.pgd)
    except Exception as exc:
        print(rojo("No se pudo leer: %s" % exc))
        return 1
    lineas = ["# Estructura de %s" % os.path.basename(os.path.expanduser(args.pgd)), ""]
    if nombre_xml:
        lineas.append("Contenedor ZIP con %d entrada(s). XML principal: `%s`"
                      % (len(entradas), nombre_xml))
    else:
        lineas.append("XML plano, sin contenedor ZIP.")
    lineas.append("")
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
    lineas += ["## Árbol de etiquetas", "", "| Ruta | Veces | Ejemplo |", "|---|---|---|"]
    for ruta in sorted(conteo):
        lineas.append("| `%s` | %d | %s |" % (ruta, conteo[ruta],
                                              muestras.get(ruta, "").replace("|", "\\|")))
    ejes = declinaciones_de(raiz)
    if ejes:
        nombres = {}
        for nodo in raiz.findall("./partsOfSpeech/partOfSpeechNode"):
            nombres[_hijo(nodo, "partOfSpeechId")] = _hijo(nodo, "partOfSpeechName")
        lineas += ["", "## Declinaciones por categoría", ""]
        for pid, lista in sorted(ejes.items()):
            lineas.append("**%s**" % nombres.get(pid, "id " + pid))
            for eje in lista:
                dims = ", ".join("%s (%s)" % (d["nombre"], d["id"]) for d in eje["dimensiones"])
                lineas.append("- %s: %s" % (eje["nombre"] or "eje " + eje["id"], dims))
            lineas.append("")
    reporte = "\n".join(lineas)
    print(reporte)
    if args.salida:
        destino = os.path.expanduser(args.salida)
        with io.open(destino, "w", encoding="utf-8") as fh:
            fh.write(reporte)
        print(verde("\nGuardado en %s" % destino))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="tabure", description="Puente entre el cuaderno de tabure'shi y PolyGlot.")
    sub = p.add_subparsers(dest="comando")

    sp = sub.add_parser("extraer", help="Saca el contenido de un .pgd al paquete JSON")
    sp.add_argument("--pgd", required=True)
    sp.add_argument("--salida", default="paquete.json")
    sp.set_defaults(func=cmd_extraer)

    sp = sub.add_parser("revisar", help="Valida el paquete. No escribe nada")
    sp.add_argument("--paquete", required=True,
                    help="Archivo, o carpeta de la que se toma el paquete*.json más reciente")
    sp.add_argument("--ignorar", default=IGNORAR_POR_DEFECTO,
                    help="Caracteres que no se validan contra la fonología")
    sp.set_defaults(func=cmd_revisar)

    sp = sub.add_parser("probar", help="Aplica cada regla al léxico real y muestra qué produce")
    sp.add_argument("--paquete", required=True)
    sp.add_argument("--muestras", type=int, default=4)
    sp.add_argument("--solo", choices=["activa", "inerte", "error", "sin-lexico"],
                    help="Mostrar solo las reglas en ese estado")
    sp.set_defaults(func=cmd_probar)

    sp = sub.add_parser("inyectar", help="Escribe el paquete en una COPIA del .pgd")
    sp.add_argument("--pgd", required=True)
    sp.add_argument("--paquete", required=True)
    sp.add_argument("--salida", required=True)
    sp.add_argument("--secciones", default="todo",
                    help="Coma-separadas: %s, o «todo»" % ", ".join(SECCIONES))
    sp.add_argument("--fuente", default="Charis SIL")
    sp.add_argument("--sobrescribir", action="store_true")
    sp.add_argument("--sin-revisar", action="store_true",
                    help="Escribir aunque el paquete tenga errores")
    sp.set_defaults(func=cmd_inyectar)

    sp = sub.add_parser("ordenar",
                        help="Lista lo que sobra en la carpeta de trabajo y opcionalmente lo borra")
    sp.add_argument("--carpeta", required=True)
    sp.add_argument("--borrar", action="store_true", help="Eliminar de verdad los sobrantes")
    sp.set_defaults(func=cmd_ordenar)

    sp = sub.add_parser("inspeccionar", help="Describe la estructura interna de un .pgd")
    sp.add_argument("--pgd", required=True)
    sp.add_argument("--salida")
    sp.set_defaults(func=cmd_inspeccionar)

    args = p.parse_args(argv)
    for campo in ("pgd", "paquete", "salida", "carpeta"):
        v = getattr(args, campo, None)
        if isinstance(v, str) and v.startswith("~"):
            setattr(args, campo, os.path.expanduser(v))
    if not getattr(args, "func", None):
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
