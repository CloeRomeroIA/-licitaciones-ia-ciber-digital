#!/usr/bin/env python3
"""
Buscador automático de licitaciones PLACSP
Descarga, filtra y envía por email licitaciones de IA y Ciberseguridad.
Diseñado para ejecutarse como GitHub Actions scheduled workflow.
"""

import csv
import html as html_lib
import io
import json
import logging
import os
import re
import smtplib
import ssl
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ─────────────────────────────────────────────────────────────────
# CONFIGURACIÓN — edita esto a tu gusto
# ─────────────────────────────────────────────────────────────────

# Prefijos CPV a monitorizar
CPV_PREFIJOS = ["48", "72"]

# Palabras clave (case-insensitive, se normalizan acentos)
PALABRAS_CLAVE = [
    "inteligencia artificial",
    "machine learning",
    "aprendizaje automático",
    "aprendizaje automatico",
    "deep learning",
    "aprendizaje profundo",
    "ciberseguridad",
    "ciberdefensa",
    "ciberamenaza",
    "ciberresiliencia",
    "ciberinteligencia",
    "ciber",
    " ia ",
    " i.a.",
    "llm",
    "modelo de lenguaje",
    "modelos de lenguaje",
    "redes neuronales",
    "red neuronal",
    "visión artificial",
    "vision artificial",
    "procesamiento de lenguaje natural",
    "procesamiento del lenguaje natural",
    "nlp",
    "chatbot",
    "automatización inteligente",
    "automatizacion inteligente",
    "transformación digital",
    "transformacion digital",
    "datos masivos",
    "big data",
    "robotic process automation",
    "rpa",
    "analítica avanzada",
    "analitica avanzada",
]

# Estados de licitación activa
ESTADOS_CODIGOS = ["pub", "ev"]
ESTADOS_TEXTO = [
    "en plazo",
    "publicada",
    "anuncio previo",
    "pendiente de adjudicación",
    "pendiente de adjudicacion",
]

# URL base PLACSP datos abiertos (sindicación 643)
BASE_URL = "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643"

# Límites de seguridad
MAX_ATOM_FILES = 300
HTTP_TIMEOUT = 90
HTTP_RETRIES = 3
DELAY_ENTRE_DESCARGAS = 0.5

# ─────────────────────────────────────────────────────────────────
# NAMESPACES XML
# ─────────────────────────────────────────────────────────────────

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc":  "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac":  "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "gc":   "urn:dgpe:names:draft:codice:schema:xsd:ContractFolderStatusExtension",
    "cbc2": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac2": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("buscador")

# ─────────────────────────────────────────────────────────────────
# MODELO
# ─────────────────────────────────────────────────────────────────

@dataclass
class Licitacion:
    id: str = ""
    expediente: str = ""
    titulo: str = ""
    organo_contratacion: str = ""
    estado: str = ""
    tipo_contrato: str = ""
    cpv_codigos: list = field(default_factory=list)
    importe: str = ""
    fecha_publicacion: str = ""
    fecha_limite: str = ""
    enlace: str = ""
    lugar_ejecucion: str = ""
    procedimiento: str = ""
    descripcion: str = ""
    palabras_encontradas: list = field(default_factory=list)
    match_cpv: bool = False
    match_keyword: bool = False
    updated: str = ""

# ─────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────

def descargar(url: str) -> bytes:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = Request(url, headers={"User-Agent": "BuscadorLicitaciones/2.0"})
    for intento in range(1, HTTP_RETRIES + 1):
        try:
            with urlopen(req, context=ctx, timeout=HTTP_TIMEOUT) as resp:
                return resp.read()
        except (URLError, HTTPError, TimeoutError, OSError) as e:
            log.warning(f"  Intento {intento}/{HTTP_RETRIES}: {e}")
            if intento < HTTP_RETRIES:
                time.sleep(DELAY_ENTRE_DESCARGAS * intento * 2)
            else:
                raise


def _ft(elem, paths, default=""):
    """Find text in multiple XPaths."""
    if elem is None:
        return default
    for p in paths:
        f = elem.find(p, NS)
        if f is not None and f.text:
            return f.text.strip()
    return default


