import streamlit as st
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
from io import BytesIO

# --- PDF GENERATION LIBRARY ---
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="Vertex Roofing Calculator", layout="wide")

# --- CLIMATE DATA (From Kingspan Report) ---
# Monthly averages for Galway (or generic worst case)
CLIMATE_DATA = {
    "Galway (ISO 13788)": {
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "temp_out": [-2.2, -2.0, -0.8, 0.7, 2.6, 5.9, 7.9, 7.6, 6.1, 3.0, 0.4, -1.0],
        "rh_out": [92, 91, 91, 93, 92, 92, 93, 94, 94, 93, 93, 93],
        "temp_in": [20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20],
        "rh_in": [66.2, 66.3, 68.5, 70.3, 69.7, 70.4, 72.0, 72.2, 71.3, 70.1, 70.4, 68.6]
    }
}

# --- 2. PDF GENERATOR FUNCTION ---
def generate_pdf(project_name, u_val, risk_result, layers_data, monthly_results=None):
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
    
    risk_color = "red" if "FAIL" in risk_result else "green"
    risk_text = f"Condensation Risk: <font color='{risk_color}'><b>{risk_result}</b></font>"
    elements.append(Paragraph(risk_text, styles["Normal"]))
    elements.append(Spacer(1, 20))

    # Layers Table
    elements.append(Paragraph("<b>Construction Build-Up (Top to Bottom):</b>", styles["Normal"]))
    elements.append(Spacer(1, 6))
    
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
    
    # Monthly Breakdown (If available)
    if monthly_results:
        elements.append(PageBreak())
        elements.append(Paragraph("<b>12-Month Condensation Analysis (Glaser Method)</b>", styles["Heading2"]))
        elements.append(Spacer(1, 12))
        
        m_data = [["Month", "T_out", "RH_out", "Status"]]
        for m in monthly_results:
            status = "RISK" if m['risk'] else "Safe"
            m_data.append([m['month'], f"{m['t_out']} C", f"{m['rh_out']}%", status])
            
        mt = Table(m_data)
        mt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
        ]))
        elements.append(mt)

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

def run_single_glaser(layers, t_in, rh_in, t_out, rh_out):
    # Calculates the profile for ONE specific moment/month
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
    risk_found = False
    
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
        if dp_temp >= curr['temp']: risk_found = True
            
    return points, risk_found, 1/total_r

# --- 5. INTERFACE ---
col_header1, col_header2 = st.columns([1, 4])
with col_header1:
    st.image("logo.jpg", width=150)
with col_header2:
    st.title("Vertex Roofing Systems")
    st.markdown("**Thermal Calculation & Condensation Risk Analysis**")

# --- SIDEBAR: CLIMATE CONTROL ---
st.sidebar.header("Project Settings")
project_name = st.sidebar.text_input("Project Name", "Daisy Lodge")

st.sidebar.write("---")
st.sidebar.header("Climate Data")
calc_mode = st.sidebar.radio("Calculation Mode", ["Manual Input", "Annual Cycle (Galway)"])

t_in, rh_in, t_out, rh_out = 20.0, 66.2, -2.2, 92.0 # Defaults

if calc_mode == "Manual Input":
    st.sidebar.subheader("Manual Conditions")
    t_in = st.sidebar.number_input("Inside Temp (°C)", 20.0)
    rh_in = st.sidebar.number_input("Inside RH (%)", 66.2)
    t_out = st.sidebar.number_input("Outside Temp (°C)", -2.2)
    rh_out = st.sidebar.number_input("Outside RH (%)", 92.0)
else:
    st.sidebar.info("Using 12-month climate data from ISO 13788 (Galway Profile).")

# --- LAYERS LOGIC ---
if 'layers' not in st.session_state:
    st.session_state.layers = [{'name': 'Aluminium', 'thick': 1.0}, {'name': 'Kingspan TR26', 'thick': 100.0}, {'name': 'CLT Panel', 'thick': 160.0}]

def add_layer(): st.session_state.layers.append({'name': 'Siga Wetguard', 'thick': 0.6})
def remove_layer(): 
    if len(st.session_state.layers) > 0: st.session_state.layers.pop()

c1, c2 = st.columns([1, 5])
c1.button("➕ Add Layer", on_click=add_layer)
c2.button("➖ Remove Layer", on_click=remove_layer)

st.write("---")
st.info("💡 **Instructions:** Enter layers from the **TOP** (Outside Weathering) to the **BOTTOM** (Inside Ceiling).")

