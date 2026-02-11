import streamlit as st
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
from io import BytesIO

# --- PDF GENERATION LIBRARY ---
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="Vertex Roofing Calculator", layout="wide")

# --- 2. PDF GENERATOR FUNCTION ---
def generate_pdf(project_name, u_val, risk, layers_data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # Title
    elements.append(Paragraph("Vertex Roofing Systems", styles["Title"]))
    elements.append(Paragraph("Thermal Calculation & Condensation Risk Analysis", styles["Heading2"]))
    elements.append(Spacer(1, 12))

    # Project Info
    elements.append(Paragraph(f"<b>Project:</b> {project_name}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Results
    u_text = f"Calculated U-Value: <b>{u_val:.3f} W/m²K</b>"
    elements.append(Paragraph(u_text, styles["Normal"]))
    
    risk_text = "Condensation Risk: <font color='red'><b>DETECTED</b></font>" if risk else "Condensation Risk: <font color='green'><b>NONE (Safe)</b></font>"
    elements.append(Paragraph(risk_text, styles["Normal"]))
    elements.append(Spacer(1, 20))

    # Data Table
    # Convert list of dicts to list of lists for ReportLab
    # We list layers Top (Outside) -> Bottom (Inside) to match user input
    table_data = [["Layer Name", "Thickness (mm)", "Lambda (W/mK)", "Mu Value"]]
    for layer in layers_data:
        table_data.append([
            layer['name'], 
            str(layer['thickness']), 
            str(layer['lambda']), 
            str(layer['mu']) if not np.isnan(layer['mu']) else "-"
        ])

    t = Table(table_data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(t)
    
    # Build
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- 3. LOAD DATABASE ---
@st.cache_data
def load_data():
    try:
        return pd.read_csv("materials.csv")
    except:
        return None

df_materials = load_data()
if df_materials is None:
    st.error("Error: materials.csv not found. Please upload it to GitHub.")
    st.stop()

# --- 4. PHYSICS ENGINE ---
def calculate_dewpoint(vp):
    if vp <= 0: return -50
    return (237.7 * math.log(vp/610.5)) / (17.27 - math.log(vp/610.5))

def run_condensation_analysis(layers, t_in, rh_in, t_out, rh_out):
    psat_in = 610.5 * math.exp((17.27 * t_in) / (237.7 + t_in))
    pv_in = psat_in * (rh_in / 100)
    psat_out = 610.5 * math.exp((17.27 * t_out) / (237.7 + t_out))
    pv_out = psat_out * (rh_out / 100)
    
    total_r = 0.14
    total_rv = 0
    processed = []
    
    for layer in layers:
        thick_m = layer['thickness'] / 1000
        r = thick_m / layer['lambda'] if layer['lambda'] > 0 else 0
        if not np.isnan(layer['r_vap']): 
            rv = layer['r_vap'] 
        else:
            rv = layer['mu'] * thick_m * 5 
        total_r += r
        total_rv += rv
        processed.append({'r': r, 'rv': rv, 'thick': layer['thickness'], 'name': layer['name']})

    points = {'x': [0], 'temp': [t_in], 'dew': [calculate_dewpoint(pv_in)]}
    curr = {'temp': t_in, 'pv': pv_in, 'x': 0}
    risk = False
    
    dt = (t_in - t_out) * (0.10 / total_r)
    curr['temp'] -= dt
    points['x'].append(0)
    points['temp'].append(curr['temp'])
    points['dew'].append(calculate_dewpoint(curr['pv']))

    for p in processed:
        dt = (t_in - t_out) * (p['r'] / total_r)
        dp = (pv_in - pv_out) * (p['rv'] / total_rv) if total_rv > 0 else 0
        curr['temp'] -= dt
        curr['pv'] -= dp
        curr['x'] += p['thick']
        dp_temp = calculate_dewpoint(curr['pv'])
        points['x'].append(curr['x'])
        points['temp'].append(curr['temp'])
        points['dew'].append(dp_temp)
        if dp_temp >= curr['temp']: risk = True
            
    return points, risk, 1/total_r

# --- 5. INTERFACE ---
col_header1, col_header2 = st.columns([1, 4])
with col_header1:
    st.image("logo.jpg", width=150)
with col_header2:
    st.title("Vertex Roofing Systems")
    st.markdown("**Thermal Calculation & Condensation Risk Analysis**")

# Sidebar
st.sidebar.header("Project Settings")
project_name = st.sidebar.text_input("Project Name", "Daisy Lodge")
st.sidebar.subheader("Environment")
