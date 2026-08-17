# tabure-polyglot

Puente entre el cuaderno web de **tabure'shi** y **PolyGlot**.

Un solo formato de datos —el paquete JSON, el mismo que usa el cuaderno— y cinco
comandos alrededor:

```
        .pgd  ──extraer──▶  paquete.json  ──inyectar──▶  .pgd nuevo
                                 │
                    revisar ◀────┴────▶ probar
```

Requiere Python 3.8 o superior y nada más. Verificado contra PolyGlot 3.6.1.

---

## Los cinco comandos

| Comando | Qué hace |
|---|---|
| `extraer` | Saca el contenido de un `.pgd` al paquete JSON. Solo lectura. |
| `revisar` | Valida el paquete y lista errores y avisos. No escribe. |
| `probar` | Aplica cada regla al léxico real y muestra qué produce. |
| `inyectar` | Escribe el paquete en una **copia** del `.pgd`. |
| `colocar` | Mueve el paquete exportado a la carpeta de trabajo, renombrado y rotado. |
| `ordenar` | Lista lo que sobra en la carpeta de trabajo y opcionalmente lo borra. |
| `inspeccionar` | Describe la estructura interna de un `.pgd`. Solo lectura. |

### extraer

```bash
python3 tabure.py extraer --pgd "~/Tabure/Tabure.pgd" --salida ~/Tabure/paquete.json
```

Produce la fonología (grafema, AFI, romanización y tecla de sustitución), el léxico,
las categorías con sus dimensiones, las reglas de conjugación con su casilla de
declinación, y las secciones de gramática. Ese JSON se pega en el cuaderno con
**Actualizar**.

### revisar

```bash
python3 tabure.py revisar --paquete ~/Tabure/paquete.json
```

**Fonología** — grafemas duplicados, romanizaciones ambiguas, grafemas sin AFI.

**Teclas de sustitución** — PolyGlot solo acepta un carácter de entrada, así que aquí
se concentran los fallos que rompen la escritura sin avisar: teclas de más de un
carácter, dos grafemas peleándose la misma tecla, una tecla que también es un grafema
real, y la más traicionera, una tecla que aparece dentro de una palabra del léxico.

**Cobertura** — segmenta cada palabra contra el inventario y reporta los caracteres
que uses sin haber declarado. Los dígrafos se reconocen por coincidencia más larga.
El apóstrofe se ignora: es marca de límite morfológico, no un fonema.

**Categorías y clases** — categorías usadas sin declarar, categorías sin descripción,
clases que apuntan a categorías inexistentes, palabras en alcance sin valor asignado.

**Check Language Tool** (calcado del que trae PolyGlot) — palabras que no coinciden con
el patrón de forma de su categoría (`pos[].pattern`), palabras sin definición o sin
pronunciación cuando su categoría las exige (`pos[].defMandatory` /
`pronMandatory`), y palabras duplicadas si `langProps.wordUniqueness` está activado.
Una palabra marcada `"excepcion": true` (el Override Lexical Rules de PolyGlot) queda
fuera de estos tres chequeos.

**Conjugación** — regex que no compila, casos de prueba que fallan, reglas sin anclar,
filtros de clase que no existen (ahora una regla puede traer varios a la vez, en
`filtros: [{clase, valor}, …]`; deben cumplirse todos), y el uso de `\1` donde PolyGlot
espera `$1`.

### probar

```bash
python3 tabure.py probar --paquete ~/Tabure/paquete.json --solo inerte
```

Clasifica cada regla en **activa** (modifica palabras), **inerte** (no cambia ninguna,
casi siempre síntoma de un patrón mal escrito), **error** y **sin léxico**. Respeta el
filtro de clase léxica de cada regla (ahora pueden ser varios a la vez).

Cuando una regla de PolyGlot tiene **varias transformaciones encadenadas** (un mismo
`decGenRule` con más de un `decGenTrans`), `extraer` las trae como filas separadas que
comparten `pgGrupo`. `probar` las vuelve a unir y las aplica **en cadena** — la salida
de la primera es la entrada de la segunda, tal como lo hace PolyGlot — en vez de
probar cada una aislada contra la palabra base, que daría un resultado distinto al
real. El cuaderno hace lo mismo al ensayar.

### inyectar

```bash
python3 tabure.py inyectar --pgd "~/Tabure/Tabure.pgd" \
    --paquete ~/Tabure/paquete.json --salida ~/Tabure/ --secciones todo
```

Secciones: `phonology`, `pos`, `lexicon`, `rules`, `grammar`, o `todo`.
`--sobrescribir` permite pisar una salida existente; `--sin-revisar` escribe aunque el
paquete tenga errores (por defecto se niega y los lista).

**Cada sección escrita reemplaza la que hubiera**: lo que no esté en el paquete
desaparece de esa sección. El resto del contenedor se copia intacto, incluida la
carpeta `reversion/` con el historial.

Lo que la escritura resuelve por ti:

- **Los ids de categoría se conservan por nombre.** Renumerarlos desconectaría las
  declinaciones, que apuntan a la categoría por su id; las categorías nuevas reciben
  un id libre.
- **La casilla de declinación de cada regla.** Una regla sin `decGenRuleComb` se guarda
  pero PolyGlot no la aplica a ninguna forma — es la causa más común de que una regla
  «no entre». Si la regla trae su casilla original, se conserva; si no, se resuelve
  emparejando su campo `dimension` (o su etiqueta) con una dimensión de su categoría.
  El comando informa de cada casilla que resolvió y de las que no pudo.