calc_layers = []
for i, layer in enumerate(st.session_state.layers):
    c1, c2 = st.columns([3, 1])
    with c1:
        idx = df_materials[df_materials['Name'] == layer['name']].index[0] if layer['name'] in df_materials['Name'].values else 0
        new_name = st.selectbox(f"Layer {i+1}", df_materials['Name'], index=int(idx), key=f"mat_{i}")
    with c2:
        new_thick = st.number_input(f"Thickness (mm)", value=float(layer['thick']), min_value=0.0, step=0.1, format="%.1f", key=f"th_{i}")
    
    props = df_materials[df_materials['Name'] == new_name].iloc[0]
    calc_layers.append({'name': new_name, 'thickness': new_thick, 'lambda': props['Lambda'], 'mu': props['Mu'], 'r_vap': props['R_Vap']})

st.write("---")

# --- 6. RUN & EXPORT ---
if st.button("RUN CALCULATIONS", type="primary", use_container_width=True):
    
    # 1. U-Value (Standard check, uses simplified logic)
    # We run one snapshot just to get the U-value for the report
    _, _, u_val = run_single_glaser(calc_layers[::-1], 20, 50, 0, 80)
    
    final_risk_msg = "NONE (Safe)"
    graph_data = None
    monthly_report = []

    # 2. RUN ANALYSIS BASED ON MODE
    if calc_mode == "Manual Input":
        # Run once
        points, risk, _ = run_single_glaser(calc_layers[::-1], t_in, rh_in, t_out, rh_out)
        graph_data = points
        if risk: final_risk_msg = "FAIL (Risk Detected)"
        
    else:
        # Run 12 times (Galway Cycle)
        months = CLIMATE_DATA["Galway (ISO 13788)"]
        risky_months = []
        worst_points = None
        max_overlap = 0 # To track which month looks "worst" on the graph
        
        for i in range(12):
            m_name = months["months"][i]
            ti = months["temp_in"][i]
            rhi = months["rh_in"][i]
            to = months["temp_out"][i]
            rho = months["rh_out"][i]
            
            pts, is_risk, _ = run_single_glaser(calc_layers[::-1], ti, rhi, to, rho)
            monthly_report.append({'month': m_name, 'risk': is_risk, 't_out': to, 'rh_out': rho})
            
            # Check overlap area to find "worst visual" month for plotting
            # Simple heuristic: sum of dew point exceedance
            overlap_score = np.sum(np.maximum(0, np.array(pts['dew']) - np.array(pts['temp'])))
            
            if overlap_score >= max_overlap:
                max_overlap = overlap_score
                worst_points = pts
                worst_month_name = m_name
            
            if is_risk:
                risky_months.append(m_name)
        
        # Logic: If risky months exist, is it acceptable? 
        # For this tool, if ANY condensation occurs, we flag it.
        if len(risky_months) > 0:
            final_risk_msg = f"FAIL (Risk in {', '.join(risky_months)})"
            graph_data = worst_points # Plot the worst month
            st.warning(f"⚠️ Condensation Risk detected during: {', '.join(risky_months)}")
            st.write(f"Graph shows worst case month: **{worst_month_name}**")
        else:
            final_risk_msg = "NONE (Safe Year-Round)"
            graph_data = worst_points # Plot whatever month was closest (usually Jan)
            st.success("✅ Analysis Complete: No condensation risk detected in any month.")

    # 3. DISPLAY METRICS & GRAPH
    m1, m2, m3 = st.columns(3)
    m1.metric("U-Value", f"{u_val:.3f} W/m²K")
    m2.metric("Condensation Risk", final_risk_msg, delta_color="inverse" if "FAIL" in final_risk_msg else "normal")
    m3.metric("Project", project_name)
    
    if graph_data:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(graph_data['x'], graph_data['temp'], label="Temperature", color="blue", linewidth=2)
        ax.plot(graph_data['x'], graph_data['dew'], label="Dew Point", color="red", linestyle="--", linewidth=2)
        
        # Fill risk
        ax.fill_between(graph_data['x'], graph_data['temp'], graph_data['dew'], 
                        where=(np.array(graph_data['dew']) > np.array(graph_data['temp'])), 
                        color='red', alpha=0.3, label='Condensation Zone')
        
        ax.set_xlabel("Depth from Inside Surface (mm)")
        ax.set_ylabel("Temp (°C)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)

    # 4. PDF EXPORT
    pdf_buffer = generate_pdf(project_name, u_val, final_risk_msg, calc_layers, monthly_report)
    
    st.download_button(
        label="📄 Download Official PDF Report",
        data=pdf_buffer,
        file_name=f"{project_name}_Report.pdf",
        mime="application/pdf"
    )
