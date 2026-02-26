# Troubleshooting za demo

Brzi vodič za rješavanje problema tokom live demo prezentacije.

---

## 1. Dashboard se ne učitava

**Simptom:** Prazan ekran ili broken layout u browseru.

**Rješenje:**
```bash
# CDN-ovi zahtijevaju internet. Pokreni lokalni server:
cd /path/to/sportek
python -m http.server 8080
# Otvori: http://localhost:8080/dashboard/index.html
```

**Fallback:** Ako nema interneta, React/Recharts se neće učitati. Koristi
screenshots iz `modules/*/results/*.png` kao backup vizuale.

---

## 2. API ne radi

**Simptom:** Connection refused ili 404 na API endpointima.

**Rješenje:**
```bash
cd /path/to/sportek
PYTHONPATH=. python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Provjera:** `curl http://localhost:8000/health`

---

## 3. Model ne učitava (FileNotFoundError)

**Simptom:** `FileNotFoundError: Model not found: .../defect_classifier.pkl`

**Rješenje:**
```bash
# CV Quality model:
cd modules/01_cv_quality && python train.py

# TradeFlow model:
cd modules/02_tradeflow && python hs_classifier.py

# Knowledge Guardian index:
cd modules/03_knowledge_guardian && python vector_store.py

# Demand Forecast model:
cd modules/04_demand_forecast && python models.py
```

---

## 4. Import error (ModuleNotFoundError)

**Simptom:** `ModuleNotFoundError: No module named 'modules'`

**Rješenje:**
```bash
# Opcija 1: PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Opcija 2: Pokretanje iz root direktorija
cd /path/to/sportek
python -m modules.01_cv_quality.inference
```

---

## 5. Grafovi nedostaju u results/

**Simptom:** Prazan `results/` folder, nema PNG/JSON fajlova.

**Rješenje:**
```bash
# Pokreni analytics za relevantni modul:
python modules/01_cv_quality/analytics.py
python modules/02_tradeflow/compliance_analytics.py
python modules/03_knowledge_guardian/analytics.py
python modules/04_demand_forecast/visualizations.py
python modules/05_oee_dashboard/visualizations.py
python modules/06_brand_reporting/analytics.py
```

---

## 6. CSV error (FileNotFoundError ili parsing error)

**Simptom:** `FileNotFoundError: data/production/production_log.csv`

**Rješenje:**
```bash
# Provjeri da CSV-ovi postoje:
ls data/production/production_log.csv
ls data/quality/defect_log.csv
ls data/supply_chain/inventory.csv
ls data/compliance/hs_classifications.csv

# Ako nedostaju, regeneriši:
python data/generate_production.py
```

---

## 7. Spor odgovor Knowledge Guardian

**Simptom:** Search traje >2 sekunde.

**Objašnjenje:** Normalno je 0.5-2s na CPU za TF-IDF search sa 247 chunks.
Nije bug — CPU-only sistem bez GPU akceleracije.

**Optimizacija:**
```bash
# Provjeri veličinu indeksa:
ls -la modules/03_knowledge_guardian/store/vector_index.pkl
# Normalna veličina: 1-5 MB
```

---

## 8. Browser CORS error

**Simptom:** `Access-Control-Allow-Origin` error u browser konzoli.

**Rješenje:**
```bash
# NIKAD ne otvaraj dashboard sa file:// protokolom!
# Koristi HTTP server:
python -m http.server 8080
# Otvori: http://localhost:8080/dashboard/index.html
```

---

## 9. Nedostaje font (Inter)

**Simptom:** Tekst izgleda drugačije, generic font umjesto Inter.

**Objašnjenje:** Google Fonts zahtijeva internet. Dashboard automatski koristi
`system-ui, -apple-system, sans-serif` kao fallback. Vizualni efekat je minimalan.

**Rješenje:** Poveži se na WiFi. Font se učitava sa `fonts.googleapis.com`.

---

## 10. Laptop se pregrijava / spor rad

**Simptom:** Ventilator radi na max, spor response.

**Rješenje:**
- Zatvori sve osim: 1 browser tab + 1 terminal
- Zatvori: Slack, Teams, VS Code, Docker
- Ako treba, pokreni demo na drugom laptopu
- Dashboard je lightweight (1 HTML fajl, no build step)

---

## Quick checklist prije demo-a

```
[ ] Internet konekcija radi (za CDN-ove i font)
[ ] python --version → 3.10+
[ ] pip install -r requirements.txt (done)
[ ] python tests/test_integration.py → 8/8 PASS
[ ] Browser otvoren na dashboard/index.html
[ ] Terminal otvoren u project root
[ ] Backup screenshots pripremljeni
[ ] Laptop napunjen / na punjač
[ ] Projektor/screen testiran
```

---

## Kontakti za hitnu pomoć

- **AI Tim:** interno
- **IT Support:** za mrežne probleme
- **Backup plan:** Ako ništa ne radi, koristiti dashboard screenshots + prezentacijske bilješke
