# Grounding test results — grounded answers or refusal

*Prototype built for the SMART ERA application, September–October 2026. Sample data.* — generated 2026-09-09T22:11:22+00:00 by `python -m app.cli grounding-test` / `tests/test_grounding.py`.

**Result: PASS** — answerable 40/40 (100%, floor 90%) answered with an approved citation; unanswerable 20/20 (100%) withheld.

Providers: embeddings `hash` (`hashed-lexical-v1`, 768-d, top-k 5), LLM `none`, support check `lexical` (min score 0.75).

Gate: similarity ≥ 0.35 AND IDF-weighted coverage ≥ 0.34 (stems: first 4 characters; language bonus 0.05, coverage rank weight 0.25).

## Per launch language

| language | answerable answered | rate | unanswerable withheld | rate | pass |
|---|---|---|---|---|---|
| cnr | 20/20 | 100% | 10/10 | 100% | PASS |
| en | 20/20 | 100% | 10/10 | 100% | PASS |

## Signal distribution (how the thresholds were calibrated)

| signal | set | n | min | median | max |
|---|---|---|---|---|---|
| similarity | answerable | 40 | 0.4231 | 0.6218 | 0.9049 |
| similarity | unanswerable | 20 | 0.0455 | 0.1175 | 0.4932 |
| coverage | answerable | 40 | 0.3899 | 1.0 | 1.0 |
| coverage | unanswerable | 20 | 0.0 | 0.1424 | 0.4422 |
| confidence | answerable | 40 | 0.481 | 0.779 | 0.952 |
| confidence | unanswerable | 20 | 0.023 | 0.1695 | 0.391 |

### cnr

| signal | set | n | min | median | max |
|---|---|---|---|---|---|
| similarity | answerable | 20 | 0.436 | 0.6218 | 0.9015 |
| similarity | unanswerable | 10 | 0.062 | 0.1157 | 0.4484 |
| coverage | answerable | 20 | 0.3899 | 1.0 | 1.0 |
| coverage | unanswerable | 10 | 0.0 | 0.1904 | 0.4422 |
| confidence | answerable | 20 | 0.481 | 0.781 | 0.951 |
| confidence | unanswerable | 10 | 0.031 | 0.1655 | 0.379 |

### en

| signal | set | n | min | median | max |
|---|---|---|---|---|---|
| similarity | answerable | 20 | 0.4231 | 0.6134 | 0.9049 |
| similarity | unanswerable | 10 | 0.0455 | 0.2019 | 0.4932 |
| coverage | answerable | 20 | 0.5814 | 1.0 | 1.0 |
| coverage | unanswerable | 10 | 0.0 | 0.1073 | 0.2891 |
| confidence | answerable | 20 | 0.544 | 0.776 | 0.952 |
| confidence | unanswerable | 10 | 0.023 | 0.177 | 0.391 |

## Questions

