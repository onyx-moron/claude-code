#!/usr/bin/env python3
"""Prepara el anclaje de vocales de la escritura Madera (šitakü) en un .sfd.

Hace cuatro cosas sobre una copia del archivo, sin tocar el original:

  1. Crea la lookup GPOS de marca sobre base y le cuelga las clases de
     anclaje «arriba» y «abajo», que hoy existen sueltas en el archivo.
  2. Pone a cero el avance de las diez vocales, para que la marca no
     empuje el texto.
  3. Coloca en cada base que no la tenga un ancla «arriba» y otra «abajo»,
     a una altura fija común y centradas sobre la mancha del trazo.
  4. Coloca en cada vocal que no lo tenga el ancla de marca complementaria.

Las anclas que ya existan se respetan. Las alturas son un punto de partida
uniforme: se ajustan después a ojo, glifo por glifo, en la ventana de
FontForge (Point ▸ Add Anchor Point para ver y arrastrar las existentes).

Uso:
    python3 anclas_shitaku.py Shitaku_1.0.sfd
    python3 anclas_shitaku.py Shitaku_1.0.sfd -o Shitaku_1.1.sfd --arriba 560

Requiere el módulo fontforge (paquete python3-fontforge).
"""

import argparse
import os
import sys

try:
    import fontforge
except ImportError:  # pragma: no cover
    sys.exit("No encuentro el módulo fontforge. Instala python3-fontforge "
             "y ejecuta este script con el mismo Python contra el que se compiló.")

PORTADOR = 0xE000
VOCALES = range(0xE001, 0xE00B)      # diez vocales, secuencia u-o-ã-a-è-ø-e-î-ü-i
CONSONANTES = range(0xE00B, 0xE02D)  # 34 consonantes, grupos 1 a 11

LOOKUP = "vocales"
SUBTABLA = "vocales-1"
CLASES = ("arriba", "abajo")


def bases(font):
    for cp in [PORTADOR] + list(CONSONANTES):
        if cp in font:
            yield font[cp]


def marcas(font):
    for cp in VOCALES:
        if cp in font:
            yield font[cp]


def clases_del_glifo(glifo):
    return {a[0] for a in glifo.anchorPoints}


def centro_tinta(glifo):
    """x del centro de la mancha; None si el glifo está vacío."""
    x1, y1, x2, y2 = glifo.boundingBox()
    if x1 == x2 == 0 and y1 == y2 == 0:
        return None
    return round((x1 + x2) / 2)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sfd", help="archivo .sfd de entrada")
    p.add_argument("-o", "--salida", help="archivo .sfd de salida (por defecto, «-anclas» junto al original)")
    p.add_argument("--arriba", type=int, default=550, help="altura del ancla superior (por defecto 550)")
    p.add_argument("--abajo", type=int, default=-100, help="altura del ancla inferior (por defecto -100)")
    p.add_argument("--sin-ceros", action="store_true", help="no tocar el avance de las vocales")
    p.add_argument("--otf", metavar="ARCHIVO", help="generar además una fuente de prueba")
    args = p.parse_args()

    salida = args.salida or os.path.splitext(args.sfd)[0] + "-anclas.sfd"
    font = fontforge.open(args.sfd)

    informe = {"lookup": False, "anclas_base": 0, "anclas_marca": 0,
               "avances": 0, "respetadas": 0, "descentradas": [], "vacios": []}

    # 1. lookup GPOS de marca sobre base
    if LOOKUP not in font.gpos_lookups:
        font.addLookup(LOOKUP, "gpos_mark2base", (),
                       (("mark", (("DFLT", ("dflt",)), ("latn", ("dflt",)))),))
        font.addLookupSubtable(LOOKUP, SUBTABLA)
        for clase in CLASES:
            font.addAnchorClass(SUBTABLA, clase)
        informe["lookup"] = True

    # 2. avance cero en las vocales
    if not args.sin_ceros:
        for glifo in marcas(font):
            if glifo.width != 0:
                glifo.width = 0
                informe["avances"] += 1

    # 3. anclas base
    for glifo in bases(font):
        cx = centro_tinta(glifo)
        if cx is None:
            informe["vacios"].append(glifo.glyphname)
            continue
        if abs(cx - glifo.width / 2) > 200:
            informe["descentradas"].append(glifo.glyphname)
        puestas = clases_del_glifo(glifo)
        for clase, altura in (("arriba", args.arriba), ("abajo", args.abajo)):
            if clase in puestas:
                informe["respetadas"] += 1
                continue
            glifo.addAnchorPoint(clase, "base", cx, altura)
            informe["anclas_base"] += 1
        glifo.glyphclass = "baseglyph"

    # 4. anclas de marca: el punto de contacto va en la base de la mancha
    for glifo in marcas(font):
        if clases_del_glifo(glifo):
            informe["respetadas"] += 1
            continue
        x1, y1, x2, y2 = glifo.boundingBox()
        if x1 == x2 == 0 and y1 == y2 == 0:
            informe["vacios"].append(glifo.glyphname)
            continue
        glifo.addAnchorPoint("arriba", "mark", round((x1 + x2) / 2), round(y1))
        glifo.glyphclass = "mark"
        informe["anclas_marca"] += 1

    font.save(salida)
    if args.otf:
        font.generate(args.otf)

    print("Archivo escrito: %s" % salida)
    print("  lookup GPOS creada .......... %s" % ("sí" if informe["lookup"] else "ya existía"))
    print("  anclas base añadidas ........ %d" % informe["anclas_base"])
    print("  anclas de marca añadidas .... %d" % informe["anclas_marca"])
    print("  anclas ya existentes ........ %d (intactas)" % informe["respetadas"])
    print("  avances puestos a cero ...... %d" % informe["avances"])
    if args.otf:
        print("  fuente de prueba ............ %s" % args.otf)
    if informe["descentradas"]:
        print("\n  Revisar: la mancha queda muy descentrada respecto del avance, así que\n"
              "  el ancla nace fuera de sitio en %s" % ", ".join(informe["descentradas"]))
    if informe["vacios"]:
        print("\n  Sin dibujo, no se anclaron: %s" % ", ".join(informe["vacios"]))
    print("\nSiguiente paso en FontForge: abrir un glifo del grupo 1, ajustar la altura\n"
          "de sus dos anclas a ojo y propagar ese valor con --arriba/--abajo.")


if __name__ == "__main__":
    main()
