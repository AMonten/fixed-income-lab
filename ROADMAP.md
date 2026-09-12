# Roadmap — fixed-income-lab

Documento de planificación vivo. Fusiona dos revisiones externas independientes del
repo (una con ejecución de código y evidencia reproducible, otra puramente de
diseño/arquitectura sin correr la suite) más verificación propia de los hallazgos
más graves. Reemplaza como fuente de planificación a la sección `## Roadmap` del
`README.md` (esa sección se actualiza una vez que las decisiones acá abajo estén
tomadas y ejecutadas — no antes, para no duplicar estado en dos lugares).

**Cómo se usa este archivo**: cada ítem tiene un estado (`pendiente` /
`en progreso` / `hecho` / `descartado`). Actualizar el estado a medida que se
trabaja, no crear un doc de progreso aparte. El **Anexo** al final es la lista de
cosas que no están confirmadas — ni por mí (sin verificar en código o con evidencia
débil) ni por Alberto (decisiones que dependen de su contexto de negocio) — revisarlo
antes de asumir que algo del cuerpo principal es definitivo.

---

## Estado actual (2026-09-12)

- `pyproject.toml`: versión `0.1.0`, `Development Status :: 4 - Beta`. README narra
  "V1 feature-complete". Inconsistente — ver Bloque 4.
- 118 tests, ~97% coverage, 0 tests anclados contra un valor externo (QuantLib u
  otro). Coverage alto, validación financiera independiente inexistente.
- Instrumentos: `Bond` (bullet), `ZeroCouponBond`, `FloatingRateNote`,
  `AmortizingBond` (level/explicit/factor-driven).
- Day-count: ACT/360, ACT/365F, 30/360 US. Falta ACT/ACT (ICMA/ISDA), 30E/360.
- Calendario de días hábiles: `weekday() < 5` únicamente — sin feriados, sin
  calendario configurable.
- `YieldCurve`: tenor→zero-rate con interpolación linear/log-linear/flat.
  `LOG_LINEAR` interpola la zero rate (rompe con tasas negativas).

---

## Bloque 0 — Bugs confirmados (fix inmediato, bloquean todo lo demás)

Estos ya están verificados en código con reproducción numérica exacta. No son
debatibles, son bugs.

