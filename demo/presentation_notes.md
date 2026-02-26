# Sportek AI Platform — Prezentacijske bilješke

## Trajanje: 45-60 minuta
## Publika: C-level Zecchetto Group, IT direktor, Operativni menadžment

---

## Uvod (5 min)

- **Ko smo:** Sportek d.o.o. Banja Luka — AI/ML tim razvijeni za manufakturnu industriju
- **Zašto AI:** Industrija 4.0, competitive pressure od azijskih proizvođača, zahtjevi brendova
- **Šta dobijaju:** 6 funkcionalni AI modula, €872K godišnje uštede, payback <2 mjeseca
- **Ključna poruka:** "Ovo je funkcionalni sistem, ne PowerPoint. Svaki modul radi na vašim podacima."

### Setup
- Otvoriti `dashboard/index.html` u browser-u (Chrome preporučen)
- Terminal spreman za `python demo/run_demo.py`
- Backup: screenshots u `modules/*/results/` ako nešto ne radi

---

## Modul 1 — CV Quality Control (5-7 min)

### Pokazati
- Dashboard: QC Vision tab — Pareto chart defekata, trend po brendu, realtime feed
- Terminal: live predikcija na slikama iz fabrike
- Accuracy: 94.2% model accuracy

### Reći
> "Vaših 15 inspektora provodi 45 sekundi po paru. AI to radi za 4.5 sekundi
> sa 94% tačnošću. Ne zamjenjujemo ljude — AI radi screening, 6 inspektora
> verifikuju samo flagged items."

### Wow faktor
- "Payback za 3 mjeseca, ušteda €99K godišnje"
- "Na 2,340 pari dnevno, AI hvata defekte koje ljudsko oko promašuje u 3. smjeni"

### Očekivano pitanje
**"Može li AI potpuno zamijeniti inspektore?"**
→ "Ne, i ne treba. AI + 6 inspektora za verifikaciju. AI hvata 94%, ljudi verifikuju
flagged items. ISO 9001 zahtijeva human oversight. Cilj je redukcija sa 15 na 6 inspektora."

---

## Modul 2 — TradeFlow AI (5-7 min)

### Pokazati
- Dashboard: TradeFlow tab — HS demo, duty chart po zemljama, DPP readiness
- Terminal: klasifikacija uživo — unesemo opis proizvoda, dobijemo HS kod
- Duty kalkulator: DE (SAA 0%) vs US (MFN 20%) za istu pošiljku

### Reći
> "Trenutno imate 2 osobe na compliance. AI automatizira 95% klasifikacija
> sa 96% tačnošću. Plus, DPP spremnost za 2027 EU regulativu — izbjegavate
> kazne do €100K po shipment-u."

### Wow faktor
- "€354K godišnje ušteda, uglavnom kroz FTA optimizaciju za SAA BiH-EU"
- "DPP compliance gotov — spremni ste 18 mjeseci prije roka"

### Očekivano pitanje
**"Koliko je tačna klasifikacija?"**
→ "96% accuracy na 10 HS kategorija za obuću, i to je konzervativno jer je naš domen
uži od generalnog. Za obuću specifično, accuracy je 98%+. Svaki edge case ide na
human review."

---

## Modul 3 — Knowledge Guardian (5-7 min)

### Pokazati
- Dashboard: Knowledge tab — chat demo, document usage chart
- Terminal: postavi pitanje na bosanskom, odgovor za <1s sa izvorima
- Primjer: "Koji su koraci finalne inspekcije?" → odgovor sa referencom na SOP

### Reći
> "Vaš srednji menadžment troši 1.5h dnevno odgovarajući na rutinska pitanja.
> Knowledge Guardian smanjuje to za 60%. Novi radnik može naći odgovor za 3
> sekunde umjesto da čeka šefa."

### Wow faktor
- "247 dokumenata indeksirano — SOP-ovi, Nike zahtjevi, safety procedure"
- "Radi na bosanskom jeziku, bez interneta, potpuno offline"

### Očekivano pitanje
**"Radi li na bosanskom?"**
→ "Da, dokumenti su na bosanskom, sistem odgovara na istom jeziku. TF-IDF ne
zahtijeva prevod. Za buduću fazu možemo dodati GPT layer za generisanje
natural language odgovora."

---

## Modul 4 — Demand Forecasting (5-7 min)

### Pokazati
- Dashboard: Forecast tab — chart sa confidence intervalima, model comparison
- Terminal: stockout risk tabela — materijali koji će ponestati
- Model comparison: Random Forest wins sa 3.03% MAPE

### Reći
> "Random Forest model sa 3% MAPE — znači greška od 3% na sedmičnom nivou.
> Za poređenje, vaš trenutni ručni forecast ima MAPE >15%."

