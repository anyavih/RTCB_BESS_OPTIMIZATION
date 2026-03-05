import pandas as pd
import cvxpy as cp 
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os

#Color palette 
COLOR_SPP = "#5D6D7E"      
COLOR_OPT_LINE = "#2E86C1"   
COLOR_ACT_FILL = "rgba(231, 76, 60, 0.12)" 
COLOR_ACT_LINE ="#E74C3C"   
COLOR_GRID = "#F4F6F7"

def solve_lifecycle_rtcb(env_df, mw_cap, mwh_cap):
    T, dt = len(env_df), 5/60
    rte, deg_cost = 0.90, 20.0
    eff_side = np.sqrt(rte)
    
    #Set variables 
    p_char = cp.Variable(T, nonneg=True)
    p_dis = cp.Variable(T, nonneg=True)
    soc = cp.Variable(T + 1, nonneg=True)
    a_ecrs = cp.Variable(T, nonneg=True)
    
    #20-80% Longevity Bounds
    soc_min, soc_max = 0.20 * mwh_cap, 0.80 * mwh_cap
    
    #Vectorized Constraints
    constraints = [
        soc[0] == 0.5 * mwh_cap, 
        soc[T] == 0.5 * mwh_cap,
        soc >= soc_min, 
        soc <= soc_max,
        p_char <= mw_cap, 
        p_dis + a_ecrs <= mw_cap,
        # ERCOT ECRS physical energy requirement 
        soc[:-1] >= soc_min + (a_ecrs * 1.0),
        # Vectorized SOC transition
        soc[1:] == soc[:-1] + (p_char * eff_side - p_dis / eff_side) * dt]
    
    # Objective Function (Using SPP data)
    revenue = cp.sum(cp.multiply(p_dis, env_df['lmp_with_adders'].values) + 
                     cp.multiply(a_ecrs, env_df['ECRS'].values)) * dt
    
    charging_cost = cp.sum(cp.multiply(p_char, env_df['lmp_with_adders'].values)) * dt
    degr_penalty = cp.sum(p_char + p_dis) * dt * deg_cost
    
    prob = cp.Problem(cp.Maximize(revenue - charging_cost - degr_penalty), constraints)
    prob.solve()
    
    return soc.value[:-1], prob.value

DATA_PATH = "./data/"

# Batteries to consider 
FLEET_DB = {
    'ADL_ESR1':    {'mw': 60,  'mwh': 60,  'hub': 'Houston', 'file': f"{DATA_PATH}ESR_ADL_ESR1.csv"},
    'GAMBIT_ESR1': {'mw': 100, 'mwh': 175, 'hub': 'Houston', 'file': f"{DATA_PATH}ESR_GAMBIT_ESR1.csv"}}

print("Loading and preparing market data...")
df_as = pd.read_csv(f"{DATA_PATH}SCED.csv")
df_as['interval_start_utc'] = pd.to_datetime(df_as['interval_start_utc'], utc=True)
df_as_p = df_as.pivot(index='interval_start_utc', columns='as_type', values='mcpc').fillna(0)

def get_env(path, as_p):
    df = pd.read_csv(path)
    df['interval_start_utc'] = pd.to_datetime(df['interval_start_utc'], utc=True)
    return df.set_index('interval_start_utc').join(as_p, how='inner').sort_index()

# Only loading Houston SPP data
env_hou = get_env(f"{DATA_PATH}LMP_HOU.csv", df_as_p)

