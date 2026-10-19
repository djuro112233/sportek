# Usability protocol: facilitated sessions with 5 to 10 women

This protocol produces the rows of `eval/usability_sessions.csv` and the "Usability" section
of the measurement report (`docs/evaluation.md`, section 1.6). It is deliberately small: one
task, three questions, under 30 minutes per participant.

## 1. Recruitment

- 5 to 10 women from the groups MILA is built for: pregnant women and new mothers attending
  the partner clinic, adolescents (16 to 19) with a parent or guardian present, women from
  Roma settlements, and women living in rural municipalities with limited access to a
  gynaecologist. Aim for at least two participants from each of two different groups.
- Recruited by the clinic's nurse or social worker through the usual channels (waiting room,
  community mediator), never through MILA itself and never online.
- Each participant receives a **pseudonym** (`P01`, `P02`, ...) assigned by the facilitator.
  The sheet that links pseudonyms to people stays locked at the clinic and is destroyed at the
  end of the pilot. The repository never contains the link.
- Participants are not paid; travel costs are reimbursed by the clinic.

## 2. Consent

Before the session the facilitator reads the consent text in the participant's language and
hands over a printed copy. It says:

- what MILA is (information and referral, not a doctor) and what the session is for;
- that the facilitator will note whether the task was completed, how long it took, and up to
  three comments in the participant's own words, with any personal detail removed;
- that no audio of the session is kept: the recordings MILA makes to transcribe a question are
  deleted immediately, and the facilitator does not record the room;
- that the participant may stop at any time, with no effect on her care at the clinic;
- that the summary (completion rate, times, anonymised comments) will be published in a report.

For a participant under 18 the guardian signs as well, and the row's `group` is
`minor_with_guardian`. A session starts only with `consent_recorded = true`.

## 3. Setup

- A phone or tablet with the MILA web client, headphones available, on the clinic's Wi-Fi or a
  mobile connection (note which, as low bandwidth is part of what we test).
- MILA in demo mode with the current knowledge base, in the participant's language and script.
- A printed **referral card** (emergency number, clinic number, helplines from
  `ReferralService`) on the table, so that a participant who raises a real concern during the
  session is handed a concrete contact immediately.
- A facilitator (clinic staff or project member) and, when possible, a second observer taking
  the timings.

## 4. Task

The participant is told:

> Ask MILA three questions by voice, in your own words, about things you would like to know.
> If you do not know what to ask, here are some topics: contraception, the morning-after pill,
> check-ups in pregnancy, food in pregnancy, breastfeeding, periods, infections and testing,
> feeling low after birth. After each question MILA will show you what it understood; confirm
> it or say it again. Then read or listen to the answer.

Rules:

- No help from the facilitator during the three questions, except to repeat the instruction.
  If the participant cannot continue without help, the facilitator helps, and
  `task_completed` is `false`.
- The participant chooses the questions. The facilitator **does not write the questions
  down**; only whether an answer, a refusal or a referral came back.
- A red-flag response (MILA tells her to seek care now) counts as a completed step; the
  facilitator then pauses the session and follows section 7.

## 5. Metrics recorded per participant

| Column | Meaning |
|---|---|
| `participant_id` | Pseudonym `P01` ... |
| `group` | `adult` or `minor_with_guardian` |
| `task_completed` | `true` if all three questions were asked and each received an answer, refusal or referral without facilitator help |
| `time_s` | Seconds from the first tap on "Ask by voice" to the third response being shown |
| `comment1`, `comment2`, `comment3` | Up to three comments in the participant's words (see section 6) |
| `consent_recorded` | `true` only with the signed form on file |

The measurement report gives the completion rate, the median and range of `time_s`, the number
of participants per group, and the comments verbatim. Groups with fewer than five participants
are shown as a count only.

## 6. Capturing comments

After the task, the facilitator asks three open questions and writes down the answers as close
to verbatim as possible, in the participant's language:

1. "What was easy or hard about asking by voice?"
2. "Did you understand the answer? Was anything missing or confusing?"
3. "Would you use this again, and when?"

Before saving, the facilitator removes anything that could identify the participant or a third
person (names, places, employers, specific dates, details of her own medical situation) and
replaces it with a neutral word in square brackets, e.g. "[my town]". Comments are stored in
the CSV only; they are never entered into MILA.

## 7. Safety during the session

- A facilitator is present for the whole session; the participant is never left alone with the
  device.
- If a question reveals an urgent problem (bleeding in pregnancy, thoughts of self-harm,
  violence at home, a minor describing contact with an adult), the facilitator stops the test,
  hands over the printed referral card, and follows the clinic's own procedure. The row is still
  recorded (the task may be marked incomplete) and the event is noted in the facilitator's log
  without details.
- The facilitator reminds the participant that MILA gives general information and that her
  clinician is the one to decide about her care.
- Participants who become distressed can stop at any time; the facilitator offers a
  conversation with the clinic's nurse.

## 8. After the session

- Append the row to `eval/usability_sessions.csv` (remove nothing from earlier rows; the
  `EXAMPLE` row stays as documentation and is ignored by `measure.py`).
- Run `scripts/measure.py` after the last session and commit the report together with the CSV.
- Keep the facilitator's log (device, connection, incidents) at the clinic; only aggregate
  notes go into the report's "Caveats".