| id | lang | question | expected | outcome | conf. | sim. | cov. | cited slugs | supported | dropped | pass |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cnr-a01 | cnr | Iz kojeg vijeka je crkva Svete Marije u Gornjoj Lastvi? | answer | answer | 0.921 | 0.841 | 1.000 | crkva-sv-marije | 1 | 0 | PASS |
| cnr-a02 | cnr | Iz kojeg vijeka je crkva Svetog Vida iznad Gornje Lastve? | answer | answer | 0.891 | 0.782 | 1.000 | crkva-sv-vida | 1 | 0 | PASS |
| cnr-a03 | cnr | Na kojoj nadmorskoj visini se nalazi crkva Svetog Vida? | answer | answer | 0.799 | 0.598 | 1.000 | crkva-sv-vida | 1 | 0 | PASS |
| cnr-a04 | cnr | Kojeg dana se održava Lastovska fešta? | answer | answer | 0.611 | 0.621 | 0.600 | lastovska-festa | 1 | 0 | PASS |
| cnr-a05 | cnr | Od koje godine se održava Lastovska fešta? | answer | answer | 0.835 | 0.671 | 1.000 | lastovska-festa | 1 | 0 | PASS |
| cnr-a06 | cnr | Kada će biti 53. Lastovska fešta? | answer | answer | 0.811 | 0.622 | 1.000 | lastovska-festa | 1 | 0 | PASS |
| cnr-a07 | cnr | Od koje godine se održavaju Dani pejzaža? | answer | answer | 0.887 | 0.775 | 1.000 | dani-pejzaza | 1 | 0 | PASS |
| cnr-a08 | cnr | Kako se zove dom kulture u Gornjoj Lastvi? | answer | answer | 0.777 | 0.555 | 1.000 | dom-kulture-ilija-markovic | 1 | 0 | PASS |
| cnr-a09 | cnr | Do koje godine su u Gornjoj Lastvi radili mlinovi za masline? | answer | answer | 0.951 | 0.901 | 1.000 | mlinovi-za-masline | 1 | 0 | PASS |
| cnr-a10 | cnr | Koliko je stalnih stanovnika imala Gornja Lastva po popisu iz 2011. godine? | answer | answer | 0.908 | 0.816 | 1.000 | popis-2011 | 1 | 0 | PASS |
| cnr-a11 | cnr | Gdje se nalazi Gornja Lastva? | answer | answer | 0.481 | 0.573 | 0.390 | gornja-lastva | 1 | 0 | PASS |
| cnr-a12 | cnr | Kojoj opštini pripadaju Gornja i Donja Lastva? | answer | answer | 0.785 | 0.570 | 1.000 | tivat | 1 | 0 | PASS |
| cnr-a13 | cnr | Šta je Donja Lastva i gdje se nalazi? | answer | answer | 0.572 | 0.646 | 0.498 | donja-lastva | 1 | 0 | PASS |
| cnr-a14 | cnr | Šta je Tivat? | answer | answer | 0.815 | 0.630 | 1.000 | tivat | 1 | 0 | PASS |
| cnr-a15 | cnr | Između kojih zaliva se nalazi brdo Vrmac? | answer | answer | 0.629 | 0.458 | 0.800 | vrmac-plateau | 1 | 0 | PASS |
| cnr-a16 | cnr | Vodi li pješačka staza iz Donje Lastve u Gornju Lastvu? | answer | answer | 0.771 | 0.542 | 1.000 | donja-lastva | 2 | 0 | PASS |
| cnr-a17 | cnr | Koje crkve ima selo Gornja Lastva? | answer | answer | 0.720 | 0.440 | 1.000 | gornja-lastva | 2 | 0 | PASS |
| cnr-a18 | cnr | Čemu su posvećeni Dani pejzaža? | answer | answer | 0.728 | 0.456 | 1.000 | dani-pejzaza | 1 | 0 | PASS |
| cnr-a19 | cnr | Šta se održava u Domu kulture „Ilija Marković“? | answer | answer | 0.593 | 0.626 | 0.560 | dom-kulture-ilija-markovic, gornja-lastva | 2 | 0 | PASS |
| cnr-a20 | cnr | Kako se dolazi do crkve Svetog Vida iz sela? | answer | answer | 0.596 | 0.436 | 0.757 | crkva-sv-vida | 2 | 0 | PASS |
| cnr-u01 | cnr | Gdje je 1687. godine sakriveno zlatno zvono Vrmca? | withhold | withhold | 0.172 | 0.114 | 0.230 | — | 0 | 0 | PASS |
| cnr-u02 | cnr | Koliko je đaka imala stara škola u Gornjoj Lastvi 1931. godine? | withhold | withhold | 0.310 | 0.448 | 0.172 | — | 0 | 0 | PASS |
| cnr-u03 | cnr | Kada je u Lastvi otkrivena rimska vila sa mozaicima? | withhold | withhold | 0.117 | 0.184 | 0.050 | — | 0 | 0 | PASS |
| cnr-u04 | cnr | Koliko stanovnika ima Gornji Stoliv? | withhold | withhold | 0.379 | 0.316 | 0.442 | — | 0 | 0 | PASS |
| cnr-u05 | cnr | Koje crkve i kestenove šume ima Gornji Stoliv? | withhold | withhold | 0.164 | 0.118 | 0.209 | — | 0 | 0 | PASS |
| cnr-u06 | cnr | Kada polazi trajekt za Bari? | withhold | withhold | 0.032 | 0.063 | 0.000 | — | 0 | 0 | PASS |
| cnr-u07 | cnr | Koliko košta noćenje u hotelima u Budvi? | withhold | withhold | 0.059 | 0.117 | 0.000 | — | 0 | 0 | PASS |
| cnr-u08 | cnr | Kakvo će vrijeme biti sjutra u Tivtu? | withhold | withhold | 0.031 | 0.062 | 0.000 | — | 0 | 0 | PASS |
| cnr-u09 | cnr | Kada se otvaraju banke u Tivtu? | withhold | withhold | 0.167 | 0.079 | 0.255 | — | 0 | 0 | PASS |
| cnr-u10 | cnr | Kolika je visina Njegoševog mauzoleja na Lovćenu? | withhold | withhold | 0.237 | 0.063 | 0.412 | — | 0 | 0 | PASS |
| en-a01 | en | From which century is the church of St Mary in Gornja Lastva? | answer | answer | 0.952 | 0.905 | 1.000 | crkva-sv-marije | 1 | 0 | PASS |
| en-a02 | en | From which century is the church of St Vitus above Gornja Lastva? | answer | answer | 0.893 | 0.787 | 1.000 | crkva-sv-vida | 1 | 0 | PASS |
| en-a03 | en | At what altitude does the church of St Vitus stand? | answer | answer | 0.781 | 0.563 | 1.000 | crkva-sv-vida | 2 | 0 | PASS |
| en-a04 | en | On which day is the Lastovska fešta held? | answer | answer | 0.618 | 0.655 | 0.581 | lastovska-festa | 1 | 0 | PASS |
| en-a05 | en | Since which year has the Lastovska fešta been held? | answer | answer | 0.560 | 0.450 | 0.671 | lastovska-festa | 1 | 0 | PASS |
| en-a06 | en | When will the 53rd Lastovska fešta take place? | answer | answer | 0.629 | 0.587 | 0.672 | lastovska-festa | 1 | 0 | PASS |
| en-a07 | en | Since which year have the Landscape Days been held? | answer | answer | 0.624 | 0.527 | 0.722 | dani-pejzaza | 1 | 0 | PASS |
| en-a08 | en | What is the name of the culture house in Gornja Lastva? | answer | answer | 0.798 | 0.597 | 1.000 | dom-kulture-ilija-markovic | 1 | 0 | PASS |
| en-a09 | en | Until which year did the olive mills operate in Gornja Lastva? | answer | answer | 0.771 | 0.771 | 0.770 | mlinovi-za-masline | 1 | 0 | PASS |
| en-a10 | en | How many permanent residents did Gornja Lastva have in the 2011 census? | answer | answer | 0.690 | 0.640 | 0.740 | popis-2011 | 1 | 0 | PASS |
| en-a11 | en | Where is Gornja Lastva located? | answer | answer | 0.796 | 0.591 | 1.000 | gornja-lastva | 1 | 0 | PASS |
| en-a12 | en | Which municipality do Gornja and Donja Lastva belong to? | answer | answer | 0.820 | 0.640 | 1.000 | tivat | 1 | 0 | PASS |
| en-a13 | en | What is Donja Lastva and where is it? | answer | answer | 0.896 | 0.792 | 1.000 | donja-lastva | 1 | 0 | PASS |
| en-a14 | en | What is Tivat? | answer | answer | 0.815 | 0.630 | 1.000 | tivat | 1 | 0 | PASS |
| en-a15 | en | Between which bays does the hill of Vrmac lie? | answer | answer | 0.544 | 0.423 | 0.664 | vrmac-plateau | 1 | 0 | PASS |
| en-a16 | en | Is there a footpath from Donja Lastva up to Gornja Lastva? | answer | answer | 0.851 | 0.701 | 1.000 | donja-lastva | 2 | 0 | PASS |
| en-a17 | en | Which churches does the village of Gornja Lastva have? | answer | answer | 0.740 | 0.480 | 1.000 | crkva-sv-marije | 1 | 0 | PASS |
| en-a18 | en | What are the Landscape Days dedicated to? | answer | answer | 0.771 | 0.542 | 1.000 | dani-pejzaza | 2 | 0 | PASS |
| en-a19 | en | What takes place in the culture house Ilija Marković? | answer | answer | 0.729 | 0.676 | 0.782 | dom-kulture-ilija-markovic, gornja-lastva | 2 | 0 | PASS |
| en-a20 | en | How is the church of St Vitus reached from the village? | answer | answer | 0.792 | 0.584 | 1.000 | crkva-sv-vida | 2 | 0 | PASS |
| en-u01 | en | Where was the golden bell of Vrmac hidden in 1687? | withhold | withhold | 0.177 | 0.240 | 0.113 | — | 0 | 0 | PASS |
| en-u02 | en | How many pupils did the old school in Gornja Lastva have in 1931? | withhold | withhold | 0.391 | 0.493 | 0.289 | — | 0 | 0 | PASS |
| en-u03 | en | When was the Roman villa with mosaics discovered at Lastva? | withhold | withhold | 0.177 | 0.299 | 0.056 | — | 0 | 0 | PASS |
| en-u04 | en | How many inhabitants does Gornji Stoliv have? | withhold | withhold | 0.106 | 0.111 | 0.101 | — | 0 | 0 | PASS |
| en-u05 | en | Which churches and chestnut woods are there in Gornji Stoliv? | withhold | withhold | 0.186 | 0.164 | 0.209 | — | 0 | 0 | PASS |
| en-u06 | en | What time does the ferry to Bari leave? | withhold | withhold | 0.045 | 0.090 | 0.000 | — | 0 | 0 | PASS |
| en-u07 | en | How much does a hotel room in Budva cost? | withhold | withhold | 0.050 | 0.100 | 0.000 | — | 0 | 0 | PASS |
| en-u08 | en | What will the weather be like tomorrow in Tivat? | withhold | withhold | 0.216 | 0.252 | 0.181 | — | 0 | 0 | PASS |
| en-u09 | en | When do the banks in Tivat open? | withhold | withhold | 0.237 | 0.292 | 0.181 | — | 0 | 0 | PASS |
| en-u10 | en | How high is the Njegoš mausoleum on Lovćen? | withhold | withhold | 0.023 | 0.046 | 0.000 | — | 0 | 0 | PASS |