def normalizar(texto: str) -> str:
    """Normaliza acentos para búsqueda flexible."""
    for a, b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ü","u"),("ñ","n")]:
        texto = texto.replace(a, b)
    return texto

# ─────────────────────────────────────────────────────────────────
# PARSER CODICE
# ─────────────────────────────────────────────────────────────────

def parsear_entry(entry) -> Optional[Licitacion]:
    lic = Licitacion()

    lic.id = _ft(entry, ["atom:id"])
    lic.titulo = _ft(entry, ["atom:title"])
    lic.updated = _ft(entry, ["atom:updated"])

    link_el = entry.find("atom:link[@rel='alternate']", NS)
    if link_el is None:
        link_el = entry.find("atom:link", NS)
    if link_el is not None:
        lic.enlace = link_el.get("href", "")

    summary = _ft(entry, ["atom:summary", "atom:content"])
    lic.descripcion = re.sub(r'<[^>]+>', ' ', summary)

    # Buscar ContractFolderStatus
    cfs = None
    for path in [
        ".//gc:ContractFolderStatus",
        ".//cac:ContractFolderStatus",
    ]:
        cfs = entry.find(path, NS)
        if cfs is not None:
            break

    if cfs is None and summary and "<" in summary:
        try:
            raw = html_lib.unescape(summary)
            wrapped = f"<r xmlns:cbc='{NS['cbc']}' xmlns:cac='{NS['cac']}' xmlns:gc='{NS['gc']}'>{raw}</r>"
            root_tmp = ET.fromstring(wrapped)
            for path in [".//gc:ContractFolderStatus", ".//cac:ContractFolderStatus"]:
                cfs = root_tmp.find(path, NS)
                if cfs is not None:
                    break
        except ET.ParseError:
            pass

    if cfs is not None:
        lic.expediente = _ft(cfs, ["cbc:ContractFolderID", "cbc2:ContractFolderID"])
        lic.estado = _ft(cfs, ["cbc:ContractFolderStatusCode", "cbc2:ContractFolderStatusCode"])

        lic.organo_contratacion = _ft(cfs, [
            "cac:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name",
            "cac2:LocatedContractingParty/cac2:Party/cac2:PartyName/cbc2:Name",
        ])

        pp = cfs.find("cac:ProcurementProject", NS) or cfs.find("cac2:ProcurementProject", NS)
        if pp is not None:
            nombre = _ft(pp, ["cbc:Name", "cbc2:Name"])
            if nombre:
                lic.titulo = nombre

            lic.tipo_contrato = _ft(pp, ["cbc:TypeCode", "cbc2:TypeCode"])

            budget = pp.find("cac:BudgetAmount", NS) or pp.find("cac2:BudgetAmount", NS)
            if budget is not None:
                lic.importe = _ft(budget, [
                    "cbc:TotalAmount", "cbc2:TotalAmount",
                    "cbc:EstimatedOverallContractAmount",
                    "cbc:TaxExclusiveAmount",
                ])

            for ns_prefix in ["cac", "cac2"]:
                for cc in pp.findall(f"{ns_prefix}:RequiredCommodityClassification", NS):
                    code = _ft(cc, ["cbc:ItemClassificationCode", "cbc2:ItemClassificationCode"])
                    if code and code not in lic.cpv_codigos:
                        lic.cpv_codigos.append(code)

            rl = pp.find("cac:RealizedLocation", NS) or pp.find("cac2:RealizedLocation", NS)
            if rl is not None:
                lic.lugar_ejecucion = _ft(rl, ["cbc:CountrySubentity", "cbc2:CountrySubentity"])

        tp = cfs.find("cac:TenderingProcess", NS) or cfs.find("cac2:TenderingProcess", NS)
        if tp is not None:
            lic.procedimiento = _ft(tp, ["cbc:ProcedureCode", "cbc2:ProcedureCode"])
            dl = (tp.find("cac:TenderSubmissionDeadlinePeriod", NS)
                  or tp.find("cac2:TenderSubmissionDeadlinePeriod", NS))
            if dl is not None:
                lic.fecha_limite = _ft(dl, ["cbc:EndDate", "cbc2:EndDate"])

        vni = cfs.find("cac:ValidNoticeInfo", NS)
        if vni is not None:
            adp = vni.find("cac:AdditionalPublicationDocumentReference", NS)
            if adp is not None:
                lic.fecha_publicacion = _ft(adp, ["cbc:IssueDate"])

        # CPV en lotes
        for lote in cfs.findall(".//cac:ProcurementProjectLot", NS):
            pp_l = lote.find("cac:ProcurementProject", NS)
            if pp_l is not None:
                for cc in pp_l.findall("cac:RequiredCommodityClassification", NS):
                    code = _ft(cc, ["cbc:ItemClassificationCode"])
                    if code and code not in lic.cpv_codigos:
                        lic.cpv_codigos.append(code)

    if not lic.fecha_publicacion:
        lic.fecha_publicacion = lic.updated[:10] if lic.updated else ""

    return lic

