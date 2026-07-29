#!/usr/bin/env python3
"""Crea la serie de vocales preposadas de la escritura Madera (šitakü).

La vocal que se lee antes de la consonante va debajo del trazo y girada 180°.
Como una marca solo puede seguir a su base en la cadena de caracteres, esa
lectura necesita puntos de código propios: no se puede resolver girando la
misma vocal por contexto.

Este script crea U+E032–U+E03B como **referencias** giradas 180° a las diez
vocales de U+E001–U+E00A. Al ser referencias y no copias, si mañana retocas
una vocal su versión preposada se corrige sola.

Cada una recibe el ancla de marca de la clase «abajo», situada en el punto que
toca la consonante — que tras el giro es el borde superior del dibujo.

Uso:
    python3 giradas_shitaku.py Shitaku_1.0-anclas.sfd
    python3 giradas_shitaku.py entrada.sfd -o salida.sfd --otf prueba.otf

Requiere el módulo fontforge (paquete python3-fontforge).
"""

import argparse
import os
import sys

try:
    import fontforge
except ImportError:  # pragma: no cover
    sys.exit("No encuentro el módulo fontforge. Instala python3-fontforge y "
             "ejecuta este script con el mismo Python contra el que se compiló.")

VOCALES = list(range(0xE001, 0xE00B))   # u o ã a è ø e î ü i
GIRADAS = 0xE032                        # primer punto de código de la serie preposada
NOMBRES = ["u", "o", "ã", "a", "è", "ø", "e", "î", "ü", "i"]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sfd", help="archivo .sfd de entrada")
    p.add_argument("-o", "--salida", help="archivo .sfd de salida")
    p.add_argument("--otf", metavar="ARCHIVO", help="generar además una fuente de prueba")
    p.add_argument("--rehacer", action="store_true", help="rehacer las que ya existan")
    args = p.parse_args()

    salida = args.salida or os.path.splitext(args.sfd)[0] + "-giradas.sfd"
    font = fontforge.open(args.sfd)

    creadas = existentes = sin_origen = 0
    for i, cp in enumerate(VOCALES):
        destino = GIRADAS + i
        if cp not in font:
            sin_origen += 1
            continue
        if destino in font and not args.rehacer:
            existentes += 1
            continue

        origen = font[cp]
        x1, y1, x2, y2 = origen.boundingBox()
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        g = font.createChar(destino, "uni%04X" % destino)
        g.clear()
        # giro de 180° alrededor del centro del dibujo
        g.addReference(origen.glyphname, (-1, 0, 0, -1, 2 * cx, 2 * cy))
        g.width = 0
        g.glyphclass = "mark"
        # tras el giro, el punto que toca la consonante queda arriba
        g.addAnchorPoint("abajo", "mark", round(cx), round(y2))
        g.comment = "vocal %s preposada — referencia girada de %s" % (NOMBRES[i], origen.glyphname)
        creadas += 1

    font.save(salida)
    if args.otf:
        font.generate(args.otf)

    print("Archivo escrito: %s" % salida)
    print("  vocales preposadas creadas ... %d  (U+%04X–U+%04X)" % (creadas, GIRADAS, GIRADAS + 9))
    if existentes:
        print("  ya existían .................. %d  (usa --rehacer para rehacerlas)" % existentes)
    if sin_origen:
        print("  sin vocal de origen .......... %d" % sin_origen)
    if args.otf:
        print("  fuente de prueba ............. %s" % args.otf)
    print("\nSon referencias: al retocar una vocal, su preposada se corrige sola.\n"
          "Para verlas en FontForge: Encoding ▸ Go to ▸ U+E032.")


if __name__ == "__main__":
    main()
