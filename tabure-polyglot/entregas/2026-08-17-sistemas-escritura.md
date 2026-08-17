<!-- formato: templates/common/handoff.md de onyx-moron/04-proyecto-tabure -->
# Entrega a la centralización de los sistemas de escritura

- ID: `04-20260817-handoff-sistemas-escritura`
- Área: `04`
- Fecha: 2026-08-17
- De: sesión «PoliGlot Tabure lexicon sync» (`claude/polyglot-tabure-lexicon-oleqlx`)
- Para: sesiones de sistemas de escritura y digitalización
- Estado: listo
- Sensibilidad: compartible
- Alcance: repositorio
- Estatuto Tabure: ver el estatuto declarado en cada punto
- Autoridad o ratificación: pendiente del usuario

## Objetivo y resultado esperado

Poner a disposición de quien esté centralizando los sistemas de escritura el material
que esta sesión tiene verificado contra el archivo PolyGlot real, y no contra
suposiciones: el inventario fonológico cerrado, la tabla del silabario Madera en
forma legible por máquina, y una herramienta que comprueba si un sistema de
escritura cubre el inventario.

## Trabajo realizado

**1. Inventario fonológico verificado — `HECHO_CONFIRMADO`.**
44 grafemas extraídos del `.pgd` real (no transcritos a mano): 34 consonantes y
10 vocales, cada uno con su AFI, su romanización cuando la tiene y su tecla de
sustitución. Está en `datos/tabureshi.json`, clave `phonology`.
19 de los 44 llevan tecla de sustitución porque no se teclean directamente.

**2. Tabla 2.1 del silabario Madera — `CANON`, transcrita de §2.2.1.**
Los 11 grupos consonánticos con su nombre, sus miembros y su vocal asociada,
en `datos/silabario-madera.json`. Incluye el portador nulo (Ø, tercer miembro del
grupo 11), los cinco símbolos reservados y el diferenciador gráfico ◌̯.

**3. Verificación de cobertura — `DEMOSTRACIÓN`.**
Contrastada la Tabla 2.1 contra el inventario del `.pgd`:

    34 consonantes + 10 vocales = 44 de 44 grafemas
    sin huecos, sin sobras, sin repeticiones

Es decir: el silabario Madera **agota exactamente** el inventario fonológico. No es
una aproximación ni una coincidencia parcial. Esto convierte al inventario en un
conjunto cerrado y verificado, que es justamente lo que necesita cualquier sistema
nuevo como especificación de partida.

**4. Herramienta reutilizable — `PROCEDIMIENTO`.**
`verificar_escritura.py` toma un sistema descrito en el mismo formato JSON de
grupos y lo contrasta contra la fonología de un paquete. Detecta las tres formas
de fallo: un grafema en dos grupos (escritura ambigua), un signo para un grafema
que no existe, y un grafema del inventario que ningún grupo recoge.

    python3 verificar_escritura.py --sistema datos/silabario-madera.json \
                                   --paquete datos/tabureshi.json

Sirve igual para Tierra (kapoṭa), Agua (woʦaši) o cualquier sistema en desarrollo.

## Archivos cambiados

| Archivo | Papel |
|---|---|
| `tabure-polyglot/datos/silabario-madera.json` | Tabla 2.1 legible por máquina |
| `tabure-polyglot/verificar_escritura.py` | verificación de cobertura |
| `tabure-polyglot/entregas/2026-08-17-sistemas-escritura.md` | este documento |

Nada se escribió en `04-proyecto-tabure`: ese repositorio declara
`mode: read_only_until_explicit_write_authorization` y
`cross_repository_writes_enabled: false`. El material queda aquí a la espera de
que el usuario decida si se traslada.

## Verificaciones ejecutadas

- Cobertura del silabario Madera contra los 44 grafemas: **correcta**, salida en 0.
- Prueba negativa de la herramienta: introducidos a propósito un hueco (`q̂` sin
  grupo), una repetición (`c` en dos grupos) y un signo fantasma (`Ϟ`); los tres
  se detectaron y la salida fue 1. La herramienta no aprueba por defecto.