# ─────────────────────────────────────────────────────────────────
# FILTROS
# ─────────────────────────────────────────────────────────────────

def cumple_cpv(lic: Licitacion) -> bool:
    for codigo in lic.cpv_codigos:
        for prefijo in CPV_PREFIJOS:
            if codigo.startswith(prefijo):
                return True
    return False


def cumple_estado(lic: Licitacion) -> bool:
    estado = lic.estado.lower()
    for c in ESTADOS_CODIGOS:
        if c in estado:
            return True
    for t in ESTADOS_TEXTO:
        if t in estado:
            return True
    if not estado:
        return True
    return False


def buscar_keywords(lic: Licitacion) -> list:
    texto = normalizar(f" {lic.titulo} {lic.descripcion} {lic.organo_contratacion} ".lower())
    encontradas = set()
    for kw in PALABRAS_CLAVE:
        if normalizar(kw.lower()) in texto:
            encontradas.add(kw.strip())
    return sorted(encontradas)


def aplicar_filtros(licitaciones: list) -> list:
    resultado = []
    for lic in licitaciones:
        if not cumple_estado(lic):
            continue
        lic.match_cpv = cumple_cpv(lic)
        lic.palabras_encontradas = buscar_keywords(lic)
        lic.match_keyword = len(lic.palabras_encontradas) > 0
        if lic.match_cpv or lic.match_keyword:
            resultado.append(lic)
    return resultado

# ─────────────────────────────────────────────────────────────────
# DESCARGA Y PROCESAMIENTO
# ─────────────────────────────────────────────────────────────────

def procesar_atom(xml_bytes: bytes) -> list:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.error(f"  XML parse error: {e}")
        return []
    lics = []
    for entry in root.findall("atom:entry", NS):
        try:
            lic = parsear_entry(entry)
            if lic:
                lics.append(lic)
        except Exception:
            continue
    return lics


def descargar_y_procesar(mes: str = None, anual: str = None) -> list:
    """
    Descarga el ZIP de PLACSP y devuelve todas las licitaciones parseadas.
    mes: AAAAMM (ej: 202605)
    anual: AAAA (ej: 2026)
    """
    if anual:
        url = f"{BASE_URL}/licitacionesPerfilesContratanteCompleto3_{anual}.zip"
    elif mes:
        url = f"{BASE_URL}/licitacionesPerfilesContratanteCompleto3_{mes}.zip"
    else:
        ahora = datetime.now()
        mes = ahora.strftime("%Y%m")
        url = f"{BASE_URL}/licitacionesPerfilesContratanteCompleto3_{mes}.zip"

    log.info(f"📦 Descargando: {url}")
    data = descargar(url)
    log.info(f"   Descargado: {len(data) / 1024 / 1024:.1f} MB")

    todas = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        atom_files = sorted([f for f in zf.namelist() if f.endswith(".atom") or f.endswith(".xml")])
        log.info(f"   {len(atom_files)} ficheros Atom en el ZIP")

        for i, fname in enumerate(atom_files[:MAX_ATOM_FILES]):
            try:
                xml_bytes = zf.read(fname)
                lics = procesar_atom(xml_bytes)
                todas.extend(lics)
            except Exception as e:
                log.warning(f"   Error en {fname}: {e}")

            if (i + 1) % 50 == 0:
                log.info(f"   Procesados {i+1}/{len(atom_files)} — {len(todas)} licitaciones")

    log.info(f"📥 Total parseadas: {len(todas)}")
    return todas