## Answers against the independently prepared reference

- **cnr-a01** — Crkva Svete Marije u Gornjoj Lastvi potiče iz 14. vijeka. [1]
  - *expected:* Crkva Svete Marije u Gornjoj Lastvi potiče iz 14. vijeka.
- **cnr-a02** — Crkva Svetog Vida iz 9. vijeka nalazi se na 440 metara nadmorske visine iznad Gornje Lastve. [1]
  - *expected:* Crkva Svetog Vida je iz 9. vijeka.
- **cnr-a03** — Crkva Svetog Vida iz 9. vijeka nalazi se na 440 metara nadmorske visine iznad Gornje Lastve. [1]
  - *expected:* Na 440 metara nadmorske visine.
- **cnr-a04** — 53. Lastovska fešta biće održana u subotu, 7. avgusta 2027. godine. [1]
  - *expected:* Svake prve subote u avgustu.
- **cnr-a05** — 53. Lastovska fešta biće održana u subotu, 7. avgusta 2027. godine. [1]
  - *expected:* Od 1974. godine.
- **cnr-a06** — 53. Lastovska fešta biće održana u subotu, 7. avgusta 2027. godine. [1]
  - *expected:* U subotu, 7. avgusta 2027. godine.
- **cnr-a07** — Dani pejzaža se u Gornjoj Lastvi održavaju od 2015. godine. [1]
  - *expected:* Od 2015. godine.
