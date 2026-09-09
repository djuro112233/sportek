"use client";
/**
 * Consent text **version v1**, rendered verbatim in both languages at once.
 *
 * This is the text the consent record points at (`consent.text_version = "v1"`), not UI chrome: it
 * is shown in Montenegrin and in English on the same screen, whichever interface language is
 * selected, so the host reads the wording that is published on the prototype site. Changing a word
 * here means a new version string, and a new version has to be published in both languages.
 */
import styles from "./host.module.css";

interface ConsentBlock {
  heading: string;
  intro: string;
  points: string[];
  withdraw: string;
}

export const CONSENT_TEXT_VERSION = "v1";

const CONSENT_V1: Record<"cnr" | "en", ConsentBlock> = {
  cnr: {
    heading: "Saglasnost domaćina — verzija v1",
    intro:
      "Objavljujem svoju ponudu u prototipu „Vrmac — živa baština“. Ovaj tekst saglasnosti objavljen je na sajtu prototipa na crnogorskom i engleskom jeziku.",
    points: [
      "Dijelim svoje riječi: snimak ili tekst koji sam sam/sama napravio/la, i podatke koje sam unio/unijela.",
      "Snimak se pretvara u tekst, a asistent iz mojih riječi predlaže samo naslov i opis. Cijena, sezona, kapacitet, pristupačnost i lokacija nikada se ne pogađaju — njih unosim i potvrđujem ja.",
      "Prije objave oglas pregleda validator (Napredak, Gornja Lastva). Posjetiocima je vidljivo samo ono što je odobreno.",
      "Oglas se objavljuje na crnogorskom i engleskom jeziku.",
      "Nema rezervacija i nema plaćanja. Poruka posjetioca je samo poruka; potvrda nije ugovor.",
      "Ovo je prototip sa uzorkom podataka, izrađen za prijavu SMART ERA — nije komercijalna usluga.",
      "Statistika se vodi zbirno i pseudonimizovano; moje ime i e-pošta ne objavljuju se uz oglas.",
    ],
    withdraw:
      "Saglasnost mogu povući u svakom trenutku — oglas se tada uklanja iz objave. Povlačenje se traži preko Napretka ili u ovoj aplikaciji.",
  },
  en: {
    heading: "Host consent — version v1",
    intro:
      "I am publishing my offer in the “Vrmac Living Heritage” prototype. This consent text is published on the prototype site in Montenegrin and in English.",
    points: [
      "I am sharing my own words: a recording or text I made myself, and the details I typed in.",
      "The recording is turned into text, and the assistant proposes a title and a description from my words only. Price, season, capacity, accessibility and location are never guessed — I enter and confirm them.",
      "Before publication the listing is reviewed by a validator (Napredak, Gornja Lastva). Visitors only ever see what has been approved.",
      "The listing is published in Montenegrin and in English.",
      "No bookings and no payments. A visitor request is only a message; a confirmation is not a contract.",
      "This is a prototype with sample data, built for the SMART ERA application — not a commercial service.",
      "Statistics are kept in aggregate and pseudonymised; my name and e-mail are not published with the listing.",
    ],
    withdraw:
      "I may withdraw this consent at any time — the listing is then removed from publication. Withdrawal is requested through Napredak or in this application.",
  },
};

function Block({ block }: { block: ConsentBlock }) {
  return (
    <section>
      <h4>{block.heading}</h4>
      <p>{block.intro}</p>
      <ul>
        {block.points.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <p>{block.withdraw}</p>
    </section>
  );
}

export default function ConsentText() {
  return (
    <div className={styles.consent} tabIndex={0} role="region" aria-label="Consent v1 / Saglasnost v1">
      <Block block={CONSENT_V1.cnr} />
      <hr />
      <Block block={CONSENT_V1.en} />
    </div>
  );
}
