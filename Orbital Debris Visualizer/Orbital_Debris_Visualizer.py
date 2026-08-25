# -*- coding: utf-8 -*-
import requests
import numpy as np
import plotly.graph_objects as go
import geopandas as gpd
import sys
from skyfield.api import EarthSatellite, load
from dash import Dash, dcc, html, Output, Input, no_update, Patch, State, ctx
from shapely import contains_xy

# ============================================================
# LOGIN
# ============================================================
def masked_password_input(prompt):
    print(prompt, end='', flush=True)
    password = ''
    
    if sys.platform == 'win32':
        import msvcrt
        while True:
            ch = msvcrt.getwch()
            if ch in ('\r', '\n'):
                print()
                break
            elif ch == '\x08':  # backspace
                if password:
                    password = password[:-1]
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif ch == '\x03':  # ctrl+c
                raise KeyboardInterrupt
            else:
                password += ch
                sys.stdout.write('*')
                sys.stdout.flush()
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in ('\r', '\n'):
                    print()
                    break
                elif ch == '\x7f':  # backspace on mac/linux
                    if password:
                        password = password[:-1]
                        sys.stdout.write('\b \b')
                        sys.stdout.flush()
                elif ch == '\x03':  # ctrl+c
                    raise KeyboardInterrupt
                else:
                    password += ch
                    sys.stdout.write('*')
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    
    return password

session = requests.Session()

print("\n" + "="*50)
print("  ORBITAL DEBRIS VISUALIZER")
print("  Requires a free Space-Track.org account")
print("  Register at: https://www.space-track.org/auth/createAccount")
print("="*50 + "\n")

while True:
    email = input("Space-Track email: ")
    password = masked_password_input("Space-Track password: ")
    
    print("\nConnecting to Space-Track.org...")
    response = session.post(
        "https://www.space-track.org/ajaxauth/login",
        data={"identity": email, "password": password},
        timeout=30
    )
    
    if response.status_code == 200 and 'Failed' not in response.text:
        print("Login successful.\n")
        break
    else:
        print("Login failed. Check your credentials and try again.\n")

print("Fetching orbital data — this may take a minute...\n")

def get_objects(object_type):
    url = f"https://www.space-track.org/basicspacedata/query/class/gp/OBJECT_TYPE/{object_type}/DECAY_DATE/null-val/format/tle"
    return session.get(url, timeout=60).text

# ============================================================
# PARSE TLE WITH METADATA
# ============================================================
def parse_tle_with_meta(tle_text, obj_type):
    lines = [l for l in tle_text.strip().split('\n') if l.strip()]
    satellites = []
    for i in range(0, len(lines)-2, 3):
        try:
            name = lines[i].strip()
            line1 = lines[i+1].strip()
            line2 = lines[i+2].strip()
            satellites.append({
                'name': name,
                'line1': line1,
                'line2': line2,
                'norad_id': line1[2:7].strip(),
                'type': obj_type,
                'inclination': round(float(line2[8:16].strip()), 2),
                'eccentricity': round(float('0.' + line2[26:33].strip()), 4),
                'mean_motion': float(line2[52:63].strip())
            })
        except:
            continue
    return satellites

print("Fetching debris...")
debris_raw = parse_tle_with_meta(get_objects("DEBRIS"), "DEBRIS")
print("Fetching payloads...")
payload_raw = parse_tle_with_meta(get_objects("PAYLOAD"), "PAYLOAD")
print("Fetching rocket bodies...")
rocket_raw = parse_tle_with_meta(get_objects("ROCKET%20BODY"), "ROCKET BODY")

# ============================================================
# POSITIONS
# ============================================================
ts = load.timescale()

def get_positions_filtered(satellites):
    t = ts.now()
    positions, valid_sats = [], []
    for sat_data in satellites:
        try:
            sat = EarthSatellite(sat_data['line1'], sat_data['line2'], sat_data['name'], ts)
            pos = sat.at(t).position.km
            r = np.sqrt(sum(p**2 for p in pos))
            if 6371 < r < 50000:
                positions.append(list(pos))
                valid_sats.append(sat_data)
        except:
            continue
    if len(positions) == 0:
        return np.zeros((0, 3)), valid_sats
    return np.array(positions), valid_sats

print("Calculating positions...")
debris_pos, debris_sats = get_positions_filtered(debris_raw)
payload_pos, payload_sats = get_positions_filtered(payload_raw)
rocket_pos, rocket_sats = get_positions_filtered(rocket_raw)

arrays = [a for a in [debris_pos, payload_pos, rocket_pos] if len(a) > 0]
all_positions = np.vstack(arrays) if arrays else np.zeros((0, 3))
all_sats = debris_sats + payload_sats + rocket_sats

# Pre-create satellite objects for animation
print("Pre-creating satellite objects for animation...")
def create_sat_objects(sats):
    objs = []
    for s in sats:
        try:
            objs.append(EarthSatellite(s['line1'], s['line2'], s['name'], ts))
        except:
            objs.append(None)
    return objs

debris_sat_objs = create_sat_objects(debris_sats)
payload_sat_objs = create_sat_objects(payload_sats)
rocket_sat_objs = create_sat_objects(rocket_sats)

# Sample for animation performance (2000 total)
def make_sample(n_total, n_sample):
    n = min(n_total, n_sample)
    return sorted(np.random.choice(n_total, n, replace=False).tolist())

total_sats = len(debris_sats) + len(payload_sats) + len(rocket_sats)
debris_anim_idx = make_sample(len(debris_sats), round(2000 * len(debris_sats) / total_sats))
payload_anim_idx = make_sample(len(payload_sats), round(2000 * len(payload_sats) / total_sats))
rocket_anim_idx = make_sample(len(rocket_sats), round(2000 * len(rocket_sats) / total_sats))
DEFAULT_DEBRIS_ANIM_IDX = list(debris_anim_idx)
DEFAULT_PAYLOAD_ANIM_IDX = list(payload_anim_idx)
DEFAULT_ROCKET_ANIM_IDX = list(rocket_anim_idx)

# ============================================================
# DENSITY COLORS
# ============================================================
def calculate_density_colors(positions_list):
    valid = [p for p in positions_list if len(p) > 0]
    if not valid:
        def get_colors(positions):
            return ['#4488ff'] * len(positions)
        return get_colors

    all_pos = np.vstack(valid)
    altitudes_all = np.sqrt(np.sum(all_pos**2, axis=1)) - 6371
    bin_size = 50
    bins = np.arange(0, 50000, bin_size)
    counts, _ = np.histogram(altitudes_all, bins=bins)

    def get_colors(positions):
        if len(positions) == 0:
            return []
        altitudes = np.sqrt(np.sum(positions**2, axis=1)) - 6371
        bin_indices = np.clip((altitudes / bin_size).astype(int), 0, len(counts)-1)
        density = counts[bin_indices]
        p25 = np.percentile(density, 25)
        p50 = np.percentile(density, 50)
        p75 = np.percentile(density, 75)
        colors = []
        for d in density:
            if d < p25:
                colors.append('#4488ff')
            elif d < p50:
                colors.append('#ffff44')
            elif d < p75:
                colors.append('#ff8800')
            else:
                colors.append('#ff2222')
        return colors

    return get_colors