- **cnr-a08** — Dom kulture „Ilija Marković“ je mjesto kulturnih događaja u Gornjoj Lastvi. [1]
  - *expected:* Dom kulture „Ilija Marković“.
- **cnr-a09** — U Gornjoj Lastvi su do 1945. godine radili mlinovi za masline. [1]
  - *expected:* Do 1945. godine.
- **cnr-a10** — Po popisu iz 2011. godine Gornja Lastva nije imala stalnih stanovnika. [1]
  - *expected:* Nijednog: po popisu iz 2011. godine Gornja Lastva nije imala stalnih stanovnika.
- **cnr-a11** — Gornja Lastva je staro naselje na padinama Vrmca iznad Donje Lastve i Tivta, u Crnoj Gori. [1]
  - *expected:* Na padinama brda Vrmac, iznad Donje Lastve i Tivta u Boki Kotorskoj.
- **cnr-a12** — Tivat je grad i opština u Boki Kotorskoj; Gornja i Donja Lastva pripadaju opštini Tivat. [1]
  - *expected:* Opštini Tivat.
- **cnr-a13** — Donja Lastva is the coastal settlement below Gornja Lastva on the shore of the Bay of Tivat. [1]
  - *expected:* Naselje na obali Tivatskog zaliva, sjeverozapadno od centra Tivta, ispod Gornje Lastve.