results = {}
for name, spec in FLEET_DB.items():
    print(f"Analyzing {name}...")
    # Directly assign the Houston environment
    env = env_hou 
    
    soc_opt, prof_opt = solve_lifecycle_rtcb(env, spec['mw'], spec['mwh'])
    
    actuals = pd.read_csv(spec['file'])
    actuals['interval_start_utc'] = pd.to_datetime(actuals['interval_start_utc'], utc=True)
    df_p = env.copy().join(actuals.set_index('interval_start_utc')['soc'], how='inner').ffill()
    
    # Historical Profit Backcalc 
    dt, eff_side = 5/60, np.sqrt(0.90)
    soc_diff = np.diff(df_p['soc'].values, prepend=df_p['soc'].values[0])
    
    p_actual_net = np.where(soc_diff > 0, -soc_diff / eff_side, -soc_diff * eff_side) / dt
    prof_act = np.sum(p_actual_net * df_p['lmp_with_adders'].values) * dt

    results[name] = {'opt': soc_opt, 'prof_opt': prof_opt, 'prof_act': prof_act, 'df_p': df_p, 'spec': spec}

print("Generating Plotly Dashboard...")
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                    subplot_titles=("SETTLEMENT POINT PRICES ($/MWh)", "STATE OF CHARGE: ACTUAL BLOCKS VS OPTIMIZED LINE"))

buttons = []
for i, (name, data) in enumerate(results.items()):
    is_v = (i == 0)
    leakage = data['prof_opt'] - data['prof_act']
    mw, mwh = data['spec']['mw'], data['spec']['mwh']
    
    # Add Traces
    fig.add_trace(go.Scatter(x=data['df_p'].index, y=data['df_p']['lmp_with_adders'], name="SPP", line=dict(color=COLOR_SPP), visible=is_v), row=1, col=1)
    fig.add_trace(go.Scatter(x=data['df_p'].index, y=data['df_p']['soc'], name="Actual (OG Method)", line=dict(color=COLOR_ACT_LINE, shape='hv'), fill='tozeroy', fillcolor=COLOR_ACT_FILL, visible=is_v), row=2, col=1)
    fig.add_trace(go.Scatter(x=data['df_p'].index, y=data['opt'], name="Optimized (Perfect Foresight)", line=dict(color=COLOR_OPT_LINE, width=3), visible=is_v), row=2, col=1)

    vis = [False] * (len(results) * 3)
    for j in range(3): vis[i*3 + j] = True
    
    # Calculate Dynamic Y-Axis Scale with 10% Padding
    max_val = max(data['df_p']['soc'].max(), np.max(data['opt']))
    min_val = min(data['df_p']['soc'].min(), np.min(data['opt']))
    
    # Create padding, ensuring we don't divide by zero if values are flat
    padding = (max_val - min_val) * 0.1 if (max_val - min_val) > 0 else (mwh * 0.1)
    
    # Ensure the minimum axis floor doesn't drop significantly below 0 for SOC
    y2_range = [max(0, min_val - padding), max_val + padding]
    
    header = (f"<b>{name} ANALYSIS</b> | System: {mw}MW / {mwh}MWh<br>"
              f"<span style='font-size: 13px; color: #666;'>"
              f"Actual Value: ${data['prof_act']:,.0f}  |  "
              f"Optimized Value: ${data['prof_opt']:,.0f}  |  "
              f"<b>Net Leakage: ${leakage:,.0f}</b></span>")

    buttons.append(dict(
        label=name, method="update", 
        args=[{"visible": vis}, {"title.text": header, "yaxis2.range": y2_range}]))

fig.update_layout(
    template="plotly_white", height=850, margin=dict(t=150, b=50, l=150, r=50),
    title=dict(x=0.02, y=0.94, font=dict(family="Arial", size=18)),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    updatemenus=[dict(active=0, buttons=buttons, x=-0.16, y=1, xanchor="left", yanchor="top", bgcolor="#FDFDFD")])

fig.update_xaxes(showgrid=True, gridcolor=COLOR_GRID, zeroline=False)
fig.update_yaxes(showgrid=True, gridcolor=COLOR_GRID, zeroline=False)

output_file = "Final_BESS_Benchmarking.html"
fig.write_html(output_file)
print(f"Analysis complete. Dashboard saved to {output_file}")
