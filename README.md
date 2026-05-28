# 🔍 Licitaciones IA & Ciberseguridad — Informe Automático

Recibe cada mañana en tu correo las **nuevas licitaciones** de Inteligencia Artificial y Ciberseguridad publicadas en la [Plataforma de Contratación del Sector Público](https://contrataciondelsectorpublico.gob.es).

**Sin servidor. Sin cron. Sin mantenimiento.** Se ejecuta gratis con GitHub Actions.

---

## ⚡ Setup en 5 minutos

### Paso 1 — Fork del repositorio

Dale al botón **Fork** arriba a la derecha (o clona y sube a tu GitHub).

### Paso 2 — Crear una App Password de Gmail

> Si usas otro proveedor de email, salta este paso y usa tus credenciales SMTP.

1. Ve a [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Selecciona **"Otra aplicación"** → pon nombre "Licitaciones"
3. Google te dará una contraseña de 16 caracteres tipo `abcd efgh ijkl mnop`
4. **Cópiala** — la necesitas en el paso 3

> Necesitas tener la verificación en 2 pasos activada en tu cuenta de Google.

### Paso 3 — Configurar Secrets en GitHub

Ve a tu repositorio → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Crea estos 5 secrets:

| Secret | Valor | Ejemplo |
|--------|-------|---------|
| `SMTP_SERVER` | Servidor SMTP | `smtp.gmail.com` |
| `SMTP_PORT` | Puerto SMTP | `587` |
| `EMAIL_USER` | Tu email (remitente) | `tu.nombre@gmail.com` |
| `EMAIL_PASSWORD` | App Password de Gmail | `abcd efgh ijkl mnop` |
| `EMAIL_TO` | Email(s) destino (separados por coma) | `tu@empresa.com, otro@empresa.com` |

### Paso 4 — ¡Listo!

El workflow se ejecuta automáticamente **de lunes a viernes a las 7:00 (hora España)**.

Para probarlo ahora mismo: ve a **Actions** → **Informe Diario Licitaciones IA & Ciber** → **Run workflow**.

---

## 📬 Qué recibes

Un email con:

- **Dashboard visual** con todas las licitaciones encontradas
- **Badges de CPV** que coinciden (48xxx Software, 72xxx Servicios TI)
- **Badges de keywords** encontradas (IA, Ciber, Machine Learning...)
- **Importe**, **fecha límite** y **enlace directo** a la PLACSP
- **CSV adjunto** con todos los datos para abrir en Excel

El sistema recuerda qué licitaciones ya te ha enviado y **solo te manda las nuevas**.

---

## ⚙️ Personalización

### Cambiar la hora de ejecución

Edita `.github/workflows/informe-diario.yml`, línea del `cron`:

```yaml
schedule:
  - cron: '0 5 * * 1-5'   # 7:00 CET (L-V)
  # Otros ejemplos:
  # - cron: '0 6 * * *'   # 8:00 CET, todos los días
  # - cron: '0 5 * * 1'   # Solo lunes 7:00 CET
  # - cron: '0 5,11 * * 1-5'  # 7:00 y 13:00 CET (L-V)
```

> La hora está en UTC. España peninsular = UTC+1 (invierno) / UTC+2 (verano).

### Añadir o quitar palabras clave

Edita `buscador.py`, sección `PALABRAS_CLAVE`:

```python
PALABRAS_CLAVE = [
    "inteligencia artificial",
    "machine learning",
    "ciberseguridad",
    "ciber",
    "blockchain",           # ← añadir
    "computación cuántica",  # ← añadir
    # "rpa",                # ← comentar para desactivar
]
```

### Añadir o quitar códigos CPV

```python
CPV_PREFIJOS = ["48", "72", "64"]   # 64 = Telecomunicaciones
```

### Cambiar la fuente de datos (mes/año)

Puedes lanzar manualmente el workflow y especificar un mes concreto (AAAAMM):

**Actions** → **Run workflow** → en "Mes específico" pon `202605`

---

## 🏗️ Cómo funciona

```
GitHub Actions (cron diario 7:00)
       │
       ▼
  Descarga ZIP de PLACSP
  (datos abiertos oficiales)
       │
       ▼
  Parsea XML Atom/CODICE 2.07
  (estándar UBL/OASIS)
       │
       ▼
  Filtra por CPV 48*/72*
  + keywords IA/Ciber
  + estado Publicada
       │
       ▼
  Compara con historial
  (solo licitaciones nuevas)
       │
       ▼
  Envía email HTML + CSV
```

---

## 📊 Códigos CPV monitorizados

| Código | Descripción |
|--------|-------------|
| **48000000** | Paquetes de software y sistemas de información |
| **48100000** | Paquetes de software para la industria |
| **48200000** | Software de red, Internet e intranet |
| **48400000** | Software de transacciones y gestión |
| **48800000** | Sistemas de información |
| **72000000** | Servicios TI: consultoría, desarrollo, Internet |
| **72200000** | Programación y consultoría informática |
| **72300000** | Servicios de tratamiento de datos |
| **72500000** | Servicios informáticos |
| **72600000** | Apoyo y consultoría informática |

---

## 🔧 Troubleshooting

**No recibo emails:**
- Verifica que los 5 Secrets están bien configurados en GitHub
- Comprueba la carpeta de Spam
- Lanza el workflow manualmente y revisa los logs en Actions

**El workflow falla:**
- El servidor PLACSP puede tener cortes temporales, el workflow lo reintenta automáticamente al día siguiente
- Revisa los logs en **Actions** → click en el run fallido

**Quiero resetear el historial de "vistas":**
- Ve a **Actions** → **Caches** → elimina las caches que empiecen por `licitaciones-vistas`

---

## 📝 Notas

- **Gratis**: GitHub Actions da 2.000 minutos/mes en repos públicos y 500 en privados
- **Sin dependencias**: el script usa solo la librería estándar de Python
- **Datos oficiales**: fuente directa de contrataciondelsectorpublico.gob.es (datos abiertos)
- **Privacidad**: tu email y contraseña se guardan como Secrets cifrados de GitHub, nunca se exponen en logs