- **cnr-a14** — Tivat je grad i opština u Boki Kotorskoj; Gornja i Donja Lastva pripadaju opštini Tivat. [1]
  - *expected:* Grad na obali Tivatskog zaliva u Boki Kotorskoj i sjedište istoimene opštine.
- **cnr-a15** — Vrmac je brdo između Tivatskog i Kotorskog zaliva; Gornja Lastva leži na njegovim padinama. [1]
  - *expected:* Između Tivatskog i Kotorskog zaliva.
- **cnr-a16** — Donja Lastva je naselje na obali Tivatskog zaliva, sjeverozapadno od centra Tivta. [1] Iz Donje Lastve vodi pješačka staza uzbrdo do Gornje Lastve. [1]
  - *expected:* Da, iz Donje Lastve vodi pješačka staza uzbrdo do Gornje Lastve.
- **cnr-a17** — Gornja Lastva je staro seosko naselje na obroncima brda Vrmac, iznad Donje Lastve i grada Tivta u Boki Kotorskoj. [1] Selo ima crkvu Svete Marije iz 14. vijeka i, na visini od 440 metara, crkvu Svetog Vida iz 9. vijeka. [1]
  - *expected:* Crkva Svete Marije iz 14. vijeka i crkva Svetog Vida iz 9. vijeka na 440 metara.
- **cnr-a18** — Dani pejzaža su manifestacija posvećena kulturnom pejzažu Vrmca i Gornje Lastve. [1]
  - *expected:* Kulturnom pejzažu Vrmca i Gornje Lastve, odnosno zaštiti i oživljavanju baštine i predjela.
- **cnr-a19** — Dom kulture „Ilija Marković“ je mjesto kulturnih događaja u Gornjoj Lastvi. [1] Kulturni život odvija se u Domu kulture „Ilija Marković“. [2]
  - *expected:* Izložbe, predavanja, radionice i skupovi zajednice, uključujući programe Dana pejzaža.