# ─────────────────────────────────────────────────────────────────
# CONTROL DE DUPLICADOS
# ─────────────────────────────────────────────────────────────────

SEEN_FILE = "licitaciones_vistas.json"

def cargar_vistos() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            data = json.load(f)
            # Limpiar entries con más de 90 días
            cutoff = (datetime.now() - timedelta(days=90)).isoformat()
            return {k for k, v in data.items() if v > cutoff} if isinstance(data, dict) else set(data)
    return set()


def guardar_vistos(vistos: dict):
    with open(SEEN_FILE, "w") as f:
        json.dump(vistos, f, indent=2)


def filtrar_nuevas(licitaciones: list) -> list:
    vistos = cargar_vistos()
    nuevas = [l for l in licitaciones if l.id not in vistos]

    # Actualizar registro
    ahora = datetime.now().isoformat()
    registro = {}
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            raw = json.load(f)
            registro = raw if isinstance(raw, dict) else {k: ahora for k in raw}

    for l in licitaciones:
        registro[l.id] = ahora

    guardar_vistos(registro)
    log.info(f"🆕 Nuevas: {len(nuevas)} de {len(licitaciones)}")
    return nuevas

# ─────────────────────────────────────────────────────────────────
# EMAIL — cuerpo HTML del informe
# ─────────────────────────────────────────────────────────────────

def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_importe(val):
    try:
        return f'{float(val):,.2f} €'.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return val or "—"


