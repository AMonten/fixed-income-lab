# Roadmap — fixed-income-lab

Documento de planificación vivo. Fusiona tres revisiones externas independientes del
repo (dos originales — una con ejecución de código y evidencia reproducible, otra
puramente de diseño/arquitectura sin correr la suite — más verificación propia de los
hallazgos más graves) y una tercera revisión de esta v2, centrada en semántica de
mercado y consistencia interna del documento mismo. Reemplaza como fuente de
planificación a la sección `## Roadmap` del `README.md` (esa sección se actualiza una
vez que las decisiones acá abajo estén tomadas y ejecutadas — no antes, para no
duplicar estado en dos lugares).

**Cómo se usa este archivo**: cada ítem tiene un estado (`pendiente` /
`en progreso` / `hecho` / `descartado`). Actualizar el estado a medida que se
trabaja, no crear un doc de progreso aparte. El **Anexo** al final es la lista de
cosas que no están confirmadas — ni por mí (sin verificar en código o con evidencia
débil) ni por Alberto (decisiones que dependen de su contexto de negocio) — revisarlo
antes de asumir que algo del cuerpo principal es definitivo.

---

## Estado actual (2026-09-12)

- `pyproject.toml`: versión `0.1.0`, `Development Status :: 4 - Beta`. README narra
  "V1 feature-complete". Inconsistente — ver Bloque 6.
- 118 tests, ~97% coverage, 0 tests anclados contra un valor externo (QuantLib u
  otro). Coverage alto, validación financiera independiente inexistente.
- Instrumentos: `Bond` (bullet), `ZeroCouponBond`, `FloatingRateNote`,
  `AmortizingBond` (level/explicit/factor-driven).
- Day-count: ACT/360, ACT/365F, 30/360 US. Falta ACT/ACT (ICMA/ISDA), 30E/360.
- Calendario de días hábiles: `weekday() < 5` únicamente — sin feriados, sin
  calendario configurable.
- `YieldCurve`: tenor→zero-rate con interpolación linear/log-linear/flat.
  `LOG_LINEAR` interpola la zero rate (rompe con tasas negativas).
- **Regla de actualización de esta sección**: se actualiza con cada PR que cambie
  alguno de estos hechos, o se borra — no debe quedar como snapshot fechado dentro
  de un documento que se sigue editando.

---

## Bloque 0 — Bugs confirmados y el mismatch de convención (fix inmediato, bloquean todo lo demás)

Esta sección mezclaba, bajo una sola etiqueta de "no son debatibles, son bugs",
cuatro naturalezas distintas de hallazgo. Esa etiqueta solo es exacta para los
defectos de correctitud. Se separa en tres categorías — **0A**, **0B**, **0C** —
más el ítem **0.1**, que no es un bug en el sentido tradicional sino un mismatch de
semántica de mercado ya resuelto (ver abajo), y por eso se trata aparte, fuera de
0A/0B/0C.

**Criterio de hecho, uniforme para todo este bloque**: existe un test que falla en
`main` antes del fix y pasa después.

### 0.1 — El pricing basado en yield deriva los exponentes de descuento de fracciones day-count hasta la fecha de pago ajustada, en vez de hacerlo desde la convención de cotización de yield del instrumento

No es un bug de fecha, es un mismatch de semántica de tiempo: hay **dos cálculos
distintos** que hoy comparten una sola noción de `t`.

- **Yield cotizado (street).** `P = Σ CF_k / (1 + y/m)^(w+k)`, donde el tiempo se
  construye contando **períodos de cupón contractuales**. Si un cupón vence sábado
  y se paga lunes, esos dos días **no** deben entrar en el exponente. Acá la
  invariante `coupon = yield en fecha de cupón regular ⇒ clean price = 100` es
  correcta y exigible.
- **PV con curva de descuento.** `PV = Σ CF_i · DF(payment_date_i)`. Acá el dinero
  llega el lunes, así que **usar la fecha de pago ajustada es exactamente lo
  correcto**.

`present_value()` (`pricing/present_value.py:38`) deriva `t` con
`day_count.year_fraction(settlement_date, cf.payment_date)` — la fecha de pago
ajustada — para las dos cosas a la vez, mientras `cashflows/generator.py:72` devenga
el cupón con fechas sin ajustar (`accrual_start`/`accrual_end`). El híbrido
resultante no corresponde a ninguna convención de mercado real.

**Prohibido** el fix global `cf.payment_date → cf.accrual_end` dentro de
`present_value()`: arreglaría el YTM pero rompería el pricing por curva, que
necesita la fecha real de pago para descontar correctamente.

**Default — ya no depende de un criterio de negocio abierto**: street / fechas sin
ajustar es el default del yield cotizado; descontar sobre fechas de pago reales es
la variante que el mercado llama **true yield**, expuesta como opción explícita.
Las dos son legítimas y tienen nombre; lo que no es legítimo es el híbrido actual,
donde el devengo usa un criterio y el descuento otro y el resultado no corresponde
a ninguna cotización real.