get_colors = calculate_density_colors([debris_pos, payload_pos, rocket_pos])
debris_colors = get_colors(debris_pos)
payload_colors = get_colors(payload_pos)
rocket_colors = get_colors(rocket_pos)
debris_original = ['#ff4444'] * len(debris_pos)
payload_original = ['#44aaff'] * len(payload_pos)
rocket_original = ['#ffaa44'] * len(rocket_pos)

# Pre-compute sampled color arrays for animation mode
debris_density_anim = [debris_colors[i] for i in debris_anim_idx]
payload_density_anim = [payload_colors[i] for i in payload_anim_idx]
rocket_density_anim = [rocket_colors[i] for i in rocket_anim_idx]
debris_original_anim = ['#ff4444'] * len(debris_anim_idx)
payload_original_anim = ['#44aaff'] * len(payload_anim_idx)
rocket_original_anim = ['#ffaa44'] * len(rocket_anim_idx)

# Sampled customdata for animation mode
debris_anim_customdata = [[i] for i in debris_anim_idx]
payload_anim_customdata = [[i + len(debris_sats)] for i in payload_anim_idx]
rocket_anim_customdata = [[i + len(debris_sats) + len(payload_sats)] for i in rocket_anim_idx]

# Record simulation start time
sim_start_jd = ts.now().tt

def get_positions_at_jd(sat_objs, indices, jd):
    t = ts.tt_jd(jd)
    xs, ys, zs = [], [], []
    for i in indices:
        if i >= len(sat_objs) or sat_objs[i] is None:
            xs.append(float('nan'))
            ys.append(float('nan'))
            zs.append(float('nan'))
            continue
        try:
            pos = sat_objs[i].at(t).position.km
            r = float(np.sqrt(sum(p**2 for p in pos)))
            if 6371 < r < 50000:
                xs.append(float(pos[0]))
                ys.append(float(pos[1]))
                zs.append(float(pos[2]))
            else:
                xs.append(float('nan'))
                ys.append(float('nan'))
                zs.append(float('nan'))
        except:
            xs.append(float('nan'))
            ys.append(float('nan'))
            zs.append(float('nan'))
    return xs, ys, zs

print(f"Debris: {len(debris_pos)}, Payloads: {len(payload_pos)}, Rockets: {len(rocket_pos)}")
total_available = len(debris_sats) + len(payload_sats) + len(rocket_sats)

# ============================================================
# HELPERS
# ============================================================
def calculate_params(pos, sat_data):
    GM = 398600.4418
    r = np.sqrt(np.sum(np.array(pos)**2))
    altitude = round(r - 6371)
    velocity = round(np.sqrt(GM / r), 2)
    orbit = "LEO" if altitude < 2000 else "MEO" if altitude < 35786 else "GEO" if altitude < 36000 else "HEO"
    return altitude, velocity, orbit

def get_orbital_path(sat_data):
    try:
        sat = EarthSatellite(sat_data['line1'], sat_data['line2'], sat_data['name'], ts)
        period_days = 1 / sat_data['mean_motion']
        t_now = ts.now()
        times = ts.tt_jd([t_now.tt + period_days * i/100 for i in range(101)])
        return np.array(sat.at(times).position.km)
    except:
        return None

def apply_camera(fig_patch, camera):
    if camera:
        fig_patch['layout']['scene']['camera'] = camera

def reset_anim_indices_to_default():
    global debris_anim_idx, payload_anim_idx, rocket_anim_idx
    global debris_density_anim, payload_density_anim, rocket_density_anim
    global debris_original_anim, payload_original_anim, rocket_original_anim
    global debris_anim_customdata, payload_anim_customdata, rocket_anim_customdata

    debris_anim_idx = list(range(len(debris_sats)))
    payload_anim_idx = list(range(len(payload_sats)))
    rocket_anim_idx = list(range(len(rocket_sats)))
    debris_density_anim = list(debris_colors)
    payload_density_anim = list(payload_colors)
    rocket_density_anim = list(rocket_colors)
    debris_original_anim = list(debris_original)
    payload_original_anim = list(payload_original)
    rocket_original_anim = list(rocket_original)
    debris_anim_customdata = [[i] for i in range(len(debris_sats))]
    payload_anim_customdata = [[i + len(debris_sats)] for i in range(len(payload_sats))]
    rocket_anim_customdata = [[i + len(debris_sats) + len(payload_sats)] for i in range(len(rocket_sats))]

def set_anim_indices_to_2000():
    global debris_anim_idx, payload_anim_idx, rocket_anim_idx
    global debris_density_anim, payload_density_anim, rocket_density_anim
    global debris_original_anim, payload_original_anim, rocket_original_anim
    global debris_anim_customdata, payload_anim_customdata, rocket_anim_customdata
    total_sats = len(debris_sats) + len(payload_sats) + len(rocket_sats)
    debris_anim_idx = list(DEFAULT_DEBRIS_ANIM_IDX)
    payload_anim_idx = list(DEFAULT_PAYLOAD_ANIM_IDX)
    rocket_anim_idx = list(DEFAULT_ROCKET_ANIM_IDX)
    debris_density_anim = [debris_colors[i] for i in debris_anim_idx]
    payload_density_anim = [payload_colors[i] for i in payload_anim_idx]
    rocket_density_anim = [rocket_colors[i] for i in rocket_anim_idx]
    debris_original_anim = ['#ff4444'] * len(debris_anim_idx)
    payload_original_anim = ['#44aaff'] * len(payload_anim_idx)
    rocket_original_anim = ['#ffaa44'] * len(rocket_anim_idx)
    debris_anim_customdata = [[i] for i in debris_anim_idx]
    payload_anim_customdata = [[i + len(debris_sats)] for i in payload_anim_idx]
    rocket_anim_customdata = [[i + len(debris_sats) + len(payload_sats)] for i in rocket_anim_idx]