def generar_email_html(licitaciones: list, es_nuevas: bool = True) -> str:
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    tipo = "nuevas " if es_nuevas else ""

    if not licitaciones:
        return f"""
        <html><body style="font-family: -apple-system, Arial, sans-serif; color: #1a1a2e; padding: 24px;">
        <h2 style="color: #4361ee;">🔍 Informe de Licitaciones IA & Ciber</h2>
        <p style="color: #666;">{ahora}</p>
        <div style="background: #f0f4ff; border-radius: 12px; padding: 32px; text-align: center; margin: 24px 0;">
            <p style="font-size: 18px; color: #4361ee;">✅ No se han encontrado {tipo}licitaciones hoy</p>
            <p style="color: #888;">Los filtros activos son CPV 48/72 + keywords IA y Ciber</p>
        </div>
        </body></html>"""

    rows = []
    for i, lic in enumerate(licitaciones, 1):
        kw_badges = " ".join(
            f'<span style="background:#ede9fe;color:#7c3aed;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{_esc(k)}</span>'
            for k in lic.palabras_encontradas[:4]
        )
        cpv_badges = " ".join(
            f'<span style="background:{"#d1fae5" if any(c.startswith(p) for p in CPV_PREFIJOS) else "#f1f5f9"};color:{"#059669" if any(c.startswith(p) for p in CPV_PREFIJOS) else "#64748b"};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{c}</span>'
            for c in lic.cpv_codigos[:3]
        )
        enlace = f'<a href="{lic.enlace}" style="color:#4361ee;text-decoration:none;font-weight:600;">Ver ↗</a>' if lic.enlace else "—"

        bg = "#ffffff" if i % 2 == 1 else "#fafbff"
        rows.append(f"""
        <tr style="background:{bg};">
            <td style="padding:14px 12px;border-bottom:1px solid #e2e8f0;vertical-align:top;">
                <div style="font-weight:600;color:#1e293b;margin-bottom:4px;line-height:1.4;">{_esc(lic.titulo[:120])}</div>
                <div style="margin-bottom:4px;">
                    <span style="font-size:12px;color:#94a3b8;font-family:monospace;">Exp: {_esc(lic.expediente)}</span>
                </div>
                <div>{kw_badges} {cpv_badges}</div>
            </td>
            <td style="padding:14px 8px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569;vertical-align:top;">{_esc(lic.organo_contratacion[:60])}</td>
            <td style="padding:14px 8px;border-bottom:1px solid #e2e8f0;font-weight:700;color:#059669;white-space:nowrap;vertical-align:top;font-size:13px;">{_fmt_importe(lic.importe)}</td>
            <td style="padding:14px 8px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#dc2626;vertical-align:top;">{_esc(lic.fecha_limite) or "—"}</td>
            <td style="padding:14px 8px;border-bottom:1px solid #e2e8f0;vertical-align:top;">{enlace}</td>
        </tr>""")

    total_importe = 0
    for l in licitaciones:
        try:
            total_importe += float(l.importe)
        except (ValueError, TypeError):
            pass

    return f"""
    <html>
    <body style="font-family: -apple-system, 'Segoe UI', Arial, sans-serif; color: #1e293b; padding: 0; margin: 0; background: #f8fafc;">
    <div style="max-width: 900px; margin: 0 auto; padding: 24px;">

        <!-- Header -->
        <div style="background: linear-gradient(135deg, #4361ee 0%, #7c3aed 100%); border-radius: 16px; padding: 28px 32px; margin-bottom: 24px; color: white;">
            <h1 style="margin: 0 0 4px 0; font-size: 22px; font-weight: 700;">🔍 Licitaciones IA & Ciberseguridad</h1>
            <p style="margin: 0; opacity: 0.85; font-size: 14px;">PLACSP — Informe automático · {ahora}</p>
        </div>

        <!-- Stats -->
        <div style="display: flex; gap: 12px; margin-bottom: 24px;">
            <div style="flex:1; background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: #4361ee;">{len(licitaciones)}</div>
                <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">{tipo}Licitaciones</div>
            </div>
            <div style="flex:1; background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: #059669;">{sum(1 for l in licitaciones if l.match_cpv)}</div>
                <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">Match CPV 48/72</div>
            </div>
            <div style="flex:1; background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: #7c3aed;">{sum(1 for l in licitaciones if l.match_keyword)}</div>
                <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">Match Keywords</div>
            </div>
            <div style="flex:1; background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: #f59e0b;">{_fmt_importe(str(total_importe)) if total_importe else '—'}</div>
                <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">Importe Total</div>
            </div>
        </div>

        <!-- Filtros activos -->
        <div style="background: #f0f4ff; border-radius: 10px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: #4361ee;">
            <strong>Filtros:</strong>
            CPV 48* (Software), 72* (Servicios TI) ·
            Keywords: IA, Ciber, Machine Learning, NLP, Deep Learning... ·
            Estado: Publicada / En Plazo
        </div>

        <!-- Tabla -->
        <table style="width:100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0;">
            <thead>
                <tr style="background: #f1f5f9;">
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0;">Licitación</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0;">Órgano</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0;">Importe</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0;">Fecha Límite</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0;">Enlace</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>

        <!-- Footer -->
        <div style="text-align: center; color: #94a3b8; font-size: 12px; margin-top: 24px; padding-top: 16px; border-top: 1px solid #e2e8f0;">
            Fuente: contrataciondelsectorpublico.gob.es · Datos abiertos PLACSP ·
            Automatización con GitHub Actions
        </div>

    </div>
    </body>
    </html>"""


def generar_csv_adjunto(licitaciones: list) -> str:
    output = io.StringIO()
    campos = [
        "expediente", "titulo", "organo_contratacion", "estado",
        "cpv_codigos", "importe", "fecha_publicacion", "fecha_limite",
        "procedimiento", "lugar_ejecucion", "palabras_encontradas",
        "match_cpv", "match_keyword", "enlace",
    ]
    writer = csv.DictWriter(output, fieldnames=campos, delimiter=";")
    writer.writeheader()
    for lic in licitaciones:
        row = asdict(lic)
        row["cpv_codigos"] = ", ".join(lic.cpv_codigos)
        row["palabras_encontradas"] = ", ".join(lic.palabras_encontradas)
        writer.writerow({k: row.get(k, "") for k in campos})
    return output.getvalue()

# ─────────────────────────────────────────────────────────────────
# ENVÍO DE EMAIL
# ─────────────────────────────────────────────────────────────────

