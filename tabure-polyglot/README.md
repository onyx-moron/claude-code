# tabure-polyglot

Puente entre un vault de **Obsidian** y **PolyGlot** para el trabajo sobre la lengua
tabure'shi.

A diferencia del cuaderno web, esto corre en **tu propia máquina**, así que sí tiene
acceso real al disco: lee las notas de tu vault, las valida, y escribe los archivos
que PolyGlot importa.

```
Obsidian (donde escribes)
    ↓  tabure.py revisar   ← detecta incoherencias
    ↓  tabure.py exportar  ← genera CSV + Markdown
PolyGlot (Import from File)
```

---

## Instalación

No hay instalación. Solo necesitas Python 3.8 o superior, que ya viene en macOS y
Linux (en Windows se descarga de python.org).

```bash
python3 tabure.py --help
```

Si tienes `PyYAML` instalado se usa automáticamente; si no, el script trae su propio
lector de frontmatter y funciona igual.

---

## Los cinco comandos

| Comando | Qué hace |
|---|---|
| `extraer` | Saca todo el contenido de tu `.pgd` al formato del cuaderno. Solo lectura. |
| `revisar` | Valida el vault y muestra errores y avisos. No escribe nada. |
| `exportar` | Valida y genera los archivos para PolyGlot. |
| `vigilar` | Repite `exportar` automáticamente cada vez que guardas una nota. |
| `inspeccionar` | Describe la estructura interna de tu archivo `.pgd`. Solo lectura. |
| `importar-cuaderno` | Convierte el respaldo JSON del cuaderno web en notas del vault. |

### Sacar lo que ya tienes en PolyGlot

Si tu diccionario ya tiene trabajo hecho, este es el punto de partida: no hay que
volver a escribir nada.

```bash
python3 tabure.py extraer --pgd ~/Tabure/Tabure.pgd --salida ~/Desktop/paquete.json
```

Lee el `.pgd` **sin modificarlo** y produce un JSON con la fonología (grafema, AFI,
romanización y tecla de sustitución), el léxico, las categorías con sus dimensiones,
las reglas de conjugación y las secciones de gramática. Ese JSON se pega en el
cuaderno web con **Actualizar**.

De dónde sale cada dato:

| En el cuaderno | En PolyGlot |
|---|---|
| Grafema y AFI | Guía de pronunciación (`proGuide`) |
| Romanización | Guía de romanización (`romGuide`) |
| Tecla de sustitución | Sustitución de caracteres (`langPropCharRep`) |
| Dimensiones de una categoría | Declinaciones enlazadas a esa categoría |
| Reglas de conjugación | Cada transformación del generador, por separado |

Verificado contra PolyGlot 3.6.1. Si tu versión guarda las cosas con otros nombres,
`inspeccionar` te lo dirá.

### Empezar desde el cuaderno web

Si ya tienes datos en el cuaderno, descarga el JSON (botón **Descargar JSON**) y
siembra el vault con él:

```bash
python3 tabure.py importar-cuaderno ~/Descargas/tabureshi-cuaderno-backup.json \
    --vault ~/Obsidian/Tabure
```

### El ciclo de trabajo diario

```bash
# Mientras escribes en Obsidian, deja esto corriendo en una terminal:
python3 tabure.py vigilar --vault ~/Obsidian/Tabure --salida ~/Tabure/polyglot
```

Cada vez que guardas una nota, revalida todo y regenera los archivos. Luego, en
PolyGlot: **Archivo → Import from File**, eliges `lexicon.csv` y mapeas las columnas.

---

## Cómo se escriben las notas

La herramienta reconoce una nota por su campo `tipo:` o por la carpeta donde está
(`Lexicon/`, `Conjugaciones/`, `Gramatica/`, `Categorias/`, `Fonologia.md`). Los
nombres de campo aceptan sinónimos: `palabra` o `lexema`, `glosa` o `definicion`,
`romanizacion` o `transcripcion`, etc.

### Un lexema — `Lexicon/sherema.md`

```markdown
---
tipo: lexema
palabra: sherema
ipa: ʃeˈɾema
romanizacion: sherema
pos: sustantivo
glosa: nube
etimologia: de *sher- "vapor" + -ema
estado: verificado
---

Cualquier nota libre va aquí abajo.
```

### El inventario fonológico — `Fonologia.md`

Una sola nota con una tabla. Los dígrafos (`sh`) se reconocen por coincidencia más
larga, así que `sherema` se segmenta como `sh-e-r-e-m-a`, no `s-h-...`.

```markdown
---
tipo: fonologia
---

| Grafema | IPA | Romanización | Reemplazo | Notas |
|---|---|---|---|---|
| č | tʃ | ch | 1 | se escribe tecleando 1 |
| sh | ʃ | sh |  | dígrafo |
| ' | ʔ | ' |  | oclusiva glotal |
```