| Evidencia | Archivo | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|
| Reproducido: ACT/365 → 99.997019, 30/360 → 99.997379, 30/360+`NONE` → 100.0000000000 | `pricing/present_value.py:38` vs `cashflows/generator.py:72` | [#4](https://github.com/AMonten/fixed-income-lab/issues/4) | El entregable inmediato **no es el fix**, es el test de regresión: escribir hoy `test_par_bond_prices_to_exactly_100`, marcado `xfail`, que pasa a verde cuando aterrice la separación de responsabilidades del Bloque 1 (mismo test alimenta el invariante par→100 de Bloque 5). | pendiente |

### 0A — Defectos de correctitud (producen un número incorrecto)

| # | Ítem | Evidencia | Archivo | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|---|---|
| 0.2 | `YieldCurve(tenors=(1,2,2,5))` acepta duplicados en silencio — el check `list(tenors) != sorted(tenors)` no detecta repetidos porque `(1,2,2,5)` ya está ordenada. Reproducido en vivo. | verificado | `pricing/curves.py:55` | [#5](https://github.com/AMonten/fixed-income-lab/issues/5) | Test de regresión (ver regla uniforme del bloque). | pendiente |
| 0.3 | `YieldCurve(tenors=(-1,5))` acepta tenor negativo; `discount_factor(-1) = 1.03`. Reproducido en vivo. | verificado | `pricing/curves.py` | [#6](https://github.com/AMonten/fixed-income-lab/issues/6) | Test de regresión (ver regla uniforme del bloque). | pendiente |
| 0.5 | `ExplicitAmortizationPlan` trunca en silencio la sobre-amortización (`max(..., 0)`) en vez de fallar. El defecto real no es que `sum(repayments)` deba dar siempre `original_face` — `100 = 20+20+20` con balloon de 40 al vencimiento es una estructura válida — sino que hoy no hay forma de distinguir "no suma porque hay balloon" de "no suma porque hay un bug". Rediseño de semántica que resuelve esto de raíz (no bloqueante para el fix inmediato): dos tipos explícitos, `FullyAmortizingPlan` (invariante `Σ principal = face`) y `PartialAmortizationPlan` (`Σ principal ≤ face`, con la política de balance terminal tratada explícitamente). | leído en código | `instruments/amortizing.py` | [#8](https://github.com/AMonten/fixed-income-lab/issues/8) | Test de regresión: sobre-amortizar falla (en vez de truncarse en silencio) en cualquiera de los dos tipos. | pendiente |
| 0.6 | `FactorHistory` no distingue una secuencia de **observaciones** (que admite revisiones legítimas — una corrección de vendor puede legítimamente subir un factor previamente incorrecto) de un **factor path proyectado** (que sí debe ser estrictamente no creciente); tampoco rechaza `(effective_date, as_of)` duplicado, que sí es siempre un error. El bug de esta fila es el sobrescribir silencioso, no la falta de monotonicidad estricta. Modelo propuesto: `FactorObservation(effective_date=..., factor=0.89, as_of=..., source="Freddie", status="observed")` + `FactorRevision(effective_date=..., old_factor=0.89, new_factor=0.91, as_of=...)`. Asimetría a dejar asentada: `FactorAmortizationPlan` **no** debe exigir factor cero al vencimiento — una historia de factores incompleta es un caso legítimo que el README ya documenta. | verificado | `instruments/amortizing.py:69,86` | [#9](https://github.com/AMonten/fixed-income-lab/issues/9) | Test de regresión: `(effective_date, as_of)` duplicado falla; una revisión explícita de una observación histórica no falla; un factor path proyectado no-monótono sí falla. | pendiente |

### 0B — Defectos de contrato / API (no producen un número malo, pero el diseño miente)

| # | Ítem | Evidencia | Archivo | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|---|---|
| 0.4 | `ZeroCouponBond(100, 0.07, ...)` guarda `coupon_rate=0.0` — la firma posicional miente, viola LSP. Reproducido en vivo. | verificado | `instruments/bond.py:95` | [#7](https://github.com/AMonten/fixed-income-lab/issues/7) | Test de regresión (ver regla uniforme del bloque). | pendiente |
| 0.8 | `reset_lag_days` del FRN resta días calendario (`timedelta`), no días hábiles bajo el calendario de fixing aplicable. | verificado | `floating_rate.py:78` | [#11](https://github.com/AMonten/fixed-income-lab/issues/11) | Test de regresión (ver regla uniforme del bloque). | pendiente |

### 0C — Documentación y dependencias

| # | Ítem | Evidencia | Archivo | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|---|---|
| 0.7 | `numpy` es dependencia declarada, cero usos en `src/`/`app/` (grep vacío confirmado). | verificado | `pyproject.toml` | [#10](https://github.com/AMonten/fixed-income-lab/issues/10) | CI sigue verde sin `numpy` en `pyproject.toml`. | pendiente |
| 0.9 | README afirma que el DV01 por full-repricing "stays exact regardless of convexity" — falso, tiene error `O(h²)·P'''`, solo es más chico que la aproximación de duration modificada. | verificado | `README.md:226` (el mismo claim está también en el docstring de `risk/duration.py:32-34` — corregir los dos, no solo el README) | [#12](https://github.com/AMonten/fixed-income-lab/issues/12) | Ningún texto del repo (README ni docstrings) afirma "exacto"; describe el error `O(h²)` en su lugar. | pendiente |

---

## Bloque 1 — Market conventions (P0 — prerequisito de todo lo demás)

El eje central de ambas críticas originales: la abstracción financiera
(cash-flow-first) está mejor lograda que la fidelidad de mercado. Sin esto,
cualquier número que salga de la librería puede diferir de Bloomberg/mesa por
razones que no son el pricing en sí.

### Separación de responsabilidades: no son dos ejes, son tres

La formulación original de este bloque proponía `PeriodCounting` vs
`DayCountFraction`. Falta un eje. Son tres responsabilidades independientes, cada
una con su pregunta:

| Concepto | Pregunta que responde |
|---|---|
| `AccrualConvention` | ¿Cuánto cupón se devengó entre estas dos fechas? |
| `YieldConvention` | ¿Cómo transforma el mercado un yield cotizado en discount factors para este bono? |
| `DiscountCurve` | ¿Cuánto vale hoy un peso recibido exactamente en esta fecha? |

La API destino queda así, y conviene dejarla escrita en el documento como norte:

```python
bond.accrual_fraction(settlement)
bond.price_from_yield(yield_=0.0525, convention=StreetYield(...))
price_from_curve(bond, market.discount_curve("USD"))
```

Resuelve 0.1 de raíz (ver Bloque 0), no como parche: separa la política de tiempo
de descuento (yield cotizado vs curva) del day-count de devengo.

| Ítem | Detalle | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|
| Implementar `AccrualConvention` / `YieldConvention` / `DiscountCurve` como políticas explícitas e inyectables (ver diseño arriba) | Hoy `t` en `present_value`/YTM sale de `day_count.year_fraction(settlement, payment_date)`, un híbrido que no reproduce ninguna convención de mercado real. Mismo patrón de inyección que `DayCountConvention`. | [#13](https://github.com/AMonten/fixed-income-lab/issues/13) | `test_par_bond_prices_to_exactly_100` (0.1) pasa a verde; `present_value_from_curve` no cambia de resultado en los tests existentes. | pendiente |
| Extender la interfaz `DayCountConvention` para que reciba contexto de schedule, no solo `(start, end)` | ACT/ACT ICMA no es computable a partir de dos fechas aisladas: necesita los períodos de cupón. La firma actual `year_fraction(start, end)` es estructuralmente insuficiente. Cambio transversal: afecta `cashflows/generator.py`, `pricing/accrued_interest.py`, `pricing/present_value.py`, `risk/duration.py`, `risk/convexity.py`. **Bloquea ICMA e ISDA** — sin esta fila, quien tome el ítem de ICMA va a asumir que es "una clase más registrada en el `_REGISTRY`" y se va a chocar con un refactor de seis módulos. | [#14](https://github.com/AMonten/fixed-income-lab/issues/14) | Las convenciones existentes (ACT/360, ACT/365F, 30/360) migran a la nueva firma sin cambiar de resultado en ningún test existente. | pendiente |
| ACT/ACT ICMA | Las convenciones ACT/ACT basadas en período de cupón, ICMA incluida, son P0: necesarias para soportar correctamente los principales mercados soberanos y de bonos internacionales de tasa fija. *(Corrección: no es específicamente para Treasuries — ver nota abajo.)* Prioridad más alta de las dos convenciones ACT/ACT faltantes. | [#15](https://github.com/AMonten/fixed-income-lab/issues/15) | Caso de referencia de Bloque 5 (bono EUR bajo ICMA) dentro de tolerancia documentada. | pendiente |
| ACT/ACT ISDA | Segunda prioridad de las dos convenciones ACT/ACT faltantes. | [#16](https://github.com/AMonten/fixed-income-lab/issues/16) | Caso de referencia de Bloque 5 dentro de tolerancia documentada. | pendiente |
| 30E/360 (+ 30E/360 ISDA después) | Menor prioridad que ACT/ACT. | [#17](https://github.com/AMonten/fixed-income-lab/issues/17) | Caso de referencia dentro de tolerancia documentada. | pendiente |
| Calendario de días hábiles configurable | Reemplazar `weekday() < 5` hardcodeado por un `Calendar` inyectable (holidays reales). Es prerequisito de "reconciliación real" contra sistemas externos. | [#18](https://github.com/AMonten/fixed-income-lab/issues/18) | `Calendar` es inyectable y al menos un calendario real (p. ej. US) reemplaza `weekday() < 5` en al menos un test de fecha de pago/reset. | pendiente |
| `ScheduleSpec` como objeto de primera clase | Formalizar effective/termination date, first/penultimate coupon explícito, stub corto/largo delante y detrás, EOM rule, payment lag, settlement lag — hoy son implícitos o inexistentes. | [#19](https://github.com/AMonten/fixed-income-lab/issues/19) | Cada campo (stub, EOM, lag) tiene al menos un test que lo ejercita a través de `ScheduleSpec`. | pendiente |
| `reset_lag_days` del FRN en días calendario, no hábiles | Usa `timedelta(days=...)` — no es "2 días hábiles antes bajo el calendario de fixing aplicable". Diseñar `RateIndex`/`ResetConvention` para soportar esto y, más adelante, lookback/lockout/observation shift/compounded-in-arrears (SOFR-style). | [#11](https://github.com/AMonten/fixed-income-lab/issues/11) (mismo bug que 0.8) | Test de 0.8 pasa a verde. | pendiente |
| Fix de LSP en `ZeroCouponBond` | Convertir a factory (`Bond.zero_coupon(...)`) o clase hermana bajo un contrato común, no herencia que descarta un parámetro posicional. | [#7](https://github.com/AMonten/fixed-income-lab/issues/7) (mismo bug que 0.4) | Test de 0.4 pasa a verde. | pendiente |
| `typing.Protocol` común para instrumentos | `Bond`, `FloatingRateNote`, `AmortizingBond` comparten `cash_flows()`/`face_value`/`day_count` por convención, no por tipo (`AmortizingBond.face_value` es un alias de `original_face` puesto ahí a mano). Un Protocol de ~10 líneas lo formaliza y mypy lo puede verificar. Mejor relación esfuerzo/impacto del repo. | [#20](https://github.com/AMonten/fixed-income-lab/issues/20) | `mypy` (Bloque 6) verifica los tres instrumentos contra el Protocol en CI. | pendiente |

**Nota — corrección sobre Treasuries e ICMA**: el documento original decía que sin
ACT/ACT ICMA no se puede valuar un Treasury. Es impreciso: los Treasuries usan
convenciones ACT/ACT de tipo bond-equivalent con conteo real de días, mientras que
ICMA es una convención específica, habitual sobre todo en bonos de tasa fija no
denominados en USD, con sus propias reglas de períodos de cupón. Bloque 5 agrega
casos de referencia separados en vez de asumir `Treasury = ICMA` (ver ahí).

---

## Bloque 2 — Arquitectura de curva (P1)

| Ítem | Detalle | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|
| `DiscountCurve` basada en fecha→discount factor | Cambiar el centro conceptual de `tenor → zero rate` a `reference date + pillar date → discount factor`, derivando zero/forward desde ahí, no al revés. | [#21](https://github.com/AMonten/fixed-income-lab/issues/21) | Tests actuales de curva migran sin cambio de resultado; zero/forward se derivan, no se asumen. | pendiente |
| Interpolar `log(DF)` en vez de `log(zero rate)` | El `LOG_LINEAR` actual interpola zero rates en log-space, lo que rompe matemáticamente con tasas negativas (reales en mercado). `ln(DF)` interpolado linealmente es más robusto y no tiene esa restricción. | [#22](https://github.com/AMonten/fixed-income-lab/issues/22) | Un caso con zero rate negativa en un pillar interpola sin `ValueError`. | pendiente |
| `CurveBuilder` / bootstrap básico | Tomar inputs observables (T-bills/notes/bonds, o deposits/OIS/swaps) y generar una `DiscountCurve` con pillars — el paso que convierte la librería de "matemática" a "financiera". | [#23](https://github.com/AMonten/fixed-income-lab/issues/23) | Un bootstrap desde un set de inputs reproduce los pillars esperados dentro de tolerancia (caso de referencia de Bloque 5). | pendiente |
| Separación `DiscountCurve` / `ProjectionCurve` | Prerequisito real para que el FRN deje de ser una simplificación declarada (ver Bloque 3). | [#24](https://github.com/AMonten/fixed-income-lab/issues/24) | Un test de FRN usa discount curve y projection curve distintas y el resultado difiere del caso de curva única. | pendiente |
| Z-spread | Con la curva ya armada, resolver `z` tal que PV coincide con precio de mercado. Alto retorno inmediato para corporates, antes que callable/OAS. | [#25](https://github.com/AMonten/fixed-income-lab/issues/25) | Caso de referencia dentro de tolerancia documentada. | pendiente |
| Spread duration / spread DV01 | Sigue naturalmente de Z-spread. | [#26](https://github.com/AMonten/fixed-income-lab/issues/26) | Caso de referencia dentro de tolerancia documentada. | pendiente |
| Key-rate durations / partial DV01 por pilar | `risk` ya solo ve flujos, así que un shock por pilar es casi gratis con la arquitectura actual. Es la métrica que una tesorería usa de verdad para cubrir. Habilita escenarios no-paralelos (steepener, flattener, belly shock, shocks custom por nodo). | [#27](https://github.com/AMonten/fixed-income-lab/issues/27) | Suma de KRDs por pilar ≈ DV01 paralelo dentro de tolerancia documentada. | pendiente |
| Corregir claim de README sobre DV01 "exacto" | El README dice que la diferencia central "stays exact regardless of convexity" — es falso, tiene error `O(h²)·P'''`. Es mejor que `D_mod·P·1e-4`, no exacto. Corregir la afirmación (ver 0.9/0C, incluye también el docstring de `risk/duration.py`). | [#12](https://github.com/AMonten/fixed-income-lab/issues/12) (mismo issue que 0.9) | Ver 0.9. | pendiente |

---

## Bloque 3 — FRN y risk basado en curva (P1)

| Ítem | Detalle | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|
| Objeto `Market` (`discount_curves`, `projection_curves`, `fixings`) | Separa terms del instrumento / estado de mercado / analytics. Cambio arquitectónico más grande propuesto, pero encaja sin romper lo existente porque `pricing`/`risk` ya solo consumen cash flows. | [#28](https://github.com/AMonten/fixed-income-lab/issues/28) | Tests existentes migran a consumir `Market` sin cambio de resultado. | pendiente |
| FRN: duration/DV01 con recálculo de flujos, no flujo proyectado fijo | Hoy el shock de yield mantiene el cash flow proyectado fijo — el README ya reconoce que esto infla el rate risk aparente del FRN. Con `Market` separando discount/projection, el shock puede mover también los forwards que determinan `CF_t`. | [#29](https://github.com/AMonten/fixed-income-lab/issues/29) | Un test de shock muestra el DV01 del FRN cambiando cuando se mueven los forwards (hoy no cambia). | pendiente |
| Provenance transversal de cash flows (P1) | No es específica de MBS: aplica a fixings de FRN (observado vs proyectado — ya existe la semilla funcionando en `FloatingRateNote.rate_provenance()`), a factores (publicado vs proyectado por PSA — ver 0.6), a nodos de curva (cotizado vs bootstrapeado vs interpolado — ver Bloque 2) y en última instancia a cualquier cash flow (contractual / observado / derivado / proyectado). Modelo: `CashFlow(..., provenance=CashFlowProvenance(status=ProjectionStatus.PROJECTED, source="SOFR_FORWARD"))`. | [#30](https://github.com/AMonten/fixed-income-lab/issues/30) | Al menos un tipo de cash flow (FRN) expone `provenance` con el modelo de arriba, con test. | pendiente |
| `PrepaymentModel` protocol (si se elige el eje MBS — ver Bloque 7) | `NoPrepayment`, `ConstantCPR`, `PSA`. Depende de la decisión estratégica. | [#31](https://github.com/AMonten/fixed-income-lab/issues/31) | Las tres implementaciones satisfacen un protocolo común, con un caso de referencia de WAL/CPR. | pendiente / depende de decisión |

---

## Bloque 4 — Portfolio (P1/P2)

| Ítem | Detalle | Issue | Criterio de hecho | Estado |
|---|---|---|---|---|
| Portfolio yield real vía IRR de flujos agregados | El `weighted_yield` actual pondera YTM individuales por valor de mercado — matemáticamente válido pero no es el yield del portfolio. Renombrar la métrica actual a algo inequívoco (`market_value_weighted_yield`) e implementar el yield real: `MV = Σ_t CF_portfolio_t / (1+y)^t` con `CF_portfolio_t = Σ_i CF_i,t`. | [#32](https://github.com/AMonten/fixed-income-lab/issues/32) | Caso de referencia (a mano o QuantLib) coincide dentro de tolerancia; `weighted_yield` queda renombrada. | pendiente |
| Cash-flow ladder / agregación de portfolio | Generar tabla fecha→interest/principal/total/outstanding y buckets de madurez (0-3m, 3-6m, ..., 10y+). Casi no requiere matemática nueva, aprovecha la abstracción de cash flows ya existente — alto ROI. Habilita liquidity analysis, cash forecasting, maturity concentration. | [#33](https://github.com/AMonten/fixed-income-lab/issues/33) | El ladder reconcilia (suma) contra el total de cash flows del portfolio en un caso de referencia. | pendiente |
| Permitir posiciones cortas (`par_amount` negativo) | Hoy `par_amount > 0` impide modelar una cobertura — la mitad de para qué existe una cartera de renta fija en un banco. | [#34](https://github.com/AMonten/fixed-income-lab/issues/34) | Escenario long+short con DV01 neto ≈ 0 pasa. | pendiente |
| `valuation_date` común de cartera (reemplaza la validación de "fecha de liquidación común") | Validar una `settlement_date` común entre posiciones es incorrecto: una cartera real contiene operaciones con settlements distintos. En su lugar: la cartera exige `valuation_date` común; cada posición lleva su propio `trade_date`, `settlement_date` y `par_amount`. Esto habilita después distinguir holdings de pending settlements. | [#35](https://github.com/AMonten/fixed-income-lab/issues/35) | `PortfolioAnalytics` valida `valuation_date` común y falla con settlements dispares entre posiciones; hay test para el caso de falla. | pendiente |
| Validar moneda común (o soportar FX explícitamente) | Fila que faltaba: hoy nada impide sumar valores de mercado o DV01 entre posiciones en monedas distintas. | [#36](https://github.com/AMonten/fixed-income-lab/issues/36) | `analyze_portfolio` falla (o convierte explícitamente) ante monedas mixtas; hay test para el caso de falla. | pendiente |

---

## Bloque 5 — Testing y validación externa (transversal — corre en paralelo a todo lo anterior)

El gap de calidad más grande no es coverage, es que ningún test ancla contra un
valor externo. 97% de cobertura de una fórmula equivocada es 97% de cobertura de
nada.

> **Política de validación** (aplica a todo este roadmap, no solo a este bloque):
> ningún ítem de este roadmap se marca `hecho` sin al menos un test de referencia
> independiente cuando existe un benchmark externo aplicable.

| Ítem | Detalle | Criterio de hecho | Estado |
|---|---|---|---|
| `tests/reference/` — validación de referencia | Para cada instrumento: inputs, expected clean/dirty/accrued/YTM/duration/convexity/cash flows, y la fuente de referencia declarada por fixture — "golden tests contra QuantLib" se renombra porque QuantLib no es la referencia adecuada para todo. Formato del fixture: `reference.engine`, `reference.version`, `reference.convention`, `tolerance.price`, `tolerance.yield`. Fuentes válidas: QuantLib, ejemplo trabajado de ICMA, ejemplo publicado por el Tesoro, caso analítico derivado a mano, caso de cash flow conocido de vendor. QuantLib (u otro motor externo) solo como dependencia de test/dev, no runtime. Casos mínimos a cubrir (ver Bloque 1): US Treasury, bono EUR bajo ACT/ACT ICMA, primer cupón irregular, último cupón irregular, año bisiesto. Indicadores a subir al README en vez de perseguir cobertura: `118 tests / 97% coverage / N casos de referencia independientes / M convenciones validadas`, y más adelante desviación máxima de precio y de yield contra referencia. | Cada instrumento soportado tiene ≥1 fixture con los campos de arriba, corriendo en CI dentro de la tolerancia declarada. | pendiente |
| Invariantes analíticas | par→100 en fecha de cupón (mismo test que 0.1); precio monótono decreciente en yield; convexidad ≥ 0 con flujos positivos; `sum(principal) == face` (donde aplique — ver 0.5); `dirty == clean + accrued`; `factor ∈ [0,1]`; `DV01 ≈ D_mod·P·1e-4` dentro de tolerancia. | Cada invariante tiene un test explícito en CI. | pendiente |
| Property-based testing con `hypothesis` | Generación de schedules: stubs, fin de mes, años bisiestos, frecuencias mixtas — encuentra edge cases que los tests example-based no encuentran. | Al menos la generación de schedules tiene tests basados en `hypothesis` corriendo en CI. | pendiente |
| `--cov-fail-under` en CI | Evitar regresión silenciosa de cobertura. | Un PR que baja cobertura por debajo del umbral falla en CI. | pendiente |

---

## Bloque 6 — Ingeniería y repo (P1/P2 — no bloquea lo anterior, se puede intercalar)

| Ítem | Detalle | Criterio de hecho | Estado |
|---|---|---|---|
| `mypy` en CI | Está en `dev` deps, pasa limpio hoy, pero no corre en el pipeline. Ponerlo antes de que deje de pasar en silencio. | Un PR que introduce un error de tipos falla en CI. | pendiente |
| `py.typed` | Falta en el paquete propio — quien lo instale no recibe los tipos, se pierde todo el trabajo de tipado río abajo. | El archivo existe y queda empaquetado en el wheel (verificable en el ítem de CI de abajo). | pendiente |
| Sacar `numpy` de dependencias (o vectorizar de verdad) | Ver 0.7/0C — cero usos confirmados. | Ver 0.7. | pendiente |
| Alinear versión y narrativa | `0.1.0`/Beta vs README "v1.0 feature-complete". Mantener `0.x` hasta cerrar market conventions + validación externa + arquitectura de curva + API estable, y recién ahí reservar `1.0` para compromiso de estabilidad de API. Agregar tags/releases/CHANGELOG. | `pyproject.toml` y README describen la misma fase de madurez; existe al menos un tag/release. | pendiente |
| `sys.path.insert()` en el Streamlit app | El demo debería consumir el paquete igual que cualquier usuario (`from fixed_income import ...` vía instalación editable), no hackear el path — señal de madurez de packaging. | El app importa el paquete instalado (editable install), sin manipular `sys.path`. | pendiente |
| CI: cerrar el círculo | Sumar a lint+pytest actuales: `mypy`, coverage threshold, `python -m build`, instalar el wheel generado, smoke import, docs build. | Cada paso corre y falla el pipeline si no pasa. | pendiente |
| `ruff format`, pre-commit, dependabot | | Configurados y verdes en CI. | pendiente |
| Demo desplegado / GIF en README | Streamlit Community Cloud + GIF — mayor retorno por hora invertida para un repo con 0 estrellas, aunque no toca correctitud. | README enlaza un demo vivo y muestra un GIF. | pendiente |
| PyPI | Hoy el README pide `git clone` — barrera de adopción si se quiere posicionar como librería. Ver Anexo (depende de si se persigue adopción externa o portfolio personal). | Paquete instalable con `pip install` desde PyPI. | pendiente |
| Performance: cachear flujos, precomputar vector de `t` | `generate_schedule()` corre 2 veces por `analyze_bond`; `brentq` reprecia recalculando `year_fraction` en cada iteración. Sin tocar arquitectura, un orden de magnitud de mejora. Ver Anexo — números no re-verificados de forma independiente. | Profiling propio (no los números heredados de la primera crítica) documenta la mejora medida. | pendiente |
| Política de redondeo por mercado / `Decimal` en montos | Hoy todo es `float` sin redondeo específico por convención de mercado. Ver Anexo — depende de si el objetivo es liquidación real o analítica. | Solo aplica si se persigue el caso de liquidación real (ver Anexo); montos usan `Decimal` bajo una política de redondeo documentada. | pendiente |

### PR de higiene (primera PR sugerida — no bloqueante)

Extraído de Bloque 0 y Bloque 6, para arrancar con algo chico y de retorno
inmediato antes de meterse con Bloque 1: sacar `numpy`, agregar `py.typed`,
`mypy` y `--cov-fail-under` en CI, corregir el claim del DV01 en README y en el
docstring de `risk/duration.py`, crear el test `xfail` del par (0.1). Cierra seis
filas (0.7, `py.typed`, `mypy` en CI, `--cov-fail-under`, 0.9, 0.1) y no bloquea
nada. *(La acción "crear los issues #4–#12" que figuraba originalmente en este
batch ya no aplica: se verificó que los nueve ya existen en GitHub.)*

---

## Bloque 7 — Decisión estratégica de diferenciación (BLOQUEA lo que depende de ella, no Bloque 0/1/5)

Ambas críticas originales coinciden en que "más instrumentos" no es el eje
correcto, pero proponen ejes distintos. Esto no lo puedo decidir yo. No son cuatro
opciones excluyentes en un solo eje — son tres decisiones ortogonales que se
pueden combinar:

| Decisión | Opciones |
|---|---|
| Filosofía de diseño | transparente/legible vs exhaustiva |
| Especialización de dominio | general / LatAm / amortizing-MBS |
| Forma de consumo primaria | librería Python / pipeline CLI / UI |

Notas por opción (de la formulación original, ahora ubicadas dentro del eje que
corresponde):

- **Transparente/legible** ("QuantLib explicado" — cada módulo con su derivación,
  notebooks que muestran el porqué): defendible, el README ya apunta ahí. Menor
  esfuerzo, coherente con lo que ya existe.
- **LatAm**: bonos indexados por inflación (UVA, UF, UDI), amortizables locales,
  convenciones y calendarios por plaza. No existe nada bueno open source y es tu
  dominio real de negocio. Mayor valor diferencial dado tu perfil (banca, MMG).
- **Amortizing-MBS**: `original_face → factor → current_face` ya es la semilla;
  sumar `historical vs projected factor`, CPR/SMM/PSA, WAL. La arquitectura actual
  (factor-driven amortizing) ya encaja sorprendentemente bien acá. *(El provenance
  por cash flow ya no es específico de esta opción — se movió a Bloque 3 como fila
  transversal.)*
- **Pipeline CLI / UI**: el Bloque 4/6 (CLI, ingesta CSV/Excel, export, logging)
  como producto principal — la librería es el motor, el producto es el pipeline
  hacia tu trabajo diario. Puente directo a tareas que ya automatizás en el sector
  bursátil.

**No se empieza a ejecutar lo que depende de esta decisión** — Bloque 3 más allá
de lo genérico, y el alcance MBS de Bloque 6/7 — **hasta que se elija**. Esto no
bloquea Bloque 0/1/5, que proceden en paralelo (ver Orden de trabajo). Ver Anexo
para el detalle de qué más depende de cada opción.

---

## Descartado

- **FastAPI / servicio HTTP**: fuera de alcance mientras la forma de consumo
  primaria (Bloque 7) no esté decidida — expondría una API antes de tener la
  semántica de mercado resuelta.
- **Base de datos**: no hay estado que persistir hoy — la librería es función
  pura de sus inputs; agregar una BD es infraestructura sin necesidad de negocio
  identificada.
- **Auth**: solo tendría sentido si existiera un servicio expuesto (ver FastAPI
  arriba); no aplica mientras el consumo sea librería/notebook.
- **Conectores de market data**: fuera de alcance mientras no exista un
  `DiscountCurve`/`Market` real (Bloque 2/3) que los consuma — hoy no hay dónde
  enchufarlos.
- **ML**: ningún hallazgo de ninguna de las críticas lo pide; no hay caso de uso
  identificado — pricing/risk de renta fija acá es determinístico, no un problema
  de aprendizaje.
- **Swaps/swaptions/convertibles, ahora**: Bloque 7 todavía no resolvió el eje de
  diferenciación; sumar instrumentos antes de esa decisión es la misma trampa de
  "más instrumentos no es el eje" que señalan ambas críticas.
- **CMO, antes de tener prepayments**: un CMO sin `PrepaymentModel` (Bloque 3) es
  una tabla de reglas de distribución sin la curva de prepago que la hace no
  trivial — no tiene sentido secuenciarlo antes.

---

## Orden de trabajo sugerido

1. **PR de higiene** (ver Bloque 6) — no bloqueante, se puede hacer en paralelo a
   cualquier otra cosa; buen primer commit.
2. **Bloque 0** completo (0.1 + 0A/0B/0C) — sin esto, todo lo que se construya
   encima está sobre números mal calculados.
3. **Bloque 1** (market conventions) en paralelo con **Bloque 5** (validación de
   referencia) — cada fix de convención se ancla con un caso de referencia al
   mismo tiempo, no después.
4. **Bloque 7** — decisión estratégica. No bloquea 0/1/5, pero sí todo lo que
   depende de ella (ver Bloque 7).
5. **Bloque 2** (curvas) → **Bloque 3** (FRN/Market) → **Bloque 4** (portfolio),
   en ese orden, salvo que la decisión del Bloque 7 reordene algo.
6. **Bloque 6** (ingeniería, resto) intercalado donde convenga — nada ahí es
   bloqueante.

---

## Anexo — Incertidumbres y decisiones pendientes de Alberto

Cosas que quedan afuera del cuerpo principal porque no están confirmadas — ni por
verificación propia, ni porque dependen de un criterio de negocio que solo Alberto
tiene.

- **Números de performance** (`analyze_bond` ~2.7ms, YTM solve ~3ms, ~15s para
  repreciar 5.000 posiciones) — vienen de la primera crítica, no los reproduje yo
  mismo con profiling. Antes de tratarlos como bug de performance, correr un
  profile propio.
- **¿Se persigue adopción externa (PyPI, estrellas, README con GIF) o es
  primariamente pieza de portafolio?** Cambia la prioridad relativa de Bloque 6
  (empaquetado/demo) vs Bloque 0/1/5 (correctitud).
- **Decimal vs float para montos**: solo importa si en algún momento el objetivo
  pasa de "analítica" a "liquidación real". Sin confirmar cuál es el caso, no vale
  la pena el esfuerzo de introducir `Decimal` en la capa de montos.
- **Alcance de calendario de feriados**: si la decisión del Bloque 7 es la
  especialización LatAm, el calendario configurable del Bloque 1 necesita
  feriados de plazas LatAm específicas (no solo un `Calendar` genérico tipo
  US/UK). Afecta el diseño del objeto `Calendar`, no solo su existencia.
- **`reset_lag_days` como "2 días hábiles bajo calendario de fixing"**: correcto
  como crítica (0.8 es un bug confirmado independientemente de esto), pero qué
  calendario de fixing usar (SOFR, o el que aplique) depende de qué índices de
  referencia se planea soportar — no decidido.
- **mypy `--strict` o baseline**: ambas críticas piden "mypy en CI" pero no
  especifican nivel de estrictez. Confirmar antes de fijar la config en CI para no
  tener que revertir luego.
- **PyPI**: mencionado como brecha de adopción por la primera crítica, pero con
  0 estrellas y sin decidir el eje de diferenciación (Bloque 7), publicar ahora
  podría ser prematuro — mejor evaluarlo después de esa decisión.
- **Alcance real de "Market object"**: es el cambio arquitectónico más grande
  propuesto (Bloque 3). Antes de empezarlo, vale confirmar que no es sobre-ingeniería
  para el tamaño actual del proyecto — depende directamente de qué tan lejos se
  quiere llevar FRN/curve-risk, que a su vez depende del Bloque 7.

---

## Changelog de esta revisión (v1 → v2)

- 0.1 reformulado como mismatch de semántica de tiempo, sacado del Anexo: default street, true yield explícito, prohibido el fix ingenuo `payment_date → accrual_end`.
- Bloque 1: dos conceptos (`PeriodCounting`/`DayCountFraction`) pasan a tres (`Accrual`/`Yield`/`DiscountCurve`), con API destino escrita.
- Fila bloqueante agregada: `DayCountConvention` necesita contexto de schedule para que ICMA sea implementable.
- Corregido "sin ICMA no hay Treasury" (los Treasuries no usan ICMA); casos de referencia separados en Bloque 5.
- Bloque 0 partido en 0.1 (aparte) + 0A/0B/0C; regla nueva: nada es "bug no debatible" y decisión abierta del Anexo a la vez.
- 0.5/0.6 reescritos: el bug es la sobre-amortización/sobrescritura silenciosa, no la falta de invariantes que no son universales.
- Bloque 4: "settlement_date común" (incorrecta) → "valuation_date común" + settlement por posición; agregada fila de moneda/FX.
- Provenance de cash flows: de paréntesis en la opción MBS del Bloque 7 a fila transversal en Bloque 3.
- Bloque 7: 4 opciones "excluyentes" → 3 decisiones ortogonales combinables; corregida la contradicción sobre qué bloquea.
- Bloque 5: "golden tests QuantLib" renombrado a "validación de referencia"; formato de fixture e indicadores de README especificados.
- Agregada columna "Criterio de hecho" en todas las tablas, sección "Descartado", y PR de higiene como primer paso.
- Verificado: issues #4–#12 ya existen (no hacía falta crearlos); ningún archivo de evidencia cambió desde v1, referencias intactas.
- Hallazgo adicional: `risk/duration.py` repite el claim falso de DV01 "exacto" del README — sumado como evidencia de 0.9, no como ítem nuevo.
