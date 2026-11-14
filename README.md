# Bai Matabay Plang Avenue corridor microsimulation

Field data, a calibrated SUMO microsimulation, and a web dashboard for a study of friction-driven congestion on Bai Matabay Plang Avenue, the one-way access road between the Davao–Cotabato National Highway and the University of Southern Mindanao (USM) main gate in Kabacan, Cotabato, Philippines.

![SUMO representation of the corridor](docs/fig_sumo_network.png)

## Contents

| File | Purpose |
|---|---|
| `field_data.json` | Manual counts per 15-minute interval for the morning, midday, and evening peaks: classified entry volumes, gate arrivals, pedestrians near the gate, tricycle stops, jeepney/SUV stops, parking and side-street intrusions, tricycle dwell times, and observed flow status |
| `config.json` | Corridor geometry, friction and pedestrian parameters, simulation settings, and scenario definitions |
| `run_bmp.py` | Builds the SUMO network and demand from the field data, runs every scenario and seed, validates the baseline with the GEH statistic, and writes the results |
| `RUN_SIMULATION.bat` | One-click launcher for Windows (writes `run_log.txt`) |
| `index.html` | Interactive dashboard: field data, correlations, and SUMO scenario results |
| `tools/fill_paper.py` | Fills the simulation values in the manuscript from `results/results.json` |

## Running the model

Requirements: [Eclipse SUMO](https://eclipse.dev/sumo/) 1.15 or later (with `SUMO_HOME` set), Python 3.9+, and optionally `matplotlib` for the figures.

1. Set the measured segment lengths, lane count, and lane width in `config.json`.
2. Run `python run_bmp.py` (or double-click `RUN_SIMULATION.bat` on Windows).
3. Results are written to `results/`:
   - `validation.csv`: observed versus simulated 15-minute gate counts with GEH
   - `summary.csv`: travel time, time loss, waiting time, mid-segment speed, maximum queue, and CO₂ per scenario and peak (mean ± SD across seeds)
   - `results.json`: everything above, for the dashboard
   - `fig_validation.png`, `fig_time_loss.png`

To watch one case, run `python run_bmp.py --gui S0_baseline morning`. To generate the SUMO input files without running them, run `python run_bmp.py --dry-run`.

## How the field data drive the model

| Field observation | Model element |
|---|---|
| Classified entry counts per 15 min | Vehicles inserted on the entry link by class and interval |
| Gate count minus entry count | Additional inflow from the side street and roadside origins |
| Tricycle stoppages and mean dwell time | Tricycles stopping on the left (west) curb lane of the friction zone, dwell ~ Normal(mean, 0.3 × mean) |
| Jeepney/SUV stops | 20-s on-lane stops (assumed) |
| Parking and side-street intrusions | Roadside vehicles occupying the left (west) curb lane for 60 s (assumed) before merging |
| Pedestrians near the USM gate | Groups of five pedestrians blocking traffic for 7 s each (assumed) |

Mixed traffic uses SUMO's sublane model (lateral resolution 0.8 m), so motorcycles can filter past tricycles. Each run has a 15-minute warm-up before the 60-minute peak; results cover only vehicles departing during the peak hour. Durations not measured in the field are stated assumptions in `config.json`.

## Scenarios

| ID | Scenario |
|---|---|
| S0 | Existing conditions |
| S1 | Off-lane tricycle loading bay (30 m, 8 spaces) |
| S2 | No-parking enforcement in the mid-segment |
| S3 | Controlled pedestrian crossing at the USM gate (12-s release every 90 s) |
| S4 | S1 + S2 + S3 combined |

Total vehicular demand is identical in every scenario.

## Results

Corridor: USM Avenue, 607 m (OpenStreetMap way 4302974), one-way, 2 lanes, 40 km/h. Side friction is on the west curb, where the side streets (e.g. Matalam Street) join. Results are produced automatically by the **Run SUMO simulation** GitHub Action whenever `config.json`, `field_data.json` or `run_bmp.py` changes.

Baseline validation: 10 of 12 fifteen-minute gate counts (83%) have GEH < 5 (target ≥ 85%); the two misses are the morning intervals at 07:00 and 07:15, where the observed surge-and-drop is smoother in the model.

| Scenario | Morning time loss (s/veh) | Change | Midday time loss (s/veh) | Change | Morning CO₂ change |
|---|---|---|---|---|---|
| S0 Existing conditions | 23.3 | — | 12.8 | — | — |
| S1 Tricycle loading bay | 11.7 | -50% | 8.8 | -31% | -15% |
| S2 No-parking enforcement | 12.1 | -48% | 7.9 | -38% | -16% |
| S3 Controlled pedestrian crossing | 20.1 | -14% | 12.1 | -5% | -5% |
| S4 Combined (S1+S2+S3) | 5.8 | -75% | 6.0 | -53% | -26% |

![Observed vs simulated gate counts](results/fig_validation.png)
![Time loss by scenario](results/fig_time_loss.png)

## Field data

![Vehicle composition](docs/fig06_composition.png)
![Entry vs gate](docs/fig07_entry_gate.png)

## Dashboard

`index.html` runs in any browser with no installation. With GitHub Pages enabled (Settings → Pages → Deploy from branch → `main` / root), it is served at
`https://monteropeterdominic-arch.github.io/bmp-corridor-microsimulation/`.
On GitHub Pages the dashboard loads `results/results.json` automatically.

The **Field observations** tab opens with the 3D SUMO simulation of USM Avenue, which plays automatically.

## 3D simulation

`simulation3d.html` replays SUMO vehicle trajectories in 3D on a Mapbox map with 3D buildings: cars, motorcycles, tricycles, jeepneys and trucks move along the real corridor, and pedestrians appear at the USM gate whenever they hold up traffic. It compares existing conditions (S0) with the combined measures (S4) for the busiest 15 minutes of each peak: morning 07:00–07:15, midday 12:00–12:15 and evening 19:45–20:00.

1. Run `python run_bmp.py --replay` (or double-click `RUN_REPLAY.bat`). This writes `replay/replay_<scenario>_<period>.json` for S0 and S4 and all three peaks.
2. Add the `replay/` folder to the repository. The corridor geometry comes from `corridor.json` (USM Avenue, OpenStreetMap way 4302974).
3. Open `https://monteropeterdominic-arch.github.io/bmp-corridor-microsimulation/simulation3d.html`.

## Authors

Peter Dominic C. Montero, Keith Ternura, Lesly A. Bocado, John Paul Esparagoza, Alexa Mae Serjas, Jovan A. Prudente, Carl Jay G. Ostaga, Jeko Jann G. Heyres, Samrah Angeles, Khent Brylle L. Yson, Rachelle Anne Barbecho (BSCE, Highway & Railway Engineering), and Ebrahim A. Omar (Faculty of Civil Engineering), University of Southern Mindanao, Kabacan, Cotabato.

## License

Code is released under the MIT License (see `LICENSE`). The field data in `field_data.json` are released under CC BY 4.0. Please cite the accompanying paper (see `CITATION.cff`) when using them.