- **Los fonemas recuperan sus barras** (`tʃ` → `/tʃ/`), que es como PolyGlot los guarda.
- **Las transformaciones se reagrupan** en la regla original de la que salieron.

También escribe, con etiquetas ya verificadas contra el archivo real:

- **El patrón de forma y la obligatoriedad de definición/pronunciación** de cada
  categoría (`partOfSpeechPattern`, `definitionMandatoryPartOfSpeech`,
  `pronunciationMandatoryPartOfSpeech`).
- **La excepción a las reglas** de una palabra (`wordRuleOverride`), si el paquete la
  trae marcada con `"excepcion": true`.
- **La definición libre** de una palabra, por separado de su glosa: `gloss` va a
  `localWord` y `definicion` a `definition`. Antes se escribía el mismo valor en las
  dos, así que cualquier definición larga que hubieras escrito directo en PolyGlot se
  perdía en la siguiente inyección — ya no.

Las **clases léxicas no se escriben**: ese contenedor está vacío en el archivo de
referencia y su estructura interna no es conocida. Créalas a mano en PolyGlot. El
cuaderno sí modela sus tres tipos reales (cerrada, texto libre y asociativa) para
cuando llegue el momento de verificarlo.

Las **Language Properties** (`langProps` en el paquete: nombre, idioma local, autor,
orden alfabético, kerning y los checkboxes de unicidad/obligatoriedad/RTL) tampoco se
escriben todavía — sus etiquetas XML no están verificadas. `revisar` sí las lee para
decidir si aplica el chequeo de unicidad de palabra.

### inspeccionar

```bash
python3 tabure.py inspeccionar --pgd "~/Tabure/Tabure.pgd" --salida estructura.md
```

Además del árbol de etiquetas, lista **las declinaciones de cada categoría con el id de
cada dimensión** — que es lo que permite saber a qué casilla puede atarse una regla.

---

## Sintaxis de las reglas

PolyGlot está escrito en Java, así que las retro-referencias van con **`$1`**, no con
`\1`:

```
buscar:     ([aeiou])([^aeiou])$
reemplazar: $1$2$1s          ← arlan → arlanas
```

`revisar` marca como error el uso de `\1`, y esta herramienta traduce `$1` a la forma
que espera Python para que una regla dé el mismo resultado aquí que en la aplicación.

---

### colocar

El navegador siempre descarga a Descargas; no hay forma de elegir la carpeta desde el
propio artefacto. `colocar` cierra ese hueco: mueve el `paquete.json` recién
exportado a la carpeta de trabajo (la del `.pgd`, para tenerlo todo centralizado, o
cualquier otra que prefieras), rotando el anterior, y borra la copia de Descargas.

```bash
python3 tabure.py colocar --origen ~/Descargas --carpeta ~/Tabure
```

`--origen` también acepta una carpeta y toma el `paquete*.json` más reciente.

### La autoverificación de `inyectar`

Tras escribir, `inyectar` vuelve a leer el `.pgd` que acaba de producir y compara los
recuentos con lo que pedía escribir — incluidas las reglas que quedaron con casilla de
declinación asignada. No asume que la escritura fue fiel: lo comprueba.

## Dos archivos, no más

La carpeta de trabajo se queda con lo mínimo:

| Archivo | Papel |
|---|---|
| `Tabure'shi … .pgd` | el diccionario |
| `paquete.json` | los datos, reescritos en cada exportación |
| `paquete-anterior.json` | la versión previa, para volver atrás |

`extraer` rota el respaldo por su cuenta: antes de escribir, mueve el paquete actual
a `-anterior`. Y `--paquete` acepta una carpeta, tomando el `paquete*.json` más
reciente que encuentre — así apuntar a Descargas funciona aunque el navegador haya
guardado la segunda descarga como `paquete-1.json`.

```bash
# ver qué sobra, sin borrar nada
python3 tabure.py ordenar --carpeta ~/Personal/Tabure

# borrarlo
python3 tabure.py ordenar --carpeta ~/Personal/Tabure --borrar
```

Conserva el `.pgd` sin paréntesis en el nombre, el paquete y su respaldo; considera
sobrante todo lo demás, incluidos los `.pgd` marcados `(inyectado)` o
`(con gramática)` de ejecuciones anteriores.

## datos/tabureshi.json

Copia versionada del contenido de la lengua: fonología, categorías, clases, léxico,
reglas y las secciones de la gramática. Es el mismo paquete que viene incluido en el
cuaderno, y sirve de respaldo con historial.

## Sistemas de escritura

Los tres sistemas de tabure'shi —Madera (šitakü), Tierra (kapoṭa) y Agua (woʦaši)—
son alfabetos alternativos para la misma lengua (§2.1), así que cada uno debe cubrir
el inventario fonológico entero. `verificar_escritura.py` comprueba exactamente eso:

```bash
python3 verificar_escritura.py --sistema datos/silabario-madera.json \
                               --paquete datos/tabureshi.json
```

Detecta las tres formas de fallo —un grafema en dos grupos, un signo sin grafema, y
un grafema que ningún grupo recoge— y sale con código 1 si encuentra alguna.

`datos/silabario-madera.json` es la Tabla 2.1 de la gramática (§2.2.1) en forma
legible por máquina: los 11 grupos consonánticos con su vocal asociada y el portador
nulo. Contrastada contra el `.pgd`, cubre **44 de 44 grafemas sin huecos ni sobras**.

Para describir Tierra, Agua o un sistema nuevo, basta seguir ese mismo formato y
pasarlo por la herramienta. `entregas/` guarda el traspaso con el detalle y las
cuestiones abiertas.
