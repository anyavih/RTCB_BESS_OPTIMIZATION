# ERCOT BESS Co-Optimization Benchmark: Actuals vs. Perfect Foresight (RTC+B)

## The Brief
This model benchmarks historical BESS operations in ERCOT against a perfect-foresight optimization model. The motivation behind this model is to anayze the new **Real-Time Co-optimization plus Batteries (RTC+B)** market design (which went live in ERCOT in December 2025) and compares the actual historical SOC to an optimized SOC where Ancillary values are included in the optimization objective generated. This will allow the user to quantify revenue leakage and evaluate operational efficiency under the new nodal realities.

## How to Run
1. Clone this repository.
2. Install the required packages: `pip install -r requirements.txt`
3. Execute the script: `python main.py`
4. Open the generated `Final_BESS_Benchmarking.html` to view the interactive Plotly dashboard.

## Methodology & Problem Statement
The goal is to co-optimize energy (SPP) and ancillary services (ECRS) for a standalone battery using 5-minute interval data. 
* **The Benchmark:** Actual historical state-of-charge data for operating ERCOT batteries.
* **The Optimization:** A linear programming model using `cvxpy` that maximizes revenue subject to physical battery constraints, trading off the opportunity cost of discharging energy versus holding capacity for ECRS.
* **The Result:** A net leakage calculation (Optimized Value - Actual Value) to identify missed market opportunities.

---

## The Optimization Problem

The core model behind this benchmark is a linear program using `cvxpy`. The model evaluates the entire time horizon (perfect foresight) to find the optimal dispatch schedule.

### Decision Variables (What we are optimizing)
For every 5-minute interval $t$ in the time horizon $T$, the solver determines the optimal values for:
* $p_{dis, t} \ge 0$: Discharge power injected into the grid (MW)
* $p_{char, t} \ge 0$: Charge power withdrawn from the grid (MW)
* $a_{ecrs, t} \ge 0$: Capacity awarded for ECRS (MW)
* $soc_t \ge 0$: The State of Charge of the battery (MWh)

### Objective Function
We want to maximize total operating profit between December 15, 2025, 12:00 AM and December 21, 2025, 12:00 AM (after RTC+B implementation). The objective balances the revenue from energy arbitrage and ECRS capacity against the cost to charge and the physical degradation cost of cycling the battery.

$$\max \sum_{t=1}^{T} \left[ \left( p_{dis, t} \cdot SPP_t + a_{ecrs, t} \cdot MCPC_t \right)\Delta t - \left(p_{char, t} \cdot SPP_t\right)\Delta t - \left(p_{char, t} + p_{dis, t}\right)\Delta t \cdot C_{deg} \right]$$

Where $SPP$ is the Settlement Point Price, $MCPC$ is the ECRS clearing price, $\Delta t$ is the interval duration in fraction of an hour (5/60), and $C_{deg}$ is the degradation penalty.

* Note: A soft constraint was used (i.e. degradation penalty) so that solver would only choose charge or discharge. If I didn't use a soft constraint, I would've had to MILP (Mixed-Integer Linear Programming) which can be a bit more tedious. 

### Subject to Physical Constraints

**1. State of Charge Transition:** SOC update accounting for round trip inefficiency. ($\eta = \sqrt{0.90}$).
$$soc_{t+1} = soc_t + \left( p_{char, t} \cdot \eta - \frac{p_{dis, t}}{\eta} \right) \Delta t$$

**2. State of Charge Longevity Bounds:** Ensuring the battery operates between 20% and 80% of its capacity to maximize longer term efficiency ($E_{cap}$).
$$0.20 \cdot E_{cap} \le soc_t \le 0.80 \cdot E_{cap}$$

**3. Inverter Power Limits:** The total power charging, or the total power discharging plus reserved ancillary capacity, cannot exceed the MW limit ($P_{max}$).
$$p_{char, t} \le P_{max}$$
$$p_{dis, t} + a_{ecrs, t} \le P_{max}$$

**4. RTC+B ECRS Feasibility:** ERCOT's new AS Capability limit. Under RTC+B rules, ECRS has transitioned to a 1-hour requirement.
$$soc_t \ge (0.20 \cdot E_{cap}) + (a_{ecrs, t} \cdot 1.0)$$

---


## RTC+B Market Evolution & Model Simplification
The RTC+B ERCOT duration requirements for Ancillary Services have changed, and the current model implements only some of these changes (for time constraint reasons). 

### Current Model Implementation
* **ECRS Duration:** This model is updated to the **1-hour requirement** (previously 2 hours), allowing 1-hour duration assets like **ADL_ESR1** to qualify for 100% of their rated power.
* **Simplified Focus:** For this benchmark prototype, the optimization engine focuses exclusively on the co-optimization of **Energy (SPP)** and **ECRS**.

### Future Enhancements: Full AS Stacking
To fully capture the complexity of the RTC+B environment, future iterations should incorporate the following checks:
* **RRS & Regulation:** Requirements reduced to **30 minutes**.
* **Non-Spinning Reserve**:4 MWh must be reserved per 1 MW awarded.
* **Simultaneous SoC Visibility:** Batteries must now maintain enough state-of-charge to sustain the full deployment of *all* awarded services simultaneously. 

Additional Simplifications Worth Noting: 

The historical revenue is missing anything the battery earned from ancillary services (like ECRS capacity payments). So the leakage is overstated. 

---

## Data Dictionary
The model ingests three primary data streams:
1. **BESS Telemetry (`ESR_[Asset].csv`):** `interval_start_utc` and `soc` (used to back-calculate historical actuals).
2. **Hub Energy Pricing (`LMP_HOU.csv`):** `lmp_with_adders` ($/MWh) functioning as the Settlement Point Price (SPP).
3. **Ancillary Service Pricing (`SCED.csv`):** `mcpc` for ECRS ($/MW).

## AI Workflow
Gemini was used to help accelerate the build:
* **Data Collection:** I told Gemini my idea, what data I wanted, and it pointed me to the appropriate locations on the ERCOT wesbite.
* **Optimization Equation:** I created the optimization problem in collaboration with Gemini. I knew what objective I wanted and what constraints, and Gemini (w/ confirmation) created the appropriate equation. 
* **Visualization:** Sped up the generation of the Plotly dashboard. Again, I told Gemini I wanted a plotly graph, what color scheme I wanted to use, and what I wanted it to look like.

All of these steps were with close collaboration with myself, looking over each step and what assumptions I wanted to build in. 
