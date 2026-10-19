"""Generate fake Moonpool Bakehouse finance CSVs and PDFs (deterministic). Needs the dev group: uv sync."""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from fpdf import FPDF

random.seed(26)
ROOT = Path(__file__).resolve().parent.parent
DATA, DOCS = ROOT / "data", ROOT / "docs"
REGIONS = {"north": 1.0, "south": 0.8, "midlands": 0.9, "scotland": 0.55}
PRODUCTS = {"BSC-12": 14.40, "FROST-12": 15.84}  # wholesale price per box
MONTHS = [f"2026-{m:02d}" for m in range(1, 10)]

with open(DATA / "sales.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["month", "region", "product", "boxes", "revenue", "target_revenue"])
    for mi, m in enumerate(MONTHS):
        for r, scale in REGIONS.items():
            for p, price in PRODUCTS.items():
                if p == "FROST-12" and int(m[-2:]) not in (1, 11, 12):
                    continue
                boxes = int(random.gauss(5200 * scale, 400) * (1 + mi * 0.02) * (0.25 if p == "FROST-12" else 1))
                rev = round(boxes * price, 2)
                w.writerow([m, r, p, boxes, rev, round(rev * random.uniform(0.9, 1.1), 2)])

CUSTOMERS = ["Greenfield Grocers", "Corner & Crumb", "Harbour Deli", "Lantern Cafes", "Oakmere Stores",
             "Tidewater Co-op", "Pennine Provisions", "Nimbus Vending", "Glenfiddy Hotels", "Starling Kiosks"]
today = date(2026, 10, 19)
with open(DATA / "invoices.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["invoice_id", "customer", "region", "amount", "due_date", "status", "days_overdue"])
    for i in range(1, 41):
        due = today - timedelta(days=random.randint(-20, 80))
        paid = random.random() < 0.55
        overdue = max((today - due).days, 0)
        w.writerow([f"INV-{1000 + i}", random.choice(CUSTOMERS), random.choice(list(REGIONS)),
                    round(random.uniform(1200, 31000), 2), due, "paid" if paid else "open",
                    0 if paid else overdue])

COSTS = {"spirulina extract": 21000, "sherbet crystals": 13500, "butter & dairy": 52000,
         "packaging": 24000, "labour": 118000, "energy": 17500}
with open(DATA / "costs.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["month", "category", "amount"])
    for mi, m in enumerate(MONTHS):
        for c, base in COSTS.items():
            bump = 1.12 if (c == "spirulina extract" and mi >= 6) else 1  # supplier price rise from Jul
            w.writerow([m, c, round(base * bump * random.uniform(0.95, 1.05), 2)])


def pdf(name, title, paras):
    p = FPDF()
    p.add_page()
    p.set_auto_page_break(True, 15)
    p.set_font("Helvetica", "B", 16)
    p.multi_cell(0, 10, title)
    p.ln(2)
    p.set_font("Helvetica", "", 11)
    for t in paras:
        p.multi_cell(0, 6, t)
        p.ln(2)
    p.output(str(DOCS / name))


pdf("board-minutes-q3.pdf", "Moonpool Bakehouse - Board Minutes, Q3 FY26 (CONFIDENTIAL)", [
    "Attendees: CEO, Finance Director, Head of Production, Head of Sales.",
    "1. Trading: Q3 revenue ahead of plan in the North and Midlands; Scotland remains 15% below target due to slow onboarding of Glenfiddy Hotels. South is flat.",
    "2. Margin: Spirulina extract price rose 12% from July (AlgaeWorks). Board approved qualifying BlueBloom GmbH as a hedge but notes the hue difference.",
    "3. Capital: Approved 340,000 for a second colourimeter-equipped cooling line to reduce CLR-02 grey-green defects, which cost approx. 1.9% of output in Q3.",
    "4. Action: Finance Director to bring an Fizzwick Confectionery acquisition proposal to the November board. Strictly confidential.",
    "5. Credit control: Board asked for all accounts over 60 days overdue to be placed on credit hold.",
])
pdf("qa-audit-report-sep.pdf", "QA Audit Report - September 2026", [
    "Scope: Blue Sherbet line, batches MB-2635-A to MB-2639-B.",
    "Result: 41 batches tested, 3 quarantined. Two failed colourimeter (b* above -18) after an oven drifted to 169C on Line A. One failed the fizz test because the crystal store hygrometer read 52% RH.",
    "Corrective actions: Oven thermocouple replaced 14 Sep. Hygrometer alarm set at 45% RH. Operators retrained on the 40-second maximum fold time for sherbet crystals.",
    "Allergen: ATP swab at Green Moon (pistachio) changeover passed on all 9 changeovers. No Level 3 incidents.",
])
pdf("allergen-matrix.pdf", "Allergen Matrix - Blue Sherbet Cookie (BSC-12) and Frost Moon (FROST-12)", [
    "Contains: wheat (gluten), milk, egg, soy (in white chocolate).",
    "Does not contain: peanuts, tree nuts, sesame, sulphites. Produced on a site that also makes pistachio products; line is segregated with full clean-down between runs.",
    "Colourant: spirulina extract (phycocyanin). Suitable for vegetarians; not suitable for vegans (egg, milk).",
    "Frost Moon drizzle contains additional soy lecithin.",
])
print("done")