def enviar_email(licitaciones: list, es_nuevas: bool = True):
    """Envía el informe por email usando variables de entorno."""
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    email_user = os.environ.get("EMAIL_USER", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    email_to = os.environ.get("EMAIL_TO", "")

    if not email_user or not email_pass or not email_to:
        log.error("❌ Faltan variables de entorno EMAIL_USER, EMAIL_PASSWORD o EMAIL_TO")
        sys.exit(1)

    destinatarios = [e.strip() for e in email_to.split(",")]

    tipo = "nuevas " if es_nuevas else ""
    fecha = datetime.now().strftime("%d/%m/%Y")

    if licitaciones:
        asunto = f"🔔 {len(licitaciones)} {tipo}licitaciones IA/Ciber — {fecha}"
    else:
        asunto = f"✅ Sin {tipo}licitaciones IA/Ciber hoy — {fecha}"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = asunto
    msg["From"] = email_user
    msg["To"] = ", ".join(destinatarios)

    # Cuerpo HTML
    html_body = generar_email_html(licitaciones, es_nuevas)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # CSV adjunto si hay resultados
    if licitaciones:
        csv_content = generar_csv_adjunto(licitaciones)
        csv_part = MIMEBase("text", "csv")
        csv_part.set_payload(csv_content.encode("utf-8-sig"))
        encoders.encode_base64(csv_part)
        csv_part.add_header(
            "Content-Disposition",
            f"attachment; filename=licitaciones_{datetime.now().strftime('%Y%m%d')}.csv",
        )
        msg.attach(csv_part)

    # Enviar
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(email_user, email_pass)
            smtp.send_message(msg)
        log.info(f"📧 Email enviado a {', '.join(destinatarios)}")
    except Exception as e:
        log.error(f"📧 Error enviando email: {e}")
        raise

# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  🔍 BUSCADOR AUTOMÁTICO DE LICITACIONES PLACSP         ║")
    print("║  CPV 48/72 · IA · Ciberseguridad                      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Determinar qué descargar
    mes = os.environ.get("MES")          # AAAAMM
    anual = os.environ.get("ANUAL")      # AAAA
    solo_nuevas = os.environ.get("SOLO_NUEVAS", "true").lower() == "true"
    enviar = os.environ.get("ENVIAR_EMAIL", "true").lower() == "true"

    # 1. Descargar y parsear
    todas = descargar_y_procesar(mes=mes, anual=anual)

    # 2. Filtrar
    filtradas = aplicar_filtros(todas)
    log.info(f"✅ Cumplen filtros: {len(filtradas)}")

    # 3. Solo nuevas (evitar repetir)
    es_nuevas = False
    if solo_nuevas:
        filtradas = filtrar_nuevas(filtradas)
        es_nuevas = True

    # 4. Ordenar por fecha
    filtradas.sort(key=lambda l: l.updated or l.fecha_publicacion or "", reverse=True)

    # 5. Resumen consola
    print(f"\n{'═' * 54}")
    print(f"  Total parseadas:     {len(todas):>6}")
    print(f"  Cumplen filtros:     {len(filtradas):>6}")
    print(f"  Match CPV 48/72:     {sum(1 for l in filtradas if l.match_cpv):>6}")
    print(f"  Match Keywords:      {sum(1 for l in filtradas if l.match_keyword):>6}")
    print(f"{'═' * 54}\n")

    for i, lic in enumerate(filtradas[:10], 1):
        t = lic.titulo[:75] + "..." if len(lic.titulo) > 75 else lic.titulo
        print(f"  {i:>2}. {t}")
        print(f"      CPV: {', '.join(lic.cpv_codigos) or '—'} | KW: {', '.join(lic.palabras_encontradas[:3]) or '—'}")

    # 6. Enviar email
    if enviar:
        enviar_email(filtradas, es_nuevas)
    else:
        # Guardar HTML local
        html = generar_email_html(filtradas, es_nuevas)
        os.makedirs("output", exist_ok=True)
        with open("output/informe.html", "w", encoding="utf-8") as f:
            f.write(html)
        log.info("📄 Informe guardado en output/informe.html")


if __name__ == "__main__":
    main()