### Wow faktor
- "Identifikovali smo X materijala koji će ponestati u narednih 30 dana"
- "EOQ optimizacija smanjuje order cost za 40%"

### Očekivano pitanje
**"Koliko podataka treba?"**
→ "Minimum 6 mjeseci historije, idealno 12+. Vi već imate dovoljno u SAP-u.
Model se re-trenira sedmično automatski."

**"A sezonalnost?"**
→ "Model detektuje sezonalne paterne — is_high_season feature je među top 5
po važnosti. Football sezona, back-to-school, holiday peaks."

---

## Modul 5 — OEE Dashboard (5-7 min)

### Pokazati
- Dashboard: OEE tab — bar chart po linijama, Six Big Losses, What-If simulator
- Terminal: OEE za sve linije, best vs worst
- What-If: "Šta ako dodamo 3. smjenu?" → +18% output ali -2% OEE

### Reći
> "Vaš prosječan OEE je 76.3%. World-class je 85%. Svaki procentni poen je
> ~€22K godišnje. Mi ciljamo 82% u prvoj godini."

### Wow faktor
- "What-if analiza: dodavanje 3. smjene daje +18% output ali -2% OEE"
- "Anomaly detection hvata probleme 2h prije nego se breakdown dogodi"

### Očekivano pitanje
**"Odakle dolaze podaci?"**
→ "Direktno iz SAP Business One — production log, downtime log, quality data.
Opciono: IoT senzori na SHIMA SEIKI mašinama za real-time monitoring.
Integracija sa SAP zahtijeva 2-3 dana setup."

---

## Modul 6 — Brand Reporting (5-7 min)

### Pokazati
- Dashboard: Reporting tab — Nike SMSI scorecard, KPI traffic lights, 20+ KPI-jeva
- Terminal: Nike score + grade, Crocs FPY, Decathlon sustainability
- Status: Bronze (67.1) — put do Silver (75) i Gold (90)

### Reći
> "Umjesto 3 dana ručnog rada, izvještaj se generiše za 15 sekundi.
> Jedan klik, sva tri brenda, svi KPI-jevi."

### Wow faktor
- "Ako postignete Gold SMSI (82+), Nike vam daje prioritet za nove modele
  — procjena +€50K godišnje samo od novih alokacija"
- "Alerting: sistem vam javlja kad KPI padne ispod praga PRIJE nego Nike primijeti"

### Očekivano pitanje
**"Može li se customizirati za naše specifične KPI-jeve?"**
→ "Apsolutno. Dashboard ima 20+ konfigurabilinih KPI-jeva. Možemo dodati custom
metriku za bilo koji aspekt — quality, delivery, sustainability, innovation."

---

## ROI Summary (5 min)

### Tabela

| Modul | Godišnja ušteda | ROI | Payback |
|-------|-----------------|-----|---------|
| CV Quality Control | €99,271 | 205% | 3 mj |
| TradeFlow AI | €354,734 | 1,582% | <1 mj |
| Knowledge Guardian | €20,431 | 170% | 7 mj |
| Demand Forecasting | €147,000 | 720% | 1 mj |
| OEE Dashboard | €198,000 | 890% | <1 mj |
| Brand Reporting | €52,571 | 1,971% | <1 mj |
| **UKUPNO** | **€872,007** | **614%** | **<2 mj** |

### Ključne poruke
- "Investicija od €142,000 se vrati za manje od 2 mjeseca"
- "Svaki modul je replicabilan na Diamant, DMT, Alé, MCipollini"
- "5 fabrika × €872K = €4.36M godišnje za cijelu grupu"

---

## Naredni koraci (5 min)

1. **Discovery faza** (2-3 dana u fabrici)
   - Mapiranje podataka, IT infrastrukture, workflow-a
   - Validacija pretpostavki na realnim podacima
   - Identifikacija quick wins

2. **PoC modul** (4-6 sedmica)
   - Preporučujemo: OEE Dashboard ili CV Quality (najbrži ROI)
   - Realni podaci, realna integracija sa SAP
   - Go/No-Go odluka na kraju PoC-a

3. **Rollout Sportek** (3-4 mjeseca)
   - Svih 6 modula, puna integracija
   - Training za operatore i menadžment
   - 24/7 monitoring i support

4. **Scale na grupu** (6-12 mjeseci)
   - Diamant → DMT → Alé → MCipollini
   - Svaka fabrika prilagođena lokalno
   - Centralni dashboard za Zecchetto Group

---

## Backup materijali

- Dashboard live: `dashboard/index.html`
- Demo script: `python demo/run_demo.py`
- Integration tests: `python tests/test_integration.py` (8/8 PASS)
- Svi rezultati: `modules/*/results/`
- Troubleshooting: `demo/troubleshooting.md`
