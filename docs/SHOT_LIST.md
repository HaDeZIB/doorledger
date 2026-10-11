# Lista de tomas — footage propio (para el flujo de la cuidadora y "paquete recogido")

**Por qué:** el simulador de Ring solo trae 3 escenas (paquete, vehículo, pájaros). Lo que no cubre
(la cuidadora mostrando su código y alguien recogiendo el paquete) lo filmamos nosotros. En el video
y en el README va etiquetado como **"Own footage"**; nunca lo hacemos pasar por video de Ring.

## Equipo
- **"Cámara del timbre":** tu iPhone en modo video, **horizontal**, lente **0.5x** (gran angular,
  se parece al ojo de pez del Ring). Pégalo con cinta al marco de la puerta a ~1.2–1.4 m de altura,
  apuntando hacia afuera y un poco hacia abajo. Si no puedes fijarlo, la Mac con Photo Booth sobre
  una silla también sirve.
- **"Teléfono de la cuidadora":** otro celular (o el de quien te ayude) con el **Caregiver Pass**
  abierto. Te paso el enlace cuando grabemos (lo genera el servidor con el código secreto de la visita).
- **Un paquete:** caja o bolsa de farmacia/hielera chica.
- **Actores:** alguien de "cuidadora" (bata o ropa clara si tienes) y alguien de "vecino/paciente".
- Luz de día, sin contraluz fuerte.

## Antes de grabar (2 min)
1. Te genero el enlace del pase y lo abres en el teléfono de la cuidadora; sube el brillo al 100%.
2. Comprueba la **hora del teléfono** (automática); el código cambia cada 15 s.
3. Graba **todo en una sola toma larga** por escena (mejor más largo que cortado).
4. Anota la **hora exacta** en que empiezas cada toma (o díctala en voz alta al inicio).

## Tomas
| # | Escena | Qué pasa | Duración | Clave |
|---|---|---|---|---|
| 1 | **Check-in de la cuidadora** | Llega caminando a la puerta, se detiene, **acerca el teléfono con el pase en "Check-in" a 30–50 cm de la cámara**, lo sostiene **quieto 3 s**, lo baja y "entra" | 20 s | Pantalla de frente a la lente, sin reflejos |
| 2 | **Check-out** | Sale por la puerta, cambia el pase a **"Check-out"**, lo muestra igual (30–50 cm, 3 s) y se va caminando | 20 s | Igual que la 1 |
| 3 | **Paquete en el porche** | Porche vacío 3 s → alguien deja el paquete en el tapete y se va → porche con paquete 10 s | 25 s | Que el paquete quede completo en cuadro |
| 4 | **Paquete recogido** | Porche con paquete 5 s → el "vecino" llega, lo levanta y se lo lleva → porche vacío 5 s | 20 s | Termina con el porche vacío |
| 5 | **(Opcional) Respaldo de 6 dígitos** | Como la 1, pero a ~80 cm (para mostrar el código numérico grande) | 15 s | |

## Después
Pásame los videos (AirDrop a la Mac → carpeta `~/ring-hackathon/doorledger/fixtures/raw/own/`)
con estos nombres (o dime cuál es cuál):

| Toma | Nombre de archivo |
|---|---|
| 1 Check-in | `checkin.mov` |
| 2 Check-out | `checkout.mov` |
| 3 Paquete dejado | `drop.mov` |
| 4 Paquete recogido | `pickup.mov` |

Yo corro `uv run python scripts/ingest_own_footage.py`: extrae cuadros, lee la hora de grabación
del video, verifica los códigos con el secreto de la visita (`fixtures/own_footage/visit.json`) y
el escenario del demo los usa automáticamente en lugar de los pasos "Simulated".
