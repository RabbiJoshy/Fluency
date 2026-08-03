# Zero-training masked-filler benchmark

## Headline

The pretrained masked model is useful for proposing and ranking fillers inside a deliberately reusable slot, but not as a standalone sentence-quality gate.

- No training or fine-tuning was performed; model: `dccuchile/bert-base-spanish-wwm-cased` at revision `c4d86612f51b4f46759c8390d1798c2febe71b93`.
- Ranked 3,096 single-token noun candidates from the first 10,000 vocabulary entries.
- Source-relative sentence scoring separated accepted from rejected pilot variants with only 50.0% pairwise accuracy.
- OpenSubtitles exact-construction counts are retained as an independent attestation signal, not treated as proof that an unattested filler is invalid.

## Slot results

| Construction | Top masked-model fillers | Top exact-corpus fillers | Probe ranks |
|---|---|---|---|
| ¿Quieres ver mi [MASK] nuevo? | auto, coche, juguete, juego, teléfono, vergüenza, libro, trabajo, anillo, televisor | cuarto (25), habitación (16), nuevo (9), placa (9), identificación (9), casa (7), colección (7), madre (5) | perro=28, camión=13, robot=51, coche=2, dinero=125, verano=350 |
| El [MASK] era muy caro. | alquiler, trabajo, servicio, precio, billete, dinero, coche, papel, combustible, viaje | OxyContin (2), seguro (1), taxi (1), tratamiento (1), pub (1), acero (1), alquiler (1), láton (1) | edificio=43, hotel=25, coche=7, perro=118, verano=276, dinero=6 |
| ¿Me puedes pasar esa [MASK]? | toalla, bolsa, cosa, pluma, botella, cámara, foto, llave, luz, cerveza | mermelada (1), ropa (1), toalla (1), cinta (1), clase (1) | tarjeta=11, botella=5, cerveza=10, escuela=586, iglesia=564, vida=511 |
| Si ellos están aquí, entonces, ¿quién está en el [MASK]? | edificio, mundo, lugar, cuarto, coche, equipo, avión, banco, auto, barco | teléfono (19), coche (15), auto (12), cuarto (11), comité (9), menú (8), hospital (7), lugar (5) | hospital=42, hotel=20, edificio=1, verano=1020, dinero=185, perro=312 |
| Cuando hace calor, nos gusta desayunar en la [MASK]. | cama, calle, mañana, plaza, casa, piscina, iglesia, mesa, noche, ciudad | cama (28), terraza (4), cocina (2), mañana (2), cena (2), cubierta (1), habitación (1), oficina (1) | escuela=24, iglesia=7, casa=5, cocina=n/a, playa=n/a, calle=2 |
| No voy a comprarlo sin [MASK]. | dinero, vergüenza, pruebas, embargo, permiso, razón, invitación, ayuda, protección, efectivo | más (1), ti (1), ella (1), licencia (1), mirarlo (1), preguntarte (1) | dinero=1, permiso=5, ayuda=8, miedo=185, verano=2416, perro=554 |

## Decision

Use masked-token rank as a cheap candidate-generator signal. Combine it with grammatical constraints and corpus construction evidence. Do not use whole-sentence pseudo-likelihood as the publication gate, and retain a semantic/naturalness review for combinations whose broader situation can be odd despite strong local probability.