- **cnr-a20** — Crkva Svetog Vida (Sv. Vid) je mala crkva iz 9. vijeka, jedna od najstarijih u ovom dijelu Boke. [1] Nalazi se na visini od 440 metara nadmorske visine, na brdu iznad Gornje Lastve, i do nje vodi pješačka staza iz sela. [1]
  - *expected:* Pješačkom stazom iz Gornje Lastve na brdo, do crkve na 440 metara.
- **cnr-u01** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: tvrdnja postoji samo u nacrtu koji nije odobren (sample-draft-zlatno-zvono), pa asistent mora odbiti.
- **cnr-u02** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: podatak postoji samo u unosu u statusu 'reviewed' (sample-reviewed-stara-skola), koji nije odobren.
- **cnr-u03** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: tvrdnja postoji samo u odbijenom unosu (sample-rejected-rimska-vila).
- **cnr-u04** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: unos o Gornjem Stolivu je nepotvrđen nacrt i nije objavljen.
- **cnr-u05** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: sve tvrdnje o Gornjem Stolivu osim položaja namjerno su izostavljene do provjere izvora.
- **cnr-u06** — withheld (`no_approved_source`)
  - *expected:* Bez odgovora: red vožnje trajekta nije dio odobrenih unosa o Vrmcu.
- **cnr-u07** — withheld (`no_approved_source`)
  - *expected:* Bez odgovora: cijene smještaja u Budvi nisu u opsegu prototipa.
- **cnr-u08** — withheld (`no_approved_source`)
  - *expected:* Bez odgovora: vremenska prognoza nije baštinski podatak i nema odobrenog izvora.
- **cnr-u09** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: radno vrijeme banaka nije dio odobrenih unosa.
- **cnr-u10** — withheld (`low_confidence`)
  - *expected:* Bez odgovora: Lovćen je izvan teritorije Vrmca i nema odobrenog unosa.
- **en-a01** — The church of St Mary in Gornja Lastva dates from the 14th century. [1]
  - *expected:* The church of St Mary in Gornja Lastva dates from the 14th century.
- **en-a02** — The 9th-century church of St Vitus stands at 440 metres above sea level above Gornja Lastva. [1]
  - *expected:* The church of St Vitus is from the 9th century.
- **en-a03** — The church of St Vitus (Sv. Vid) is a small church from the 9th century, one of the oldest in this part of the Bay of Kotor. [1] It stands at an altitude of 440 metres above sea level on the hill above Gornja Lastva and is reached by a footpath from the village. [1]
  - *expected:* At 440 metres above sea level.
- **en-a04** — The 53rd Lastovska fešta will be held on Saturday, 7 August 2027. [1]
  - *expected:* Every first Saturday of August.
- **en-a05** — The Lastovska fešta is held every first Saturday of August since 1974; the 53rd festival is on 7 August 2027. [1]
  - *expected:* Since 1974.
- **en-a06** — The 53rd Lastovska fešta will be held on Saturday, 7 August 2027. [1]
  - *expected:* On Saturday, 7 August 2027.
- **en-a07** — The Landscape Days (Dani pejzaža) have been held in Gornja Lastva since 2015. [1]
  - *expected:* Since 2015.
- **en-a08** — The culture house "Ilija Marković" is the venue of cultural events in Gornja Lastva. [1]
  - *expected:* The culture house "Ilija Marković".
- **en-a09** — Olive mills operated in Gornja Lastva until 1945. [1]
  - *expected:* Until 1945.
- **en-a10** — In the 2011 census Gornja Lastva had no resident population. [1]
  - *expected:* None: the 2011 census recorded no resident population in Gornja Lastva.
- **en-a11** — Gornja Lastva is an old settlement on the slopes of Vrmac above Donja Lastva and Tivat, Montenegro. [1]
  - *expected:* On the slopes of the Vrmac hill, above Donja Lastva and the town of Tivat in the Bay of Kotor.