- Normalización NFC aplicada antes de comparar: sin ella, `q̂` escrita como
  `q` + combinante no casaría con la del `.pgd`, y la verificación daría un
  falso negativo.

## Decisiones y evidencia

Ninguna decisión autoral tomada aquí. Todo lo marcado `CANON` procede de la
gramática descriptiva v1.1 y se cita con su sección.

## Pendientes, riesgos y contradicciones

**a) El canon declara tres sistemas, no cuatro — `CUESTIÓN ABIERTA`.**
§2.1 es explícito: «Tabure'shi cuenta, en su tradición literaria, con **tres**
sistemas de escritura distintos» —Madera, Tierra y Agua—, cada uno vinculado a un
elemento del esquema heptagonal del Anexo A (Madera 1, Tierra 2, Agua 5). Si el
trabajo en curso desarrolla un cuarto sistema, eso es legítimo, pero es una
`DECISIÓN AUTORAL`, no `CANON`: exige ratificación explícita y obliga a corregir
§2.1, §2.5 («Interoperabilidad entre los tres sistemas») y probablemente el Anexo A.
El contrato del área 04 lo dice en una línea: *no canonizar propuestas*. Lo señalo
para que quede registrado como decisión y no se deslice como hecho.

**b) Restricciones que hereda cualquier sistema nuevo — `CANON`.**
De §2.1: los tres sistemas son **fonográficos**, **mutuamente intercambiables** y
representan la misma lengua subyacente; se diferencian por registro, soporte o
contexto ritual, no por tipo de palabra. De ahí se sigue que un sistema nuevo debe
cubrir los 44 grafemas 1:1 —lo que la herramienta comprueba— y no puede repartirse
el léxico con otro sistema.
De §2.3: para Tierra se anticipa una organización consonántica *análoga* a la de
Madera, «aunque no necesariamente idéntica en su principio ordenador ni en sus
parámetros gráficos». Análoga, no calcada: el número de grupos y el criterio de
gradación quedan abiertos.

**c) El silabario sostiene la morfología verbal — `CANON`, §2.2.1.**
La correspondencia grupo→vocal se fijó con propósito gráfico, pero es el esqueleto
del paradigma verbal: los sufijos de Tiempo, Modo, Voz, Aspecto y Evidencialidad
(§7.2–§7.6) toman una consonante de un grupo y la vocal de ese mismo grupo.
**Consecuencia práctica:** tocar la asignación vocálica de Madera no es un cambio
gráfico, es un cambio morfológico. Un sistema nuevo con otra asignación no arrastra
ese problema —es un alfabeto alternativo— pero conviene saber que ahí hay un
acoplamiento que en Madera no se puede deshacer a la ligera.

**d) §2.2 «Madera (šitakü)» está vacía — `PENDIENTE`.**
El encabezado existe y sus subsecciones §2.2.1–§2.2.5 tienen contenido, pero la
sección madre no. Puede ser correcto (un encabezado de agrupación) o puede faltar
texto introductorio. No lo he tocado.

**e) Aviso de audiencia — `ERROR_DETECTADO` potencial.**
Este material vive en `onyx-moron/claude-code`, que es un repositorio **público**,
mientras que los diez repositorios del sistema de Organización (00–09) son
**privados**. La fonología, el léxico y las secciones de gramática de tabure'shi ya
estaban ahí antes de esta entrega, así que no he cambiado la exposición de nada;
pero si la centralización pretende consolidar el material bajo el área 04, conviene
decidir la audiencia a propósito y no por herencia.

## Próxima acción observable

Del lado del usuario, una decisión: si el material se traslada al área 04 —lo que
requiere autorización expresa de escritura— y si el cuarto sistema se registra como
decisión autoral.

Del lado de quien desarrolle Tierra, Agua o el cuarto sistema: describir el sistema
en el formato de `datos/silabario-madera.json` y pasarlo por `verificar_escritura.py`
antes de darlo por cerrado. Si cubre los 44 sin huecos, es intercambiable con Madera
en el sentido de §2.1.

## Issue, rama o pull request

Rama `claude/polyglot-tabure-lexicon-oleqlx` en `onyx-moron/claude-code`, PR #1.
