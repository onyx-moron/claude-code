#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verificar_escritura.py — Contrasta un sistema de escritura contra el inventario real.

Un sistema de escritura de tabure'shi es un alfabeto alternativo para la MISMA
lengua subyacente (§2.1), así que debe cubrir el inventario fonológico entero:
cada grafema declarado en Phonology necesita un signo, y ningún signo puede
apuntar a un grafema que no existe.

Esta herramienta comprueba justamente eso, y sirve igual para Madera (šitakü),
que ya está documentado, y para Tierra (kapoṭa), Agua (woʦaši) o cualquier
sistema en desarrollo: basta describirlo en el mismo JSON de grupos.

    python3 verificar_escritura.py --sistema datos/silabario-madera.json \\
                                   --paquete datos/tabureshi.json

Requiere Python 3.8+ y solo la biblioteca estándar.
"""

import argparse
import json
import os
import sys
import unicodedata

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(t, code):
    return "\033[%sm%s\033[0m" % (code, t) if _COLOR else t


def rojo(t): return _c(t, "31")
def ambar(t): return _c(t, "33")
def verde(t): return _c(t, "32")
def gris(t): return _c(t, "90")
def negrita(t): return _c(t, "1")


def norm(s):
    """NFC: sin esto, q̂ escrito como q+combinante no casa con el del .pgd."""
    return unicodedata.normalize("NFC", s or "")


def cargar(ruta):
    with open(os.path.expanduser(ruta), "r", encoding="utf-8") as fh:
        return json.load(fh)


def signos_de(sistema):
    """Devuelve (consonantes, vocales) tal como las declara el sistema, en orden."""
    consonantes, vocales = [], []
    for grupo in sistema.get("grupos") or []:
        for c in grupo.get("consonantes") or []:
            consonantes.append((norm(c), grupo.get("n"), grupo.get("nombre")))
        v = grupo.get("vocal")
        if v:
            vocales.append((norm(v), grupo.get("n"), grupo.get("nombre")))
    return consonantes, vocales


def verificar(sistema, fonologia):
    inventario = {norm(p.get("char")): p for p in fonologia if p.get("char")}
    consonantes, vocales = signos_de(sistema)
    asignados = consonantes + vocales

    hallazgos = []

    # Un grafema en dos grupos haría ambigua la escritura.
    visto = {}
    for g, n, nombre in asignados:
        if g in visto:
            hallazgos.append((
                "error",
                "«%s» aparece en el grupo %s (%s) y también en el %s (%s)"
                % (g, visto[g][0], visto[g][1], n, nombre)))
        else:
            visto[g] = (n, nombre)

    # Un signo para un grafema inexistente: sobra, o la fonología cambió.
    for g, n, nombre in asignados:
        if g not in inventario:
            hallazgos.append((
                "error",
                "«%s» (grupo %s, %s) no está en el inventario fonológico" % (g, n, nombre)))

    # Un grafema sin signo no se puede escribir en este sistema.
    for g in inventario:
        if g not in visto:
            hallazgos.append((
                "error",
                "«%s» está en el inventario y ningún grupo lo recoge" % g))

    return hallazgos, inventario, consonantes, vocales


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--sistema", required=True,
                        help="JSON del sistema de escritura (grupos con consonantes y vocal)")
    parser.add_argument("--paquete", required=True,
                        help="paquete.json o carpeta; de ahí sale la fonología")
    args = parser.parse_args(argv)

    try:
        sistema = cargar(args.sistema)
        paquete = cargar(args.paquete)
    except (OSError, ValueError) as exc:
        print(rojo("No se pudo leer: %s" % exc))
        return 1

    fonologia = paquete.get("phonology") or []
    if not fonologia:
        print(ambar("El paquete no trae fonología: no hay contra qué contrastar."))
        return 1

    hallazgos, inventario, consonantes, vocales = verificar(sistema, fonologia)

    nombre = sistema.get("sistema") or "(sin nombre)"
    nativo = sistema.get("nombre_nativo")
    print(negrita("\n%s%s — %d grupo(s)\n"
                  % (nombre, " (%s)" % nativo if nativo else "",
                     len(sistema.get("grupos") or []))))

    for grupo in sistema.get("grupos") or []:
        cs = " ".join(grupo.get("consonantes") or [])
        v = grupo.get("vocal")
        extra = grupo.get("portador_nulo")
        print("  %2s %-14s %-22s %s%s"
              % (grupo.get("n"), grupo.get("nombre") or "", cs,
                 gris("vocal " + v) if v else gris("sin vocal"),
                 gris("  + portador nulo " + extra) if extra else ""))

    print()
    if hallazgos:
        for nivel, texto in hallazgos:
            print("  %s %s" % (rojo("✗") if nivel == "error" else ambar("!"), texto))
        print(rojo("\n  %d problema(s): el sistema no cubre el inventario." % len(hallazgos)))
    else:
        print("  %s %d consonante(s) + %d vocal(es) = %d de %d grafemas, sin huecos ni sobras"
              % (verde("✓"), len(consonantes), len(vocales),
                 len(consonantes) + len(vocales), len(inventario)))
        print(gris("     Cada grafema del .pgd tiene exactamente un signo en este sistema."))

    print()
    return 1 if hallazgos else 0


if __name__ == "__main__":
    sys.exit(main())
