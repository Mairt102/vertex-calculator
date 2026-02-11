import streamlit as st
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt

# --- CONFIGURATION ---
st.set_page_config(page_title="Vertex Roofing Calculator", layout="wide")

# --- 1. LOAD DATABASE ---
@st.cache_data
def load_data():
    # Reads the CSV file from your repository
    df = pd.read_csv("materials.csv")
    return df

try:
    df_materials = load_data()
except:
    st.error("Error: materials.csv not found. Please upload it to the repository.")
    st.stop()

# --- 2. PHYSICS ENGINE (GLASER METHOD) ---
def calculate_u_value(layers):
    r_total = 0.10 + 0.04 # Standard Rsi + Rse
    for layer in layers:
        thick_m = layer['thickness'] / 1000
        cond = layer['lambda']
        if cond > 0:
            r_total += thick_m / cond
    return 1 / r_total if r_total > 0 else 0

def calculate_dewpoint(vp):
    if vp <= 0: return -50
    return (237.7 * math.log(vp/610.5)) / (17.27 - math.log(vp/610.5))

def run_condensation_analysis(layers, t_in, rh_in, t_out, rh_out):
    # Saturation Pressures
    psat_in = 610.5 * math.exp((17.27 * t_in) / (237.7 + t_in))
    pv_in = psat_in * (rh_in / 100)
    
    psat_out = 610.5 * math.exp((17.27 * t_out) / (237.7 + t_out))
    pv_out = psat_out * (rh_out / 100)
    
    # Calculate Total R and Rv
    total_r = 0.14
    total_rv = 0
    
    # Pre-process layers to get totals
    processed = []
    for layer in layers:
        thick_m = layer['thickness'] / 1000
        r = thick_m / layer['lambda'] if layer['lambda'] > 0 else 0
        
        # Determine Vapour Resistance (Rv)
        # If specific R_Vap is given (MNs/g), convert to equivalent air layer for calculation ratio
        # Simplified: We treat everything as relative resistance units for the pressure drop
        if not np.isnan(layer['r_vap']): 
            rv = layer['r_vap'] # Use direct value from CSV
        else:
            rv = layer['mu'] * thick_m * 5 # Approx conversion if only Mu is known
            
        total_r += r
        total_rv += rv
        processed.append({'r': r, 'rv': rv, 'thick': layer['thickness'], 'name': layer['name']})

    # Walk through the wall
    points = {'x': [0], 'temp': [t_in], 'dew': [calculate_dewpoint(pv_in)]}
    curr = {'temp': t_in, 'pv': pv_in, 'x': 0}
    risk = False
    
    # Surface Resistance In
    dt = (t_in - t_out) * (0.10 / total_r)
    curr['temp'] -= dt
    points['x'].append(0)
    points['temp'].append(curr['temp'])
    points['dew'].append(calculate_dewpoint(curr['pv']))

    for p in processed:
        # Drops across material
        dt = (t_in - t_out) * (p['r'] / total_r)
        dp = (pv_in - pv_out) * (p['rv'] / total_rv) if total_rv > 0 else 0
        
        curr['temp'] -= dt
        curr['pv'] -= dp
        curr['x'] += p['thick']
        
        dp_temp = calculate_dewpoint(curr['pv'])
        
        points['x'].append(curr['x'])
        points['temp'].append(curr['temp'])
        points['dew'].append(dp_temp)
        
        if dp_temp >= curr['temp']:
            risk = True
            
    return points, risk, 1/total_r

# --- 3. SIDEBAR CONTROLS ---
st.sidebar.image("logo.jpg", use_container_width=True) # Replace with your URL
st.sidebar.header("Project Settings")
project_name = st.sidebar.text_input("Project Name", "Daisy Lodge")

st.sidebar.subheader("Environment (Winter)")
t_in = st.sidebar.number_input("Inside Temp (°C)", value=20.0)
rh_in = st.sidebar.number_input("Inside RH (%)", value=66.2)
t_out = st.sidebar.number_input("Outside Temp (°C)", value=-2.2)
rh_out = st.sidebar.number_input("Outside RH (%)", value=92.0)

# --- 4. MAIN INTERFACE ---
# Create two columns: Logo on the left, Title on the right
col_header1, col_header2 = st.columns([1, 4])

with col_header1:
    st.image("logo.jpg", width=150) # You can adjust '150' to make it bigger/smaller

with col_header2:
    st.title("Vertex Roofing Systems")
    st.markdown("**Thermal Calculation & Condensation Risk Analysis**")

# Session State for Layers... (rest of code continues as normal)

# Session State for Layers
if 'layers' not in st.session_state:
    st.session_state.layers = [
        {'name': 'CLT Panel', 'thick': 160},
        {'name': 'Siga Wetguard', 'thick': 1},
        {'name': 'Kingspan TR26', 'thick': 30}
    ]

def add_layer(): st.session_state.layers.append({'name': 'Warmdex Insulation', 'thick': 100})
def remove_layer(): 
    if len(st.session_state.layers) > 0: st.session_state.layers.pop()

col_btn1, col_btn2 = st.columns([1, 5])
col_btn1.button("➕ Add Layer", on_click=add_layer)
col_btn2.button("➖ Remove Layer", on_click=remove_layer)

st.write("---")

# Build the Layer Inputs dynamically
calc_layers = []
for i, layer in enumerate(st.session_state.layers):
    c1, c2 = st.columns([3, 1])
    with c1:
        # Find index of current material in CSV
        try:
            default_idx = df_materials[df_materials['Name'] == layer['name']].index[0]
        except:
            default_idx = 0
            
        new_name = st.selectbox(f"Layer {i+1} Material", df_materials['Name'], index=int(default_idx), key=f"mat_{i}")
    with c2:
        new_thick = st.number_input(f"Thickness (mm)", value=int(layer['thick']), key=f"th_{i}")
    
    # Get properties
    props = df_materials[df_materials['Name'] == new_name].iloc[0]
    calc_layers.append({
        'name': new_name,
        'thickness': new_thick,
        'lambda': props['Lambda'],
        'mu': props['Mu'],
        'r_vap': props['R_Vap']
    })

st.write("---")

# --- 5. RESULTS & GRAPH ---
if st.button("RUN CALCULATIONS", type="primary", use_container_width=True):
    points, risk, u_val = run_condensation_analysis(calc_layers, t_in, rh_in, t_out, rh_out)
    
    # Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("U-Value", f"{u_val:.3f} W/m²K")
    m2.metric("Condensation Risk", "HIGH" if risk else "NONE", delta_color="inverse" if risk else "normal")
    m3.metric("Project", project_name)
    
    # Plot
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(points['x'], points['temp'], label="Temperature", color="blue", linewidth=2)
    ax.plot(points['x'], points['dew'], label="Dew Point", color="red", linestyle="--", linewidth=2)
    
    if risk:
        ax.fill_between(points['x'], points['temp'], points['dew'], 
                        where=(np.array(points['dew']) > np.array(points['temp'])), 
                        color='red', alpha=0.3, label='Condensation Zone')
        
    ax.set_xlabel("Construction Depth (mm)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title(f"Thermal Profile: {project_name}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    st.pyplot(fig)