# ============================================================
# BASE FIGURE
# ============================================================
def build_base_figure():
    N = 100
    u = np.linspace(0, 2*np.pi, N)
    v = np.linspace(0, np.pi, N)
    er = 6371
    x_e = er * np.outer(np.sin(v), np.cos(u))
    y_e = er * np.outer(np.sin(v), np.sin(u))
    z_e = er * np.outer(np.cos(v), np.ones(N))

    fig = go.Figure()

    # Earth numbers

    # Get longitude / latitude from your EXISTING sphere
    # This is important: we derive lon/lat from x_e/y_e/z_e
    # rather than assuming how your sphere was generated.
    r = np.sqrt(x_e**2 + y_e**2 + z_e**2) 
    lat = np.degrees(np.arcsin(np.clip(z_e / r, -1, 1)))
    lon = np.degrees(np.arctan2(y_e, x_e))

    # Load real Natural Earth land polygons
    world = gpd.read_file(
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
        "geojson/ne_110m_land.geojson"
    )

    # Combine all land polygons into one geometry
    land_geometry = world.geometry.union_all()

    # CREATE LAND MASK
    # This is fast because Shapely processes the entire NumPy
    # array at once instead of creating 10,000 Point objects.
    land_mask = contains_xy(
        land_geometry,
        lon,
        lat
    )

    # Create surface colors
    surface_color = np.full_like(
        z_e,
        0.05,
        dtype=float
    )

    # Land
    surface_color[land_mask] = 0.60

    # Polar ice
    ice_mask = np.abs(lat) > 72
    surface_color[ice_mask] = 0.95

    # Earth (trace 0)
    fig.add_trace(go.Surface(
        x=x_e,
        y=y_e,
        z=z_e,

        surfacecolor=surface_color,

        colorscale=[
            # Ocean
            [0.00, '#062f4a'],
            [0.15, '#084c70'],
            [0.30, '#0e628c'],
            [0.49, '#176f96'],

            # Land
            [0.50, '#356b36'],
            [0.60, '#4f8240'],
            [0.70, '#668c45'],
            [0.80, '#8b7a4d'],
            [0.90, '#a49362'],

            # Ice
            [0.94, '#c8ccc7'],
            [1.00, '#e3e6e3']
        ],

        cmin=0,
        cmax=1,

        showscale=False,
        opacity=1,

        # Don't show hover information
        hoverinfo='skip',
        hovertemplate=None,
        name='Earth',

        # disable contour/grid lines
        contours=dict(
            x=dict(show=False),
            y=dict(show=False),
            z=dict(show=False)
        ),

        lighting=dict(
            ambient=0.8,
            diffuse=0.3,
            specular=0.0,
            roughness=1.0
        ),

        lightposition=dict(
            x=100,
            y=100,
            z=150
        )
    ))

    # Stars (trace 1)
    n_stars = 2000
    sr = 150000
    su = np.random.uniform(0, 2*np.pi, n_stars)
    sv = np.random.uniform(0, np.pi, n_stars)
    fig.add_trace(go.Scatter3d(
        x=sr*np.sin(sv)*np.cos(su),
        y=sr*np.sin(sv)*np.sin(su),
        z=sr*np.cos(sv),
        mode='markers',
        marker=dict(size=0.5, color='white', opacity=0.45),
        name='Stars', hoverinfo='skip'
    ))

    # Debris (trace 2)
    fig.add_trace(go.Scatter3d(
        x=debris_pos[:,0] if len(debris_pos) > 0 else [],
        y=debris_pos[:,1] if len(debris_pos) > 0 else [],
        z=debris_pos[:,2] if len(debris_pos) > 0 else [],
        mode='markers',
        marker=dict(size=1.5, color=debris_original, opacity=0.7),
        name=f'Debris ({len(debris_pos):,})',
        customdata=[[i] for i in range(len(debris_sats))],
        hovertemplate='Debris<extra></extra>'
    ))

    # Payloads (trace 3)
    offset_p = len(debris_sats)
    fig.add_trace(go.Scatter3d(
        x=payload_pos[:,0] if len(payload_pos) > 0 else [],
        y=payload_pos[:,1] if len(payload_pos) > 0 else [],
        z=payload_pos[:,2] if len(payload_pos) > 0 else [],
        mode='markers',
        marker=dict(size=2, color=payload_original, opacity=0.7),
        name=f'Active Satellites ({len(payload_pos):,})',
        customdata=[[i + offset_p] for i in range(len(payload_sats))],
        hovertemplate='Active Satellite<extra></extra>'
    ))

    # Rocket bodies (trace 4)
    offset_r = len(debris_sats) + len(payload_sats)
    fig.add_trace(go.Scatter3d(
        x=rocket_pos[:,0] if len(rocket_pos) > 0 else [],
        y=rocket_pos[:,1] if len(rocket_pos) > 0 else [],
        z=rocket_pos[:,2] if len(rocket_pos) > 0 else [],
        mode='markers',
        marker=dict(size=1.7, color=rocket_original, opacity=0.7),
        name=f'Rocket Bodies ({len(rocket_pos):,})',
        customdata=[[i + offset_r] for i in range(len(rocket_sats))],
        hovertemplate='Rocket Body<extra></extra>'
    ))

    # Orbital rings (traces 5, 6, 7)
    theta = np.linspace(0, 2*np.pi, 300)
    orbit_rings = {
        'LEO Reference': (
            6371 + 2000,
            '#ffffff',
            '<b>LEO — Low Earth Orbit</b><br>'
            'Altitude: ~2,000 km'
        ),
        'MEO Reference': (
            6371 + 20000,
            '#aaaaff',
            '<b>MEO — Medium Earth Orbit</b><br>'
            'Reference altitude: 20,000 km'
        ),
        'GEO Reference': (
            6371 + 35786,
            '#ffff44',
            '<b>GEO — Geostationary Orbit</b><br>'
            'Altitude: 35,786 km'
        )
    }

    for name, (r, color, hover_text) in orbit_rings.items():
        fig.add_trace(go.Scatter3d(
            x=r*np.cos(theta), y=r*np.sin(theta), z=np.zeros(300),
            mode='lines', line=dict(color=color, width=1.5),
            name=name, opacity=0.6, hovertemplate=hover_text + '<extra></extra>'
        ))

    # Orbital path placeholder (trace 8)
    fig.add_trace(go.Scatter3d(
        x=[], y=[], z=[],
        mode='lines',
        line=dict(color='#ffffff', width=2),
        name='Orbital Path',
        hoverinfo='skip', showlegend=False
    ))

    # Selected highlight placeholder (trace 9)
    fig.add_trace(go.Scatter3d(
        x=[], y=[], z=[],
        mode='markers',
        marker=dict(size=6, color='#ffffff', opacity=1.0),
        name='Selected',
        hoverinfo='skip', showlegend=False
    ))

    fig.update_layout(
        hovermode='closest',
        clickmode='event+select',
        title=dict(
            text='Earth Orbital Debris Visualization',
            font=dict(color='white', size=18), x=0.5
        ),
        scene=dict(
            xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, showbackground=False, showspikes=False, title=''),
            yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, showbackground=False, showspikes=False, title=''),
            zaxis=dict(showticklabels=False, showgrid=False, zeroline=False, showbackground=False, showspikes=False, title=''),
            bgcolor='black',
            aspectmode='data'
        ),
        paper_bgcolor='black', font_color='white',
        legend=dict(
            bgcolor='rgba(0,0,0,0.5)',
            bordercolor='rgba(255,255,255,0.2)',
            borderwidth=1,
            itemclick=False,
            itemdoubleclick=False,
            itemsizing='constant',
            tracegroupgap=4
        )
    )
    return fig