- **en-a12** — Tivat is a town and municipality in the Bay of Kotor; Gornja and Donja Lastva belong to the municipality of Tivat. [1]
  - *expected:* The municipality of Tivat.
- **en-a13** — Donja Lastva is the coastal settlement below Gornja Lastva on the shore of the Bay of Tivat. [1]
  - *expected:* A settlement on the shore of the Bay of Tivat, north-west of the centre of Tivat, below Gornja Lastva.
- **en-a14** — Tivat je grad i opština u Boki Kotorskoj; Gornja i Donja Lastva pripadaju opštini Tivat. [1]
  - *expected:* A town on the Bay of Tivat in the Bay of Kotor and the seat of the municipality of the same name.
- **en-a15** — Vrmac is the hill between the Bay of Tivat and the Bay of Kotor; Gornja Lastva lies on its slopes. [1]
  - *expected:* Between the Bay of Tivat and the Bay of Kotor.
- **en-a16** — Donja Lastva is a settlement on the shore of the Bay of Tivat, north-west of the centre of Tivat. [1] A footpath leads uphill from Donja Lastva to Gornja Lastva. [1]
  - *expected:* Yes, a footpath leads uphill from Donja Lastva to Gornja Lastva.
- **en-a17** — Coordinates are approximate (village location). [1]
  - *expected:* The church of St Mary from the 14th century and the church of St Vitus from the 9th century at 440 metres.
- **en-a18** — The Landscape Days (Dani pejzaža) are an event dedicated to the cultural landscape of Vrmac and Gornja Lastva. [1] Held since 2015, they bring together experts, residents and visitors around the protection and revival of heritage and landscape. [1]
  - *expected:* To the cultural landscape of Vrmac and Gornja Lastva, and to the protection and revival of heritage and landscape.
- **en-a19** — The culture house "Ilija Marković" is the venue of cultural events in Gornja Lastva. [1] Cultural life takes place in the culture house Dom kulture "Ilija Marković". [2]
  - *expected:* Exhibitions, lectures, workshops and community meetings, including programmes of the Landscape Days.
- **en-a20** — The church of St Vitus (Sv. Vid) is a small church from the 9th century, one of the oldest in this part of the Bay of Kotor. [1] It stands at an altitude of 440 metres above sea level on the hill above Gornja Lastva and is reached by a footpath from the village. [1]
  - *expected:* By a footpath from Gornja Lastva up the hill to the church at 440 metres.
- **en-u01** — withheld (`low_confidence`)
  - *expected:* No answer: the claim exists only in a draft entry that was never approved (sample-draft-zlatno-zvono).
- **en-u02** — withheld (`low_confidence`)
  - *expected:* No answer: the figure exists only in an entry still in status 'reviewed' (sample-reviewed-stara-skola).
- **en-u03** — withheld (`low_confidence`)
  - *expected:* No answer: the claim exists only in a rejected entry (sample-rejected-rimska-vila).
- **en-u04** — withheld (`low_confidence`)
  - *expected:* No answer: the Gornji Stoliv entry is an unverified draft and is not published.
- **en-u05** — withheld (`low_confidence`)
  - *expected:* No answer: every claim about Gornji Stoliv beyond its position was deliberately omitted until the sources are checked.
- **en-u06** — withheld (`no_approved_source`)
  - *expected:* No answer: ferry timetables are not part of the approved entries about Vrmac.
- **en-u07** — withheld (`no_approved_source`)
  - *expected:* No answer: accommodation prices in Budva are outside the scope of the prototype.
- **en-u08** — withheld (`low_confidence`)
  - *expected:* No answer: a weather forecast is not a heritage fact and has no approved source.
- **en-u09** — withheld (`low_confidence`)
  - *expected:* No answer: bank opening hours are not part of the approved entries.
- **en-u10** — withheld (`no_approved_source`)
  - *expected:* No answer: Lovćen is outside the Vrmac territory and there is no approved entry about it.
