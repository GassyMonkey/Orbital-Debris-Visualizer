# Orbital-Debris-Visualizer
An interactive 3D visualization of every tracked objects in Earth's orbit using live data from Space-Track.org. I built this because I kept reading about orbital pollution in the abstract and it felt hard to imagine. This is my attempt to make it visible.

The tool pulls live tracking data from Space-Track.org (maintained by the US Space Force) and plots every currently tracked object in Earth's orbit in 3D, including active satellites, spent rocket bodies, debris fragments from collisions and launches rotating around a sphere, color-coded by how crowded that orbital region is. 

**What it does**
- Plots all tracked orbital objects in real time using live TLE data
- Color modes: object type (debris/satellites/rockets) or orbital density (how crowded each altitude band is)
- Click any object to see its NORAD ID, altitude, inclination, orbital velocity, and eccentricity, with its full orbital path drawn
- Time simulation: watch the debris population move at up to 1000x speed, jump forward or back in one-hour increments
- Adjustable sample size for performance during simulation
- Show/hide object types to isolate what you're looking at
  
**Why I built this**
I've learned that within my life, the Milky Way may become effectively invisible from Earth's surface, not just because of ground-based light pollution, but because of the growing shell of objects in low Earth orbit reflecting sunlight. Thousands of satellites faster than the regulatory frameworks governing them can keep up.

I'm planning to study Aerospace Engineering with a focus on this problem. Building this was part to teach myself the underlying orbital mechanics, learning TLE format, SGP4 propagation, what inclination and eccentricity actually mean visually. The other part was to have something concrete to point to when I say the problem is real.

**Stack**
- Python
- Dash + Plotly for the interactive 3D visualization
- Skyfield for orbital mechanics calculations
- Space-Track.org API for live TLE data (free account required)
  
**Setup**
1. pip install requests numpy plotly dash skyfield
2. You'll need a free account at space-track.org. Add your credentials to the login section at the top of the script.
3. Then run the script: python Orbital_Debris_Visualizer.py
4. Opens automatically at http://127.0.0.1:8050.

**Notes**
This is a visualization tool and does not include an operational collision prediction system. The orbital paths and positions are calculated using SGP4 propagation from publicly available TLE data, which is accurate to within a few kilometers for most objects. For actual conjunction analysis, organizations use higher-fidelity models with more frequent data updates. The density heatmap reflects relative congestion by altitude band, not a formal risk assessment.
Data is fetched at launch and reflects orbital positions at that moment. Restart the script to refresh.