La columna **Reemplazo** es la *tecla de sustitución* de PolyGlot, que solo admite
**un carácter de entrada**: al teclear `1` aparece `č`. Se deja vacía en los
grafemas que ya se escriben directamente con el teclado.

### Una regla de conjugación — `Conjugaciones/pasado.md`

```markdown
---
tipo: regla
etiqueta: Pasado — verbos terminados en -a
pos: verbo
buscar: a$
reemplazar: e
flags: ""
pruebas:
  - entrada: tama
    esperado: tame
---
```

Los `pruebas` son el punto importante: la herramienta ejecuta cada caso y te avisa
si la regla deja de producir el resultado esperado.

### Una categoría — `Categorias/verbo.md`

```markdown
---
tipo: pos
etiqueta: verbo
dimensiones: [tiempo, aspecto, persona, número]
---
```

### Una sección de gramática — `Gramatica/01-morfologia-verbal.md`

```markdown
---
tipo: gramatica
etiqueta: Morfología verbal
orden: 1
---

El cuerpo de la sección, en Markdown normal.
```

---

## Qué valida `revisar`

**Fonología** — grafemas duplicados; romanizaciones ambiguas (dos grafemas que se
transcriben igual); grafemas sin IPA.

**Teclas de sustitución** — como PolyGlot solo acepta un carácter de entrada, aquí
se concentran los fallos que rompen la escritura sin avisar: teclas de más de un
carácter; dos grafemas peleándose la misma tecla; una tecla que también es un
grafema real de la lengua (se sustituiría sola); y el más traicionero, una tecla que
aparece dentro de una palabra del léxico, que haría imposible teclear esa palabra.
También avisa de grafemas no tecleables que se quedaron sin tecla asignada.

```
ERROR  teclas       Tecla repetida «1»: la usan «š» y «ž»
ERROR  teclas       La tecla «1» (de «š») aparece dentro de palabras del léxico
                    (ta1ma): al teclearlas se sustituiría
```

**Cobertura** — el chequeo más útil: segmenta cada palabra del léxico contra el
inventario y reporta cualquier carácter que uses en una palabra pero no hayas
declarado en Phonology. También señala grafemas declarados que ningún lexema usa.

```
ERROR  cobertura    El carácter «q» [LATIN SMALL LETTER Q] aparece en el léxico
                    pero no está en Phonology (qwixa)
```

**Parts of Speech** — categorías usadas en el léxico pero no declaradas; categorías
declaradas sin lexemas; categorías sin dimensiones de conjugación.

**Conjugación** — regex que no compila; casos de prueba que fallan (con el resultado
real vs. el esperado); reglas sin anclar (`^`/`$`), que es la causa más común de que
el Autogenerator de PolyGlot altere el interior de una palabra; reglas que apuntan a
una categoría inexistente; reglas muertas que no modifican ningún lexema.

```
ERROR  conjugación  «Prueba que falla»: tama → toma, se esperaba tamo
AVISO  conjugación  «Prueba que falla» no está anclada (sin ^ ni $)
```

**Gramática** — secciones vacías, números de orden repetidos.

`revisar` y `exportar` salen con código 1 si hay errores, así que puedes encadenarlos
en un script.

---

## Archivos que genera `exportar`

| Archivo | Para qué |
|---|---|
| `lexicon.csv` | Importar en PolyGlot con el asistente Import from File. |
| `fonologia.csv` | Referencia al llenar la pestaña Phonology. |
| `conjugaciones.csv` | Referencia al llenar el Conjugation Autogenerator. |
| `gramatica.md` | Pegar en el libro de Grammar. |
| `informe.md` | El resultado de la revisión, para guardarlo en el vault. |

---

## Sobre escribir directamente en el `.pgd`

El comando `inspeccionar` abre tu archivo de PolyGlot **sin modificarlo** y describe
su estructura XML real:

```bash
python3 tabure.py inspeccionar --pgd ~/Tabure/Tabure.pgd --salida estructura.md
```

Esto existe porque el formato `.pgd` no está documentado públicamente y varía entre
versiones de PolyGlot: escribir en él a ciegas corrompería el archivo. El camino
seguro es mirar primero la estructura de *tu* archivo y recién entonces añadir
escritura directa.

Por ahora la herramienta **no escribe en el `.pgd`**, a propósito. La importación por
CSV es reversible y no puede dañar tu diccionario.

Haz siempre una copia de tu `.pgd` antes de importar nada.

---

## Carpeta `ejemplos/`

Un vault mínimo y funcional con datos de muestra (no son datos reales de tabure'shi;
reemplázalos). Sirve para ver la herramienta funcionando antes de apuntarla a tu vault:

```bash
python3 tabure.py revisar --vault ejemplos
```