base_fig = build_base_figure()
for i, trace in enumerate(base_fig.data):
    print(f"Trace {i}: {trace.name}")

ORBITAL_PATH_IDX = 8
SELECTED_IDX = 9

# ============================================================
# DASH APP
# ============================================================
app = Dash(__name__)

PANEL_BASE_STYLE = {
    'position': 'fixed', 'top': '20px', 'left': '20px',
    'background': 'rgba(0,0,0,0.85)',
    'border': '1px solid rgba(255,255,255,0.3)',
    'borderRadius': '8px', 'padding': '20px',
    'color': 'white', 'fontFamily': 'monospace',
    'fontSize': '13px', 'minWidth': '280px', 'zIndex': '1000'
}

btn_style = {
    'background': 'rgba(255,255,255,0.1)',
    'color': 'white',
    'border': '1px solid rgba(255,255,255,0.3)',
    'borderRadius': '4px',
    'padding': '6px 14px',
    'cursor': 'pointer',
    'fontFamily': 'monospace',
    'fontSize': '15px',
    'margin': '0 4px'
}
spd_style = {**btn_style, 'fontSize': '12px', 'padding': '6px 10px'}

app.layout = html.Div([
    dcc.Store(id='sim-state', data={
        'jd_offset': 0.0,
        'playing': False,
        'speed': 60
    }),
    dcc.Store(id='selected-sat', data=None),
    dcc.Store(id='color-mode', data='original'),
    dcc.Store(id='camera-store', data=None),
    dcc.Store(id='vis-debris', data=True),
    dcc.Store(id='vis-satellites', data=True),
    dcc.Store(id='vis-rockets', data=True),
    dcc.Store(id='sample-size', data=total_available),
    dcc.Store(id='reset-flag', data=False),
    dcc.Store(id='is-reset', data=False),
    dcc.Interval(id='sim-interval', interval=500, disabled=True),
    dcc.Graph(
        id='orbit-graph',
        figure=base_fig,
        style={'height': '100vh'},
        config={
            'scrollZoom': True,
            'displaylogo': False,
        }
    ),
    html.Div(
        id='subtitle-display',
        children=
            'Every dot represents a tracked object — color indicates type: 🔴 Debris; 🔵 Active Satellites; 🟠 Rocket Bodies',
        style={
            'position': 'fixed',
            'top': '60px',
            'width': '100%',
            'textAlign': 'center',
            'color': 'rgba(255,255,255,0.6)',
            'fontFamily': 'monospace',
            'fontSize': '12px',
            'pointerEvents': 'none',
            'zIndex': '999'
        }
    ),
    html.Div(id='info-panel', style={**PANEL_BASE_STYLE, 'display': 'none'}),
    # HUD
    html.Div([
        html.Div([
            html.Button(
                'Switch to Density Colors',
                id='color-toggle',
                n_clicks=0,
                style={
                    'background': 'rgba(0,0,0,0.7)',
                    'color': 'white',
                    'border': '1px solid rgba(255,255,255,0.3)',
                    'borderRadius': '6px',
                    'padding': '4px 12px',
                    'cursor': 'pointer',
                    'fontFamily': 'monospace',
                    'fontSize': '11px',
                }
            )
        ], style={'textAlign': 'center', 'marginBottom': '6px'}),
        html.Div(
            id='live-status',
            children=f'Showing {total_available:,} — {len(debris_sats):,} debris | {len(payload_sats):,} satellites | {len(rocket_sats):,} rockets',
            style={
                'color': '#aaddff',
                'fontFamily': 'monospace',
                'fontSize': '12px',
                'textAlign': 'center',
                'marginBottom': '4px'
            }
        ),
        html.Div(
            id='time-display',
            children='Loading time...',
            style={
                'color': '#aaddff',
                'fontFamily': 'monospace',
                'fontSize': '13px',
                'textAlign': 'center',
                'marginBottom': '8px'
            }
        ),
        html.Div([
            # Visibility group
            html.Span('Show/Hide:', style={'color': 'rgba(255,255,255,0.4)', 'fontFamily': 'monospace', 'fontSize': '11px', 'marginRight': '6px'}),
            html.Button('Debris', id='btn-debris', n_clicks=0, style={**spd_style, 'color': '#ff4444'}),
            html.Button('Satellites', id='btn-satellites', n_clicks=0, style={**spd_style, 'color': '#44aaff'}),
            html.Button('Rockets', id='btn-rockets', n_clicks=0, style={**spd_style, 'color': '#ffaa44'}),

            html.Span('|', style={'color': 'rgba(255,255,255,0.3)', 'margin': '0 14px'}),

            # Playback group
            html.Button('◀◀', id='btn-backward', n_clicks=0, style=btn_style),
            html.Button('▶', id='btn-play', n_clicks=0, style=btn_style),
            html.Button('▶▶', id='btn-forward', n_clicks=0, style=btn_style),
            html.Button('Reset to Live', id='btn-reset', n_clicks=0, style={**btn_style, 'color': '#ffaa44'}),

            html.Span('|', style={'color': 'rgba(255,255,255,0.3)', 'margin': '0 14px'}),

            # Speed group
            html.Button('1x',    id='btn-1x',    n_clicks=0, style=spd_style),
            html.Button('60x',   id='btn-60x',   n_clicks=0, style=spd_style),
            html.Button('300x',  id='btn-300x',  n_clicks=0, style=spd_style),
            html.Button('1000x', id='btn-1000x', n_clicks=0, style=spd_style),
            html.Span('|', style={'color': 'rgba(255,255,255,0.3)', 'margin': '0 14px'}),
            html.Span('Sim sample size:', style={'color': 'rgba(255,255,255,0.4)', 'fontFamily': 'monospace', 'fontSize': '11px', 'marginRight': '6px'}),
            dcc.Input(
                id='sample-input',
                type='number',
                placeholder=2000,
                min=100,
                debounce=True,
                persistence=False,
                style={
                    'width': '80px',
                    'background': 'rgba(255,255,255,0.1)',
                    'border': '1px solid rgba(255,255,255,0.3)',
                    'borderRadius': '4px',
                    'color': 'white',
                    'fontFamily': 'monospace',
                    'fontSize': '12px',
                    'padding': '4px 8px',
                    'textAlign': 'center'
                }
            ),
            html.Div(id='sample-range-display', 
                children=f'100 ~ {total_available:,}',
                style={
                'color': 'rgba(255,255,255,0.3)',
                'fontFamily': 'monospace',
                'fontSize': '10px',
                'marginLeft': '6px'
            }),
        ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center'})
    ], style={
        'position': 'fixed',
        'bottom': '0', 'left': '0', 'right': '0',
        'background': 'rgba(0,0,0,0.85)',
        'borderTop': '1px solid rgba(255,255,255,0.2)',
        'padding': '12px 20px',
        'zIndex': '1000'
    })
], style={'background': 'black', 'margin': '0', 'padding': '0'})
# ============================================================
# CALLBACK: TOGGLE VISIBILITY
# ============================================================
@app.callback(
    [Output('orbit-graph', 'figure', allow_duplicate=True),
     Output('btn-debris', 'style'),
     Output('btn-satellites', 'style'),
     Output('btn-rockets', 'style'),
     Output('vis-debris', 'data'),
     Output('vis-satellites', 'data'),
     Output('vis-rockets', 'data'),
     Output('live-status', 'children', allow_duplicate=True)],
    [Input('btn-debris',     'n_clicks'),
     Input('btn-satellites', 'n_clicks'),
     Input('btn-rockets',    'n_clicks')],
    [State('vis-debris',    'data'),
     State('vis-satellites','data'),
     State('vis-rockets',   'data'),
     State('camera-store',  'data')],
    prevent_initial_call=True
)
def toggle_visibility(d_clicks, s_clicks, r_clicks, vis_d, vis_s, vis_r, camera):
    triggered = ctx.triggered_id

    if triggered == 'btn-debris':
        vis_d = not vis_d
    elif triggered == 'btn-satellites':
        vis_s = not vis_s
    elif triggered == 'btn-rockets':
        vis_r = not vis_r

    def btn_style(color, visible):
        return {
            **spd_style,
            'color': color,
            'opacity': '1' if visible else '0.3',
            'textDecoration': 'none' if visible else 'line-through'
        }

    fig_patch = Patch()
    apply_camera(fig_patch, camera)
    fig_patch['data'][2]['visible'] = True if vis_d else 'legendonly'
    fig_patch['data'][3]['visible'] = True if vis_s else 'legendonly'
    fig_patch['data'][4]['visible'] = True if vis_r else 'legendonly'

    parts = []
    if vis_d:
        parts.append(f'{len(debris_anim_idx):,} debris')
    if vis_s:
        parts.append(f'{len(payload_anim_idx):,} satellites')
    if vis_r:
        parts.append(f'{len(rocket_anim_idx):,} rockets')
    total = sum([len(debris_anim_idx) if vis_d else 0,
                 len(payload_anim_idx) if vis_s else 0,
                 len(rocket_anim_idx) if vis_r else 0])
    live_status = f'Showing {total:,} — {" | ".join(parts)}'

    return (
        fig_patch,
        btn_style('#ff4444', vis_d),
        btn_style('#44aaff', vis_s),
        btn_style('#ffaa44', vis_r),
        vis_d, vis_s, vis_r,
        live_status
    )
# ============================================================
# CALLBACK: MOVE CAMERA
# ============================================================
@app.callback(
    Output('camera-store', 'data'),
    Input('orbit-graph', 'relayoutData'),
    prevent_initial_call=True
)
def store_camera(relayoutData):
    if relayoutData and 'scene.camera' in relayoutData:
        return relayoutData['scene.camera']
    return no_update
# ============================================================
# CALLBACK: CLICK OBJECT
# ============================================================
@app.callback(
    [Output('info-panel', 'children'),
     Output('info-panel', 'style'),
     Output('orbit-graph', 'figure', allow_duplicate=True),
     Output('selected-sat', 'data')],
    Input('orbit-graph', 'clickData'),
    [State('sim-state', 'data'),
     State('camera-store', 'data')],
    prevent_initial_call=True
)
def show_info(clickData, sim_state, camera):
    if not clickData:
        return no_update, no_update, no_update, no_update

    point = clickData['points'][0]
    if 'customdata' not in point:
        return no_update, no_update, no_update, no_update

    obj_idx = point['customdata'][0]
    sat_data = all_sats[obj_idx]

    current_jd = sim_start_jd + sim_state.get('jd_offset', 0)
    try:
        sat_obj = EarthSatellite(sat_data['line1'], sat_data['line2'], sat_data['name'], ts)
        t = ts.tt_jd(current_jd)
        pos = sat_obj.at(t).position.km
    except:
        pos = all_positions[obj_idx]

    altitude, velocity, orbit = calculate_params(pos, sat_data)

    panel_content = html.Div([
        html.Div("OBJECT DETAILS", style={'color': '#44aaff', 'fontWeight': 'bold', 'marginBottom': '8px'}),
        html.Hr(style={'borderColor': 'rgba(255,255,255,0.2)', 'margin': '8px 0'}),
        html.Table([
            html.Tr([html.Td("NORAD ID",     style={'color':'#aaa','paddingRight':'20px','paddingBottom':'4px'}), html.Td(sat_data['norad_id'])]),
            html.Tr([html.Td("TYPE",         style={'color':'#aaa','paddingBottom':'4px'}), html.Td(sat_data['type'])]),
            html.Tr([html.Td("NAME",         style={'color':'#aaa','paddingBottom':'4px'}), html.Td(sat_data['name'][:30])]),
            html.Tr([html.Td("ALTITUDE",     style={'color':'#aaa','paddingBottom':'4px'}), html.Td(f"{altitude:,} km")]),
            html.Tr([html.Td("INCLINATION",  style={'color':'#aaa','paddingBottom':'4px'}), html.Td(f"{sat_data['inclination']} deg")]),
            html.Tr([html.Td("VELOCITY",     style={'color':'#aaa','paddingBottom':'4px'}), html.Td(f"{velocity} km/s")]),
            html.Tr([html.Td("ECCENTRICITY", style={'color':'#aaa','paddingBottom':'4px'}), html.Td(str(sat_data['eccentricity']))]),
            html.Tr([html.Td("ORBIT",        style={'color':'#aaa','paddingBottom':'4px'}), html.Td(orbit)]),
        ], style={'borderCollapse': 'collapse', 'width': '100%'}),
        html.Hr(style={'borderColor': 'rgba(255,255,255,0.2)', 'margin': '8px 0'}),
        html.Div([html.Span("● ", style={'color': '#44ff44'}), html.Span("TRACKED")])
    ])

    fig_patch = Patch()
    apply_camera(fig_patch, camera)
    path = get_orbital_path(sat_data)
    if path is not None:
        valid = np.sqrt(np.sum(path**2, axis=0)) > 6371
        fig_patch['data'][ORBITAL_PATH_IDX]['x'] = path[0][valid].tolist()
        fig_patch['data'][ORBITAL_PATH_IDX]['y'] = path[1][valid].tolist()
        fig_patch['data'][ORBITAL_PATH_IDX]['z'] = path[2][valid].tolist()
    else:
        fig_patch['data'][ORBITAL_PATH_IDX]['x'] = []
        fig_patch['data'][ORBITAL_PATH_IDX]['y'] = []
        fig_patch['data'][ORBITAL_PATH_IDX]['z'] = []

    fig_patch['data'][SELECTED_IDX]['x'] = [float(pos[0])]
    fig_patch['data'][SELECTED_IDX]['y'] = [float(pos[1])]
    fig_patch['data'][SELECTED_IDX]['z'] = [float(pos[2])]

    return panel_content, {**PANEL_BASE_STYLE, 'display': 'block'}, fig_patch, obj_idx
# ============================================================
# CALLBACK: TOGGLE COLORS
# ============================================================
@app.callback(
    [Output('orbit-graph', 'figure', allow_duplicate=True),
     Output('color-toggle', 'children'),
     Output('color-mode', 'data', allow_duplicate=True),
     Output('subtitle-display', 'children')],
    Input('color-toggle', 'n_clicks'),
    [State('sim-state', 'data'),
     State('color-mode', 'data'),
     State('camera-store', 'data')],
    prevent_initial_call=True
)
def toggle_colors(n_clicks, sim_state, current_mode, camera):
    if not n_clicks or not isinstance(n_clicks, int):
        return no_update, no_update, no_update

    fig_patch = Patch()
    apply_camera(fig_patch, camera)
    in_anim = sim_state.get('playing', False) or sim_state.get('jd_offset', 0) != 0

    if n_clicks % 2 == 1:
        # Switch to density colors
        if in_anim:
            fig_patch['data'][2]['marker']['color'] = debris_density_anim
            fig_patch['data'][3]['marker']['color'] = payload_density_anim
            fig_patch['data'][4]['marker']['color'] = rocket_density_anim
        else:
            fig_patch['data'][2]['marker']['color'] = debris_colors
            fig_patch['data'][3]['marker']['color'] = payload_colors
            fig_patch['data'][4]['marker']['color'] = rocket_colors
        return fig_patch, 'Switch to Colored by Object Type', 'density', 'Every dot represents a tracked object, grouped into 50 km altitude bands — color indicates orbital density: 🔵 Low → 🟡 Moderate → 🟠 High → 🔴 Peak'
    else:
        # Switch to original colors
        if in_anim:
            fig_patch['data'][2]['marker']['color'] = debris_original_anim
            fig_patch['data'][3]['marker']['color'] = payload_original_anim
            fig_patch['data'][4]['marker']['color'] = rocket_original_anim
        else:
            fig_patch['data'][2]['marker']['color'] = debris_original
            fig_patch['data'][3]['marker']['color'] = payload_original
            fig_patch['data'][4]['marker']['color'] = rocket_original
        return fig_patch, 'Switch to Colored by Orbital Density', 'original', 'Every dot represents a tracked object — color indicates type: 🔴 Debris; 🔵 Active Satellites; 🟠 Rocket Bodies'
# ============================================================
# CALLBACK: SIMULATION CONTROLS
# ============================================================
@app.callback(
    [Output('sim-state', 'data'),
     Output('sim-interval', 'disabled'),
     Output('btn-play', 'children'),
     Output('live-status', 'children', allow_duplicate=True)],
    [Input('btn-play',    'n_clicks'),
     Input('btn-1x',     'n_clicks'),
     Input('btn-60x',    'n_clicks'),
     Input('btn-300x',   'n_clicks'),
     Input('btn-1000x',  'n_clicks')],
    State('sim-state', 'data'),
    prevent_initial_call=True
)
def control_simulation(play_clicks, s1, s60, s300, s1000, state):
    triggered = ctx.triggered_id
    new_state = state.copy()

    if triggered == 'btn-play':
        new_state['playing'] = not state['playing']
    elif triggered == 'btn-1x':
        new_state['speed'] = 1
    elif triggered == 'btn-60x':
        new_state['speed'] = 60
    elif triggered == 'btn-300x':
        new_state['speed'] = 300
    elif triggered == 'btn-1000x':
        new_state['speed'] = 1000

    playing = new_state['playing']
    parts = []
    if len(debris_anim_idx) > 0:
        parts.append(f'{len(debris_anim_idx):,} debris')
    if len(payload_anim_idx) > 0:
        parts.append(f'{len(payload_anim_idx):,} satellites')
    if len(rocket_anim_idx) > 0:
        parts.append(f'{len(rocket_anim_idx):,} rockets')
    total_showing = len(debris_anim_idx) + len(payload_anim_idx) + len(rocket_anim_idx)
    live_status = f'Showing {total_showing:,} — {" | ".join(parts)}'

    return new_state, not playing, ('⏸' if playing else '▶'), live_status

# ============================================================
# CALLBACK: UPDATE SIMULATION
# ============================================================
@app.callback(
    [Output('orbit-graph', 'figure', allow_duplicate=True),
     Output('sim-state', 'data', allow_duplicate=True),
     Output('time-display', 'children'),
     Output('btn-play', 'children', allow_duplicate=True),
     Output('color-mode', 'data', allow_duplicate=True),
     Output('color-toggle', 'children', allow_duplicate=True),
     Output('sample-input', 'value', allow_duplicate=True),
     Output('live-status', 'children'),
     Output('is-reset', 'data', allow_duplicate=True)],
    [Input('sim-interval',  'n_intervals'),
     Input('btn-backward',  'n_clicks'),
     Input('btn-forward',   'n_clicks'),
     Input('btn-reset',     'n_clicks')],
    [State('sim-state',    'data'),
     State('color-mode',   'data'),
     State('selected-sat', 'data'),
     State('camera-store', 'data'),
     State('sample-input', 'value')],
    prevent_initial_call=True
)
def update_simulation(n_intervals, back_clicks, fwd_clicks, reset_clicks, state, color_mode, selected_idx, camera, sample_val):
    triggered = ctx.triggered_id
    new_state = state.copy()

    if triggered == 'btn-reset':
        new_state['jd_offset'] = 0.0
        new_state['playing'] = False
        current_jd = sim_start_jd

        # Reset globals to 2000 for next simulation
        reset_anim_indices_to_default()

        # But show ALL objects in live view using full arrays
        full_debris_customdata = [[i] for i in range(len(debris_sats))]
        full_payload_customdata = [[i + len(debris_sats)] for i in range(len(payload_sats))]
        full_rocket_customdata = [[i + len(debris_sats) + len(payload_sats)] for i in range(len(rocket_sats))]

        fig_patch = Patch()
        apply_camera(fig_patch, camera)
        fig_patch['data'][2]['x'] = debris_pos[:,0].tolist()
        fig_patch['data'][2]['y'] = debris_pos[:,1].tolist()
        fig_patch['data'][2]['z'] = debris_pos[:,2].tolist()
        fig_patch['data'][2]['marker']['color'] = debris_original
        fig_patch['data'][2]['customdata'] = full_debris_customdata
        fig_patch['data'][3]['x'] = payload_pos[:,0].tolist()
        fig_patch['data'][3]['y'] = payload_pos[:,1].tolist()
        fig_patch['data'][3]['z'] = payload_pos[:,2].tolist()
        fig_patch['data'][3]['marker']['color'] = payload_original
        fig_patch['data'][3]['customdata'] = full_payload_customdata
        fig_patch['data'][4]['x'] = rocket_pos[:,0].tolist()
        fig_patch['data'][4]['y'] = rocket_pos[:,1].tolist()
        fig_patch['data'][4]['z'] = rocket_pos[:,2].tolist()
        fig_patch['data'][4]['marker']['color'] = rocket_original
        fig_patch['data'][4]['customdata'] = full_rocket_customdata

        t = ts.tt_jd(current_jd)
        utc_str = t.utc_datetime().strftime('%Y-%m-%d %H:%M:%S UTC')
        total = len(debris_sats) + len(payload_sats) + len(rocket_sats)
        live_status = f'Showing all {total:,} — {len(debris_sats):,} debris | {len(payload_sats):,} satellites | {len(rocket_sats):,} rockets'
        return fig_patch, new_state, f'⏱  {utc_str}   |   Live Data restored', '▶', 'original', 'Switch to Colored by Orbital Density', None, live_status, True

    elif triggered == 'btn-backward':
        if sample_val is None:
            set_anim_indices_to_2000()
        new_state['jd_offset'] -= 3600 / 86400
        current_jd = sim_start_jd + new_state['jd_offset']

    elif triggered == 'btn-forward':
        if sample_val is None:
            set_anim_indices_to_2000()
        new_state['jd_offset'] += 3600 / 86400
        current_jd = sim_start_jd + new_state['jd_offset']

    elif triggered == 'sim-interval':
        if not state['playing'] or not n_intervals or camera is None:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update
        if sample_val is None:
            set_anim_indices_to_2000()
        dt_days = (state['speed'] * 0.5) / 86400.0
        new_state['jd_offset'] += dt_days
        current_jd = sim_start_jd + new_state['jd_offset']

    else:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

    current_jd = sim_start_jd + new_state['jd_offset']

    dx, dy, dz = get_positions_at_jd(debris_sat_objs, debris_anim_idx, current_jd)
    px, py, pz = get_positions_at_jd(payload_sat_objs, payload_anim_idx, current_jd)
    rx, ry, rz = get_positions_at_jd(rocket_sat_objs, rocket_anim_idx, current_jd)

    if color_mode == 'density':
        dc, pc, rc = debris_density_anim, payload_density_anim, rocket_density_anim
    else:
        dc, pc, rc = debris_original_anim, payload_original_anim, rocket_original_anim

    fig_patch = Patch()
    apply_camera(fig_patch, camera)
    fig_patch['data'][2]['x'] = dx
    fig_patch['data'][2]['y'] = dy
    fig_patch['data'][2]['z'] = dz
    fig_patch['data'][2]['marker']['color'] = dc
    fig_patch['data'][2]['customdata'] = debris_anim_customdata
    fig_patch['data'][3]['x'] = px
    fig_patch['data'][3]['y'] = py
    fig_patch['data'][3]['z'] = pz
    fig_patch['data'][3]['marker']['color'] = pc
    fig_patch['data'][3]['customdata'] = payload_anim_customdata
    fig_patch['data'][4]['x'] = rx
    fig_patch['data'][4]['y'] = ry
    fig_patch['data'][4]['z'] = rz
    fig_patch['data'][4]['marker']['color'] = rc
    fig_patch['data'][4]['customdata'] = rocket_anim_customdata

    if selected_idx is not None:
        sat_data = all_sats[selected_idx]
        try:
            sat_obj = EarthSatellite(sat_data['line1'], sat_data['line2'], sat_data['name'], ts)
            t_sel = ts.tt_jd(current_jd)
            sel_pos = sat_obj.at(t_sel).position.km
            fig_patch['data'][SELECTED_IDX]['x'] = [float(sel_pos[0])]
            fig_patch['data'][SELECTED_IDX]['y'] = [float(sel_pos[1])]
            fig_patch['data'][SELECTED_IDX]['z'] = [float(sel_pos[2])]
        except:
            pass

    t = ts.tt_jd(current_jd)
    utc_str = t.utc_datetime().strftime('%Y-%m-%d %H:%M:%S UTC')

    showing_all = (len(debris_anim_idx) == len(debris_sats) and
                   len(payload_anim_idx) == len(payload_sats) and
                   len(rocket_anim_idx) == len(rocket_sats))
    active_count = len(debris_anim_idx) + len(payload_anim_idx) + len(rocket_anim_idx)
    object_str = f'Showing all {active_count:,}' if showing_all else f'Showing {active_count:,} sampled'
    time_display = f'⏱  {utc_str}   |   Speed: {new_state["speed"]}x   |   {object_str}'

    parts = []
    if len(debris_anim_idx) > 0:
        parts.append(f'{len(debris_anim_idx):,} debris')
    if len(payload_anim_idx) > 0:
        parts.append(f'{len(payload_anim_idx):,} satellites')
    if len(rocket_anim_idx) > 0:
        parts.append(f'{len(rocket_anim_idx):,} rockets')
    live_status = f'Showing {active_count:,} — {" | ".join(parts)}'

    return fig_patch, new_state, time_display, no_update, no_update, no_update, no_update, live_status, False
# ============================================================
# CALLBACK: UPDATING SAMPLE SIZE
# ============================================================
@app.callback(
    [Output('orbit-graph', 'figure', allow_duplicate=True),
     Output('sample-range-display', 'children'),
     Output('sample-input', 'placeholder'),
     Output('sample-input', 'style', allow_duplicate=True),
     Output('sample-input', 'value', allow_duplicate=True),
     Output('live-status', 'children', allow_duplicate=True),
     Output('reset-flag', 'data', allow_duplicate=True)],
    [Input('sample-input', 'value'),
     Input('vis-debris', 'data'),
     Input('vis-satellites', 'data'),
     Input('vis-rockets', 'data')],
    [State('sim-state', 'data'),
     State('color-mode', 'data'),
     State('camera-store', 'data'),
     State('is-reset', 'data')],
    prevent_initial_call=True
)
def update_sample(sample_val, vis_d, vis_s, vis_r, sim_state, color_mode, camera, is_reset):
    triggered = ctx.triggered_id
    
    avail_d = len(debris_sats) if vis_d else 0
    avail_s = len(payload_sats) if vis_s else 0
    avail_r = len(rocket_sats) if vis_r else 0
    total_avail = avail_d + avail_s + avail_r

    DEFAULT_SAMPLE = 2000

    if sample_val is None and is_reset:
        n = total_avail        # after reset → show all
    elif sample_val is None:
        n = DEFAULT_SAMPLE     # on load → show 2000
    elif triggered in ['vis-debris', 'vis-satellites', 'vis-rockets']:
        n = min(int(sample_val), total_avail)
    elif sample_val < 100 or sample_val > total_avail:
        n = DEFAULT_SAMPLE
    else:
        n = int(sample_val)

    invalid = sample_val and (sample_val < 100 or sample_val > total_avail)
    input_style = {
        'width': '80px',
        'background': 'rgba(255,255,255,0.1)',
        'border': f'1px solid {"#ff4444" if invalid else "rgba(255,255,255,0.3)"}',
        'borderRadius': '4px',
        'color': '#ff4444' if invalid else 'white',
        'fontFamily': 'monospace',
        'fontSize': '12px',
        'padding': '4px 8px',
        'textAlign': 'center'
    }

    # Split proportionally across visible types
    if total_avail == 0:
        return no_update, f'100 ~ {total_available:,}', total_available, no_update, no_update, no_update, False

    def proportional(avail, total, n):
        return min(avail, round(n * avail / total)) if total > 0 else 0

    n_d = proportional(avail_d, total_avail, n)
    n_s = proportional(avail_s, total_avail, n)
    n_r = proportional(avail_r, total_avail, n)

    # Regenerate indices
    new_debris_idx = make_sample(len(debris_sats), n_d) if vis_d else []
    new_payload_idx = make_sample(len(payload_sats), n_s) if vis_s else []
    new_rocket_idx = make_sample(len(rocket_sats), n_r) if vis_r else []

    # Get current positions
    current_jd = sim_start_jd + sim_state.get('jd_offset', 0)

    dx, dy, dz = get_positions_at_jd(debris_sat_objs, new_debris_idx, current_jd) if new_debris_idx else ([], [], [])
    px, py, pz = get_positions_at_jd(payload_sat_objs, new_payload_idx, current_jd) if new_payload_idx else ([], [], [])
    rx, ry, rz = get_positions_at_jd(rocket_sat_objs, new_rocket_idx, current_jd) if new_rocket_idx else ([], [], [])

    # Colors
    if color_mode == 'density':
        dc = [debris_colors[i] for i in new_debris_idx]
        pc = [payload_colors[i] for i in new_payload_idx]
        rc = [rocket_colors[i] for i in new_rocket_idx]
    else:
        dc = ['#ff4444'] * len(new_debris_idx)
        pc = ['#44aaff'] * len(new_payload_idx)
        rc = ['#ffaa44'] * len(new_rocket_idx)

    # Customdata
    d_custom = [[i] for i in new_debris_idx]
    p_custom = [[i + len(debris_sats)] for i in new_payload_idx]
    r_custom = [[i + len(debris_sats) + len(payload_sats)] for i in new_rocket_idx]

    fig_patch = Patch()
    apply_camera(fig_patch, camera)
    fig_patch['data'][2]['x'] = dx
    fig_patch['data'][2]['y'] = dy
    fig_patch['data'][2]['z'] = dz
    fig_patch['data'][2]['marker']['color'] = dc
    fig_patch['data'][2]['customdata'] = d_custom

    fig_patch['data'][3]['x'] = px
    fig_patch['data'][3]['y'] = py
    fig_patch['data'][3]['z'] = pz
    fig_patch['data'][3]['marker']['color'] = pc
    fig_patch['data'][3]['customdata'] = p_custom

    fig_patch['data'][4]['x'] = rx
    fig_patch['data'][4]['y'] = ry
    fig_patch['data'][4]['z'] = rz
    fig_patch['data'][4]['marker']['color'] = rc
    fig_patch['data'][4]['customdata'] = r_custom

    # Update global anim indices for subsequent ticks
    global debris_anim_idx, payload_anim_idx, rocket_anim_idx
    global debris_density_anim, payload_density_anim, rocket_density_anim
    global debris_original_anim, payload_original_anim, rocket_original_anim
    global debris_anim_customdata, payload_anim_customdata, rocket_anim_customdata

    debris_anim_idx = new_debris_idx
    payload_anim_idx = new_payload_idx
    rocket_anim_idx = new_rocket_idx
    debris_density_anim = dc if color_mode == 'density' else [debris_colors[i] for i in new_debris_idx]
    payload_density_anim = pc if color_mode == 'density' else [payload_colors[i] for i in new_payload_idx]
    rocket_density_anim = rc if color_mode == 'density' else [rocket_colors[i] for i in new_rocket_idx]
    debris_original_anim = ['#ff4444'] * len(new_debris_idx)
    payload_original_anim = ['#44aaff'] * len(new_payload_idx)
    rocket_original_anim = ['#ffaa44'] * len(new_rocket_idx)
    debris_anim_customdata = d_custom
    payload_anim_customdata = p_custom
    rocket_anim_customdata = r_custom

    range_text = f'100 ~ {total_avail:,}'
    if not sample_val:
        clamped = no_update
    elif sample_val < 100:
        clamped = 100
    elif sample_val > total_avail:
        clamped = total_avail
    else:
        clamped = sample_val
    d_count = len(new_debris_idx)
    s_count = len(new_payload_idx)
    r_count = len(new_rocket_idx)
    total_count = d_count + s_count + r_count

    parts = []
    if len(new_debris_idx) > 0:
        parts.append(f'{len(new_debris_idx):,} debris')
    if len(new_payload_idx) > 0:
        parts.append(f'{len(new_payload_idx):,} satellites')
    if len(new_rocket_idx) > 0:
        parts.append(f'{len(new_rocket_idx):,} rockets')
    total_showing = len(new_debris_idx) + len(new_payload_idx) + len(new_rocket_idx)
    live_status = f'Showing {total_showing:,} — {" | ".join(parts)}'

    return fig_patch, range_text, total_avail, input_style, clamped, live_status, False
# ============================================================
# CALLBACK: UPDATING STYLE
# ============================================================
@app.callback(
    Output('sample-input', 'style'),
    Input('sample-input', 'value'),
    State('vis-debris', 'data'),
    State('vis-satellites', 'data'),
    State('vis-rockets', 'data'),
    prevent_initial_call=True
)
def validate_input_style(val, vis_d, vis_s, vis_r):
    avail_d = len(debris_sats) if vis_d else 0
    avail_s = len(payload_sats) if vis_s else 0
    avail_r = len(rocket_sats) if vis_r else 0
    total_avail = avail_d + avail_s + avail_r

    invalid = val is not None and val != '' and (int(val) < 100 or int(val) > total_avail)
    return {
        'width': '80px',
        'background': 'rgba(255,255,255,0.1)',
        'border': f'1px solid {"#ff4444" if invalid else "rgba(255,255,255,0.3)"}',
        'borderRadius': '4px',
        'color': '#ff4444' if invalid else 'white',
        'fontFamily': 'monospace',
        'fontSize': '12px',
        'padding': '4px 8px',
        'textAlign': 'center'
    }

# opens up the web automatically
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

if __name__ == '__main__':
    import webbrowser
    webbrowser.open('http://127.0.0.1:8050')
    app.run(debug=False, use_reloader=False)