| # | Ítem | Evidencia | Archivo | Issue | Estado |
|---|---|---|---|---|---|
| 0.1 | Un bono a la par no da 100: `present_value` descuenta con `cf.payment_date` (ajustado a día hábil) mientras el devengo/cupón usa fechas sin ajustar. Con `FOLLOWING` (default), todo precio tiene sesgo sistemático de ~0.26pb. Reproducido: ACT/365 → 99.997019, 30/360 → 99.997379, 30/360+`NONE` → 100.0000000000 | `present_value.py:38` vs `generator.py:72` | `pricing/present_value.py` | [#4](https://github.com/AMonten/fixed-income-lab/issues/4) | pendiente |
| 0.2 | `YieldCurve(tenors=(1,2,2,5))` acepta duplicados en silencio — el check `list(tenors) != sorted(tenors)` no detecta repetidos porque `(1,2,2,5)` ya está ordenada. Reproducido en vivo. | verificado | `pricing/curves.py:55` | [#5](https://github.com/AMonten/fixed-income-lab/issues/5) | pendiente |
| 0.3 | `YieldCurve(tenors=(-1,5))` acepta tenor negativo; `discount_factor(-1) = 1.03`. Reproducido en vivo. | verificado | `pricing/curves.py` | [#6](https://github.com/AMonten/fixed-income-lab/issues/6) | pendiente |
| 0.4 | `ZeroCouponBond(100, 0.07, ...)` guarda `coupon_rate=0.0` — la firma posicional miente, viola LSP. Reproducido en vivo. | verificado | `instruments/bond.py:95` | [#7](https://github.com/AMonten/fixed-income-lab/issues/7) | pendiente |
| 0.5 | `ExplicitAmortizationPlan` no valida `sum(repayments) == original_face`. Sobre-amortizar se trunca en silencio (`max(..., 0)`) en vez de fallar. | leído en código | `instruments/amortizing.py` | [#8](https://github.com/AMonten/fixed-income-lab/issues/8) | pendiente |
| 0.6 | `FactorHistory` no valida monotonicidad decreciente ni fechas duplicadas — una secuencia `0.92 → 0.89 → 0.91` (outstanding subiendo) pasa sin aviso. | verificado | `instruments/amortizing.py:69,86` | [#9](https://github.com/AMonten/fixed-income-lab/issues/9) | pendiente |
| 0.7 | `numpy` es dependencia declarada, cero usos en `src/`/`app/` (grep vacío confirmado). | verificado | `pyproject.toml` | [#10](https://github.com/AMonten/fixed-income-lab/issues/10) | pendiente |
| 0.8 | `reset_lag_days` del FRN resta días calendario (`timedelta`), no días hábiles bajo el calendario de fixing aplicable. | verificado | `floating_rate.py:78` | [#11](https://github.com/AMonten/fixed-income-lab/issues/11) | pendiente |
| 0.9 | README afirma que el DV01 por full-repricing "stays exact regardless of convexity" — falso, tiene error `O(h²)·P'''`, solo es más chico que la aproximación de duration modificada. | verificado | `README.md:226` | [#12](https://github.com/AMonten/fixed-income-lab/issues/12) | pendiente |

---

## Bloque 1 — Market conventions (P0 — prerequisito de todo lo demás)

El eje central de ambas críticas: la abstracción financiera (cash-flow-first) está
mejor lograda que la fidelidad de mercado. Sin esto, cualquier número que salga de
la librería puede diferir de Bloomberg/mesa por razones que no son el pricing en sí.

| Ítem | Detalle | Estado |
|---|---|---|
| Política de tiempo de descuento separada del day-count de devengo | Hoy `t` en `present_value`/YTM sale de `day_count.year_fraction(settlement, payment_date)`, un híbrido que no reproduce ninguna convención de mercado real. Introducir `PeriodCounting` vs `DayCountFraction` como política explícita e inyectable, igual patrón que `DayCountConvention`. Resuelve 0.1 de raíz, no como parche. | pendiente |
| ACT/ACT ICMA | Prioridad más alta de las dos convenciones faltantes — sin ella no se puede valuar un Treasury ni la mayoría de gobiernos. | pendiente |
| ACT/ACT ISDA | Segunda prioridad. | pendiente |
| 30E/360 (+ 30E/360 ISDA después) | Menor prioridad que ACT/ACT. | pendiente |
| Calendario de días hábiles configurable | Reemplazar `weekday() < 5` hardcodeado por un `Calendar` inyectable (holidays reales). Es prerequisito de "reconciliación real" contra sistemas externos. | pendiente |
| `ScheduleSpec` como objeto de primera clase | Formalizar effective/termination date, first/penultimate coupon explícito, stub corto/largo delante y detrás, EOM rule, payment lag, settlement lag — hoy son implícitos o inexistentes. | pendiente |
| `reset_lag_days` del FRN en días calendario, no hábiles ([#11](https://github.com/AMonten/fixed-income-lab/issues/11)) | Usa `timedelta(days=...)` — no es "2 días hábiles antes bajo el calendario de fixing aplicable". Diseñar `RateIndex`/`ResetConvention` para soportar esto y, más adelante, lookback/lockout/observation shift/compounded-in-arrears (SOFR-style). | pendiente |
| Fix de LSP en `ZeroCouponBond` | Convertir a factory (`Bond.zero_coupon(...)`) o clase hermana bajo un contrato común, no herencia que descarta un parámetro posicional. | pendiente |
| `typing.Protocol` común para instrumentos | `Bond`, `FloatingRateNote`, `AmortizingBond` comparten `cash_flows()`/`face_value`/`day_count` por convención, no por tipo (`AmortizingBond.face_value` es un alias de `original_face` puesto ahí a mano). Un Protocol de ~10 líneas lo formaliza y mypy lo puede verificar. Mejor relación esfuerzo/impacto del repo. | pendiente |

---

## Bloque 2 — Arquitectura de curva (P1)

| Ítem | Detalle | Estado |
|---|---|---|
| `DiscountCurve` basada en fecha→discount factor | Cambiar el centro conceptual de `tenor → zero rate` a `reference date + pillar date → discount factor`, derivando zero/forward desde ahí, no al revés. | pendiente |
| Interpolar `log(DF)` en vez de `log(zero rate)` | El `LOG_LINEAR` actual interpola zero rates en log-space, lo que rompe matemáticamente con tasas negativas (reales en mercado). `ln(DF)` interpolado linealmente es más robusto y no tiene esa restricción. | pendiente |
| `CurveBuilder` / bootstrap básico | Tomar inputs observables (T-bills/notes/bonds, o deposits/OIS/swaps) y generar una `DiscountCurve` con pillars — el paso que convierte la librería de "matemática" a "financiera". | pendiente |
| Separación `DiscountCurve` / `ProjectionCurve` | Prerequisito real para que el FRN deje de ser una simplificación declarada (ver Bloque 3). | pendiente |
| Z-spread | Con la curva ya armada, resolver `z` tal que PV coincide con precio de mercado. Alto retorno inmediato para corporates, antes que callable/OAS. | pendiente |
| Spread duration / spread DV01 | Sigue naturalmente de Z-spread. | pendiente |
| Key-rate durations / partial DV01 por pilar | `risk` ya solo ve flujos, así que un shock por pilar es casi gratis con la arquitectura actual. Es la métrica que una tesorería usa de verdad para cubrir. Habilita escenarios no-paralelos (steepener, flattener, belly shock, shocks custom por nodo). | pendiente |
| Corregir claim de README sobre DV01 "exacto" ([#12](https://github.com/AMonten/fixed-income-lab/issues/12)) | El README dice que la diferencia central "stays exact regardless of convexity" — es falso, tiene error `O(h²)·P'''`. Es mejor que `D_mod·P·1e-4`, no exacto. Corregir la afirmación. | pendiente |

---

## Bloque 3 — FRN y risk basado en curva (P1)

| Ítem | Detalle | Estado |
|---|---|---|
| Objeto `Market` (`discount_curves`, `projection_curves`, `fixings`) | Separa terms del instrumento / estado de mercado / analytics. Cambio arquitectónico más grande propuesto, pero encaja sin romper lo existente porque `pricing`/`risk` ya solo consumen cash flows. | pendiente |
| FRN: duration/DV01 con recálculo de flujos, no flujo proyectado fijo | Hoy el shock de yield mantiene el cash flow proyectado fijo — el README ya reconoce que esto infla el rate risk aparente del FRN. Con `Market` separando discount/projection, el shock puede mover también los forwards que determinan `CF_t`. | pendiente |
| `PrepaymentModel` protocol (si se elige el eje MBS — ver Bloque 6) | `NoPrepayment`, `ConstantCPR`, `PSA`. Depende de la decisión estratégica. | pendiente / depende de decisión |

---

## Bloque 4 — Portfolio (P1/P2)

| Ítem | Detalle | Estado |
|---|---|---|
| Portfolio yield real vía IRR de flujos agregados | El `weighted_yield` actual pondera YTM individuales por valor de mercado — matemáticamente válido pero no es el yield del portfolio. Renombrar la métrica actual a algo inequívoco (`market_value_weighted_yield`) e implementar el yield real: `MV = Σ_t CF_portfolio_t / (1+y)^t` con `CF_portfolio_t = Σ_i CF_i,t`. | pendiente |
| Cash-flow ladder / agregación de portfolio | Generar tabla fecha→interest/principal/total/outstanding y buckets de madurez (0-3m, 3-6m, ..., 10y+). Casi no requiere matemática nueva, aprovecha la abstracción de cash flows ya existente — alto ROI. Habilita liquidity analysis, cash forecasting, maturity concentration. | pendiente |
| Permitir posiciones cortas (`par_amount` negativo) | Hoy `par_amount > 0` impide modelar una cobertura — la mitad de para qué existe una cartera de renta fija en un banco. | pendiente |
| Validar fecha de liquidación común entre posiciones | Hoy nadie valida que todas las posiciones de una cartera compartan `settlement_date`. | pendiente |

---

## Bloque 5 — Testing y validación externa (transversal — corre en paralelo a todo lo anterior)

El gap de calidad más grande no es coverage, es que ningún test ancla contra un
valor externo. 97% de cobertura de una fórmula equivocada es 97% de cobertura de
nada.

| Ítem | Detalle | Estado |
|---|---|---|
| `tests/reference/` — golden tests contra QuantLib | Para cada instrumento: inputs, expected clean/dirty/accrued/YTM/duration/convexity/cash flows, motor de referencia, tolerancia documentada. QuantLib solo como dependencia de test/dev, no runtime. Transforma "97% coverage" en "coincide con QuantLib para N casos dentro de tolerancia documentada" — mucho más creíble. | pendiente |
| Invariantes analíticas | par→100 en fecha de cupón; precio monótono decreciente en yield; convexidad ≥ 0 con flujos positivos; `sum(principal) == face`; `dirty == clean + accrued`; `factor ∈ [0,1]`; `DV01 ≈ D_mod·P·1e-4` dentro de tolerancia. | pendiente |
| Property-based testing con `hypothesis` | Generación de schedules: stubs, fin de mes, años bisiestos, frecuencias mixtas — encuentra edge cases que los tests example-based no encuentran. | pendiente |
| `--cov-fail-under` en CI | Evitar regresión silenciosa de cobertura. | pendiente |

---

## Bloque 6 — Ingeniería y repo (P1/P2 — no bloquea lo anterior, se puede intercalar)

| Ítem | Detalle | Estado |
|---|---|---|
| `mypy` en CI | Está en `dev` deps, pasa limpio hoy, pero no corre en el pipeline. Ponerlo antes de que deje de pasar en silencio. | pendiente |
| `py.typed` | Falta en el paquete propio — quien lo instale no recibe los tipos, se pierde todo el trabajo de tipado río abajo. | pendiente |
| Sacar `numpy` de dependencias (o vectorizar de verdad) | Ver Bloque 0.7 — cero usos confirmados. | pendiente |
| Alinear versión y narrativa | `0.1.0`/Beta vs README "v1.0 feature-complete". Mantener `0.x` hasta cerrar market conventions + validación externa + arquitectura de curva + API estable, y recién ahí reservar `1.0` para compromiso de estabilidad de API. Agregar tags/releases/CHANGELOG. | pendiente |
| `sys.path.insert()` en el Streamlit app | El demo debería consumir el paquete igual que cualquier usuario (`from fixed_income import ...` vía instalación editable), no hackear el path — señal de madurez de packaging. | pendiente |
| CI: cerrar el círculo | Sumar a lint+pytest actuales: `mypy`, coverage threshold, `python -m build`, instalar el wheel generado, smoke import, docs build. | pendiente |
| `ruff format`, pre-commit, dependabot | | pendiente |
| Demo desplegado / GIF en README | Streamlit Community Cloud + GIF — mayor retorno por hora invertida para un repo con 0 estrellas, aunque no toca correctitud. | pendiente |
| PyPI | Hoy el README pide `git clone` — barrera de adopción si se quiere posicionar como librería. Ver Anexo (depende de si se persigue adopción externa o portfolio personal). | pendiente |
| Performance: cachear flujos, precomputar vector de `t` | `generate_schedule()` corre 2 veces por `analyze_bond`; `brentq` reprecia recalculando `year_fraction` en cada iteración. Sin tocar arquitectura, un orden de magnitud de mejora. Ver Anexo — números no re-verificados de forma independiente. | pendiente |
| Política de redondeo por mercado / `Decimal` en montos | Hoy todo es `float` sin redondeo específico por convención de mercado. Ver Anexo — depende de si el objetivo es liquidación real o analítica. | pendiente |

---

## Bloque 7 — Decisión estratégica de diferenciación (BLOQUEA priorización fina de Bloques 3/6-MBS)

Ambas críticas coinciden en que "más instrumentos" no es el eje correcto, pero
proponen ejes distintos. Esto no lo puedo decidir yo — condiciona qué tan lejos
llevar Bloque 3 (Market/FRN) y si vale la pena empezar `PrepaymentModel`/CPR/PSA/WAL.

| Opción | Tesis | A favor |
|---|---|---|
| **(a) Librería de renta fija legible** | "QuantLib explicado" — cada módulo con su derivación, notebooks que muestran el porqué. Defendible, el README ya apunta ahí. | Menor esfuerzo, coherente con lo que ya existe. |
| **(b) Mercado local (LatAm)** | Bonos indexados por inflación (UVA, UF, UDI), amortizables locales, convenciones y calendarios por plaza. No existe nada bueno open source y es tu dominio real de negocio. | Mayor valor diferencial dado tu perfil (banca, MMG). |
| **(c) Factors/MBS transparency** | `original_face → factor → current_face` ya es la semilla; sumar `historical vs projected factor`, CPR/SMM/PSA, WAL, provenance por cash flow (¿contractual? ¿proyectado? ¿de qué fixing/modelo salió?). | La arquitectura actual (factor-driven amortizing) ya encaja sorprendentemente bien acá. |
| **(d) Capa de automatización** | El Bloque 4/6 (CLI, ingesta CSV/Excel, export, logging) como producto principal — la librería es el motor, el producto es el pipeline hacia tu trabajo diario. | Puente directo a tareas que ya automatizás en el sector bursátil. |

**No se empieza a ejecutar nada de esto hasta que se elija.** Ver Anexo para el
detalle de qué depende de cada opción.

---

## Orden de trabajo sugerido

1. **Bloque 0** completo (bugs confirmados) — sin esto, todo lo que se construya
   encima está sobre números mal calculados.
2. **Bloque 1** (market conventions) en paralelo con **Bloque 5** (golden tests
   contra QuantLib) — cada fix de convención se ancla con un golden test al mismo
   tiempo, no después.
3. **Bloque 7** — decisión estratégica. No bloquea 0/1/5, pero sí todo lo que
   sigue después.
4. **Bloque 2** (curvas) → **Bloque 3** (FRN/Market) → **Bloque 4** (portfolio),
   en ese orden, salvo que la decisión del Bloque 7 reordene algo.
5. **Bloque 6** (ingeniería) intercalado donde convenga — nada ahí es bloqueante.

---

## Anexo — Incertidumbres y decisiones pendientes de Alberto

Cosas que quedan afuera del cuerpo principal porque no están confirmadas — ni por
verificación propia, ni porque dependen de un criterio de negocio que solo Alberto
tiene.

- **Números de performance** (`analyze_bond` ~2.7ms, YTM solve ~3ms, ~15s para
  repreciar 5.000 posiciones) — vienen de la primera crítica, no los reproduje yo
  mismo con profiling. Antes de tratarlos como bug de performance, correr un
  profile propio.
- **¿Discontinuar el "descuento a `payment_date` ajustado" es realmente incorrecto,
  o es una decisión de diseño legítima?** El bug 0.1 es real como *inconsistencia*
  (el devengo usa fechas sin ajustar, el descuento usa fechas ajustadas), pero
  descontar al día en que el cash realmente cambia de manos no es descabellado en
  sí mismo. La solución correcta (política de tiempo explícita e inyectable) es la
  misma sea cual sea el criterio — pero vale confirmar con Alberto qué convención
  quiere que sea el *default*.
- **¿Se persigue adopción externa (PyPI, estrellas, README con GIF) o es
  primariamente pieza de portafolio?** Cambia la prioridad relativa de Bloque 6
  (empaquetado/demo) vs Bloque 0/1/5 (correctitud).
- **Decimal vs float para montos**: solo importa si en algún momento el objetivo
  pasa de "analítica" a "liquidación real". Sin confirmar cuál es el caso, no vale
  la pena el esfuerzo de introducir `Decimal` en la capa de montos.
- **Alcance de calendario de feriados**: si la decisión del Bloque 7 es (b) mercado
  local, el calendario configurable del Bloque 1 necesita feriados de plazas
  LatAm específicas (no solo un `Calendar` genérico tipo US/UK). Afecta el diseño
  del objeto `Calendar`, no solo su existencia.
- **`reset_lag_days` como "2 días hábiles bajo calendario de fixing"**: correcto
  como crítica, pero qué calendario de fixing usar (SOFR, o el que aplique) depende
  de qué índices de referencia se planea soportar — no decidido.
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
