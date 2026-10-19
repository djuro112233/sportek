"""Lexical data for the red-flag router: term lists, regexes and classifier training seeds.

Everything here is written in the *normalised* form produced by ``app.core.i18n.normalize_text``
(Cyrillic transliterated to Latin, diacritics stripped, lowercase, punctuation removed), so the
router never has to normalise its own vocabulary at runtime.

Term syntax (used by ``app.core.redflags``):

* ``"word"``        - one token; fuzzy matching allowed (1 edit for >= 5 chars, 2 for >= 9)
* ``"stem*"``       - prefix match on one token (fuzzy on the stem part)
* ``"two words"``   - consecutive tokens, each matched fuzzily; also matched with spaces removed
* ``"=word"`` / ``"=two words"`` - exact match only, no fuzzy tolerance (for words with a benign
  near-neighbour such as ``sjecem`` / ``sjecam`` or ``rodila`` / ``radila``)
* a ``*`` may terminate any token inside a phrase (``"oduzm* sebi zivot"``)

Only Serbian/Bosnian/Montenegrin/Croatian (ekavian and ijekavian, formal and colloquial) and
English are covered; that is the language scope of the product.
"""

from __future__ import annotations

TermList = tuple[str, ...]

# ---------------------------------------------------------------------------------------------
# Context terms shared by several rules
# ---------------------------------------------------------------------------------------------

PREGNANCY_CTX: TermList = (
    "trudn*", "trudna", "trudnoca", "trudnoci", "trudnoce", "trudnocu", "trudnica", "trudnice", "gravid*", "pregnan*", "drugom stanju", "drugo stanje", "blagoslovenom stanju",
    "nosim bebu", "nosim dijete", "nosim dete", "ocekujem bebu", "ocekujem dijete", "ocekujem dete",
    "beba u stomaku", "bebu u stomaku", "beba u trbuhu", "bebu u trbuhu", "beba u meni",
    "trimestar", "trimestru", "trimester", "tromjesecj*", "tromesecj*",
    "=plod", "=ploda", "=fetus", "fetal", "expecting", "weeks along", "months along", "with child",
    "unborn", "my bump",
)

# Phrases that mention pregnancy only hypothetically (questions about becoming / not becoming
# pregnant). They are blanked out before the pregnancy context is evaluated.
HYPOTHETICAL_PREGNANCY_PATTERNS: tuple[str, ...] = (
    r"\b(?:da li|dal|jel|jeli|jesam li|mogu li|moze li|moglo bi|moguce|moguce li)(?: je| da| bi| bih| sam| se| ipak)*(?: ostala| ostanem| ostane| zatrudnjela| zatrudnela| budem| biti| bila| bude)? ?(?:trudna|u drugom stanju|zatrudn\w*)\b",
    r"\b(?:am i|could i be|can i be|can i get|might i be|chance (?:that )?i m|if i m|if i am|if i get|if i was|if i were|getting|become|became|to get|to become|avoid(?:ing)?|prevent(?:ing)?|risk of|chances? of|possibility of|possible|worried about|scared of|afraid of|fear of|not get|don t get|dont get|unwanted|unplanned) (?:pregnant|pregnancy|a pregnancy|getting pregnant)\b",
    r"\btest\w* (?:za|na) trudnoc\w*",
    r"\bpregnancy tests?\b",
    r"\b(?:zastit\w*|sprijec\w*|sprec\w*|izbje\w*|izbe\w*|zastita|prevencij\w*|rizik|rizika|strah|sansa|sanse|sansu|mogucnost|verovatnoca|vjerovatnoca) (?:od )?trudnoc\w*",
    r"\b(?:neplanir\w*|nezeljen\w*|nezelen\w*) trudnoc\w*",
    r"\b(?:planiram\w*|planiranj\w*|pokusavam\w*|pokusava\w*|zelim|zelimo|pripremam\w*|priprem\w* za|prije|pre|prekid\w*|prekinut\w*) (?:da )?(?:ostanem |budem |ostati |se )?trudn\w*",
    r"\bzatrudn\w*",
    r"\b(?:bojim se|plasim se|strah me|strah me je)(?: da)?(?: sam| cu| bih| necu| ne mogu)? ?(?:ostati |ostala |ostanem |budem |biti )?trudn\w*",
)

POSTPARTUM_CTX: TermList = (
    "porodil*", "porodaj*", "porodjaj*", "=rodila", "=rodila sam", "=sam rodila", "=nedavno rodila",
    "nakon poroda", "poslije poroda", "posle poroda", "babinj*", "lohij*", "carsk* rez*",
    "carskog reza", "carskim rezom", "postpartum", "post partum", "postnatal", "gave birth",
    "after birth", "after the birth", "after delivery", "since delivery", "c section", "cesarean",
    "caesarean", "sekcij*", "puerperij*",
)

BABY_TERMS: TermList = (
    "=beba", "=bebu", "=bebe", "=bebi", "=bebo", "bebic*", "=dete", "=dijete", "=djete", "=deteta",
    "=djeteta", "=plod", "=fetus", "=baby", "=babys", "=baby s", "=mala", "=mali", "=malena", "=maleni",
)

MENSTRUAL_CTX: TermList = (
    "menstru*", "mjesecnic*", "mesecnic*", "ciklus*", "=period", "=periods", "=pms", "=menga", "=mengu",
    "=menge", "=mengica", "mengic*", "ovulac*", "ovulat*",
)

# Bleeding that is almost certainly not gynaecological / obstetric (nosebleeds, gums).
NON_GYN_BLEEDING_CTX: TermList = (
    "iz nosa", "=nos", "=nosa", "=nosu", "=nose", "nosebleed*", "=desni", "=desnima", "=gums", "=gum",
    "=zub", "=zuba", "=zubi", "=zubu", "=tooth", "=teeth", "=rana", "=ranu", "=posjekla", "=posekla",
    "=cut", "=prst", "=prsta", "stolic*", "hemoroid*", "urin*", "mokrac*", "mokren*", "=urine", "=pee", "=stool",
    "hemorrhoid*", "haemorrhoid*", "=poop",
)
VAGINAL_BLEEDING_CUES: TermList = (
    "iz vagine", "vaginaln*", "=dole", "=dolje", "=odozdo", "=dolu", "uloz*", "ugrusc*", "=clots",
    "=pad", "=pads", "=tampon", "vaginal", "down there", "izmedju nogu", "iz materice", "iz rodnice",
)

# ---------------------------------------------------------------------------------------------
# bleeding_pregnancy
# ---------------------------------------------------------------------------------------------

BLEEDING: TermList = (
    "krvar*", "=krv", "=krvi", "krvav*", "iskrvar*", "prokrvar*", "curi krv", "ide krv", "izlazi krv",
    "izasla krv", "pojavila se krv", "bleed*", "=blood", "bloody", "hemorrhag*", "haemorrhag*",
    "ugrusc*", "ugrusak", "=clots", "=clot",
)

HEAVY_QUALIFIERS: TermList = (
    "=jako", "=jaka", "=jak", "=jace", "obiln*", "obilat*", "=puno", "=mnogo", "=dosta", "=strasno",
    "=uzasno", "=ogromno", "ne prestaje", "ne staje", "nece da stane", "ne moze da stane",
    "ne zaustavlja", "ne mogu zaustaviti", "ne mogu da zaustavim", "natap*", "natop*",
    "ulozak za sat", "ulozak na sat", "ulozak svakih", "uloske svakih", "ulozak svaki", "uloske svaki",
    "svaki sat", "svakih sat", "svakih pola sata", "svakih 15", "svakih 20", "svakih 30",
    "svakih 40", "svakih 45", "ugrusc*", "ugrusak", "ugruske", "komadi", "komade", "=lije",
    "kao slavina", "kao iz slavine", "kao cesma", "kao iz cesme", "=sipa", "=sika", "=siklja",
    "=heavy", "heavily", "soak*", "pad an hour", "pad every", "pads an hour", "won t stop",
    "will not stop", "doesn t stop", "does not stop", "can t stop", "cannot stop", "not stopping",
    "gushing", "pouring", "=clots", "=clot", "lot of blood", "so much blood", "too much blood",
    "=flooding", "like a tap", "like a faucet", "=massive", "=profuse", "=severe", "=heavier",
    "much heavier", "heavier than", "vise nego ikad", "najjace", "nikad ovako", "nikad ovoliko",
    "sve jace", "sve jaci", "sve vise", "pojacava", "pojacalo", "jace nego", "vise nego", "ponovo jako",
    "opet jako", "getting heavier", "more than before", "started again", "svjeze crven*", "sveze crven*",
    "svijetlo crven*", "svetlo crven*", "jarko crven*", "bright red", "=smrdi", "zaudara", "neugodan miris",
    "neprijatan miris", "smells bad", "foul smell", "bad smell",
)

# ---------------------------------------------------------------------------------------------
# fever_pregnancy
# ---------------------------------------------------------------------------------------------

FEVER_TERMS: TermList = (
    "imam temperaturu", "imam visoku temperaturu", "dobila temperaturu", "dobila sam temperaturu",
    "visoka temperatura", "visoku temperaturu", "visoke temperature", "temperatura mi je visoka",
    "skocila temperatura", "skocila mi temperatura", "temperatura skocila", "temperatura ne pada",
    "temperatura ne spada", "temperatura raste", "temperatura se penje", "penje temperatura",
    "gorim od temperature", "gori od temperature", "sva gorim", "groznic*", "vrucic*", "drhtavic*",
    "=jeza", "=jezu", "tresem se", "trese me", "tresu me", "tresavica", "cvokoc*", "=fever",
    "feverish", "=chills", "shivering", "shivers", "high temperature", "temperature of",
    "running a temperature", "burning up", "temperaturu i", "temperaturu od", "temperaturu preko",
    "temperaturu iznad", "temperaturu vec", "temperatura preko", "temperatura iznad", "temperatura od",
    "temperatura vec", "temperaturu koja", "temperatura koja",
)

# Numeric temperature of 38-42 (decimal already split by normalisation: "38,5" -> "38 5").
# Numbers followed by a unit that is not degrees (weeks, days, years, kg ...) are ignored.
TEMPERATURE_NUMBER_RE: str = (
    r"\b(3[89]|4[0-2])(?: ([0-9]))?\b"
    r"(?! ?(?:nedelj|nedjelj|tjed|sedmic|dan|god|kg|kil|cm|sat|min|tabl|mg|ml|posto|procen|put|dana|week|day|year|month|mjesec|mesec|h\b|k\b))"
)
# A number alone is not a fever: the text must also mention temperature / degrees.
TEMPERATURE_CUE_RE: str = r"\b(?:temperatur\w*|temp|tempa|tempu|groznic\w*|vrucic\w*|fever|stepen\w*|celzij\w*|celsius|degrees|c)\b"

# ---------------------------------------------------------------------------------------------
# preeclampsia
# ---------------------------------------------------------------------------------------------

HEADACHE_TERMS: TermList = (
    "glavobolj*", "boli me glava", "glava me boli", "bol u glavi", "bolovi u glavi", "boli glava",
    "pritisak u glavi", "headache*", "head hurts", "head is hurting", "head pain", "migren*", "migraine*",
)
SEVERE_HEADACHE_PHRASES: TermList = (
    "glava mi puca", "puca mi glava", "glava ce mi puci", "ce mi puci glava", "glava mi eksplodira",
    "eksplodirace mi glava", "glava mi se raspada", "raspada mi se glava", "head is splitting",
    "splitting headache", "head is pounding", "pounding headache", "worst headache",
    "head is exploding", "head feels like it will explode", "never had a headache like",
    "nikad ovakvu glavobolju", "nikad takvu glavobolju", "najgora glavobolja", "najgoru glavobolju",
)
PERSISTENT_QUALIFIERS: TermList = (
    "ne prolazi", "ne prestaje", "nece da prodje", "ne popusta", "stalno", "cijeli dan", "ceo dan",
    "cio dan", "danima", "won t go away", "doesn t go away", "does not go away", "won t stop",
    "doesn t stop", "persistent", "constant", "all day", "for days", "nista ne pomaze", "nothing helps",
)
VISION_TERMS: TermList = (
    "zamagljen vid", "zamagljen* vid*", "zamucen vid", "zamucen* vid*", "mutno vidim", "vidim mutno",
    "mutan vid", "zamagljeno", "zamuceno", "magli mi se", "mutni mi se", "vidim tacke", "vidim tackice",
    "tacke pred ocima", "tackice pred ocima", "mrlje pred ocima", "vidim mrlje", "zvezdice", "zvjezdice",
    "zvezdice pred ocima", "zvjezdice pred ocima", "bljesk*", "bljeskovi", "sijevanje pred ocima",
    "sevanje pred ocima", "sijeva mi pred ocima", "seva mi pred ocima", "svetlaci", "svjetlaci",
    "svjetlace", "svetlace", "svetle tacke", "svijetle tacke", "dupli vid", "duplo vidim",
    "vidim duplo", "dvostruko vidim", "ne vidim dobro", "slabije vidim", "losije vidim",
    "gubim vid", "crni mi se pred ocima", "pocrnilo mi je pred ocima", "blurred vision",
    "blurry vision", "vision is blurry", "vision is blurred", "blurry", "seeing spots", "see spots",
    "spots in my vision", "flashing lights", "flashes of light", "seeing stars", "double vision",
    "seeing double", "vision changes", "changes in my vision", "can t see properly", "cannot see properly",
    "can t see well", "vision problems", "problems with my vision", "losing my vision",
)
SWELLING_TERMS: TermList = (
    "otek*", "otok*", "otec*", "natek*", "natec*", "otic*", "nadu*", "swell*", "swollen", "puffy",
    "bloated",
)
FACE_HANDS_TERMS: TermList = (
    "=lice", "=licu", "=lica", "=licem", "=ruke", "=ruku", "=rukama", "=ruka", "=sake", "=saka",
    "=prsti", "=prste", "=prstiju", "=prstima", "=oci", "=ociju", "=ocima", "=kapci", "=kapke", "=kapaka",
    "=prsten", "=prstenje", "=face", "=hands", "=hand", "=fingers", "=finger", "=eyes", "=eyelids",
    "=ring", "=rings",
)
SUDDEN_SWELLING_PHRASES: TermList = (
    "ring doesn t fit", "ring won t come off", "can t get my ring off", "cant get my ring off",
    "ne mogu skinuti prsten", "ne mogu da skinem prsten", "prsten mi se ne skida",
    "prsten ne moze da se skine", "naglo otekla", "naglo oteklo", "naglo sam otekla",
    "odjednom otekla", "odjednom oteklo", "preko noci otekla", "preko noci oteklo",
    "swelled up suddenly", "swollen up overnight", "swollen overnight", "sudden swelling",
    "suddenly swollen", "swelling came on suddenly",
)

# ---------------------------------------------------------------------------------------------
# reduced_fetal_movement
# ---------------------------------------------------------------------------------------------

NOT_MOVING_TERMS: TermList = (
    "ne mrda", "se ne mrda", "ne mrda se", "nije se mrdala", "nije mrdala", "nije se mrdalo",
    "ne mice", "ne mice se", "se ne mice", "nije se micala", "nije se micalo", "ne pomera",
    "ne pomjera", "se ne pomera", "se ne pomjera", "ne pomera se", "ne pomjera se", "ne krece",
    "ne krece se", "se ne krece", "ne osecam pokrete", "ne osjecam pokrete", "ne osecam nikakve pokrete",
    "ne osjecam nikakve pokrete", "ne osecam pokret", "ne osjecam pokret", "ne osecam bebu",
    "ne osjecam bebu", "ne osecam dete", "ne osjecam dijete", "ne osecam da se", "ne osjecam da se",
    "ne osecam da mrda", "ne osjecam da mrda", "ne osecam je", "ne osjecam je", "ne osecam ga",
    "ne osjecam ga", "nisam osetila", "nisam osjetila", "nisam osetila pokret*", "nisam osjetila pokret*",
    "nisam osetila bebu", "nisam osjetila bebu", "nisam cula bebu", "manje se mrda", "mrda se manje",
    "manje mrda", "mrda manje", "slabije se mrda", "mrda slabije", "manje se mice", "mice se manje",
    "mice manje", "manje se pomera", "manje se pomjera", "pomera se manje", "pomjera se manje",
    "manje pokreta", "manje pokrete", "slabiji pokreti", "slabije pokrete", "slabi pokreti",
    "slabe pokrete", "rjedje pokrete", "redje pokrete", "rjedji pokreti", "redji pokreti",
    "rjedje se mrda", "redje se mrda", "nema pokreta", "nemam pokrete", "nema nikakvih pokreta",
    "bez pokreta", "nestali pokreti", "prestali pokreti", "prestala da se mrda", "prestala se mrdati",
    "prestala se micati", "prestala da se mice", "prestala da se pomera", "prestala da se pomjera",
    "prestalo da se mrda", "prestalo da se mice", "prestalo se micati", "prestalo se mrdati",
    "prestao da se mrda", "prestao da se mice", "ne sutira", "ne sutne", "ne rita se", "ne rita",
    "nema sutiranja", "ne sutira me", "ne sutira vise", "ne udara vise", "ne udara me vise",
    "previse mirna", "previse je mirna", "suvise mirna", "suvise je mirna", "neobicno mirna",
    "cudno mirna", "sumnjivo mirna", "nekako mirna", "mirna cijeli dan", "mirna ceo dan", "mirna cio dan",
    "mirna cijelo jutro", "mirna celo jutro", "previse tiha", "neobicno tiha", "not moving",
    "isn t moving", "is not moving", "isnt moving", "hasn t moved", "has not moved", "hasnt moved",
    "stopped moving", "stop moving", "fewer movements", "less movement", "less movements",
    "fewer kicks", "less kicks", "no movement", "no movements", "no kicks", "can t feel",
    "cannot feel", "can not feel", "cant feel", "haven t felt", "have not felt", "havent felt",
    "not kicking", "isn t kicking", "not felt", "don t feel the baby", "don t feel my baby",
    "dont feel the baby", "dont feel my baby", "not as active", "less active", "reduced movement",
    "reduced movements", "decreased movement", "decreased movements", "gone quiet", "very quiet",
    "too quiet", "unusually quiet", "quiet today", "quieter than usual", "barely moving",
    "barely moved", "hardly moving", "hardly moved", "not moved",
)

# ---------------------------------------------------------------------------------------------
# severe_abdominal_pain
# ---------------------------------------------------------------------------------------------

ABDOMEN_TERMS: TermList = (
    "=stomak", "=stomaka", "=stomaku", "=stomakom", "stomacn*", "stomacic", "=trbuh", "=trbuha", "=trbuhu",
    "=trbuhom", "trbusn*", "trbuscic", "donji deo", "donjem delu", "donji dio", "donjem dijelu",
    "donjem stomaku", "donjem trbuhu", "=dole", "=dolje", "=dolu", "karlic*", "zdjelic*", "zdelic*",
    "jajnik*", "jajovod*", "materic*", "slabin*", "prepon*", "=boku", "=bok", "jedne strane",
    "jednoj strani", "desne strane", "desnoj strani", "lijeve strane", "leve strane", "lijevoj strani",
    "levoj strani", "s desne", "s lijeve", "s leve", "sa desne", "sa lijeve", "sa leve", "ispod rebara",
    "pod rebrima", "abdomen", "abdominal", "belly", "stomach", "pelvis", "pelvic", "lower abdomen",
    "tummy", "one side", "right side", "left side", "my side", "ovary", "ovaries", "under my ribs",
    "groin", "u stomaku", "u trbuhu", "=krsta", "=krstima",
)

PAIN_TERMS: TermList = (
    "=bol", "=boli", "=bole", "=bolu", "bolov*", "=bolno", "=bolna", "boli me", "bole me", "grc*",
    "probad*", "=pain", "=pains", "painful", "hurt*", "cramp*", "=ache", "aching", "stabbing",
    "sijev*", "razdir*", "=steze", "=stezanje", "=zateg", "contractions", "kontrakcij*", "trudov*",
)

# Severity tiers. Tier 1 is strong but common wording; tier 2 is extreme / functional impact.
SEVERE_TIER1: TermList = (
    "=jak", "=jaka", "=jaki", "=jako", "=jaku", "=jake", "=jakih", "=jakim", "=jace", "=jaci",
    "=ostar", "=ostra", "=ostri", "=ostru", "=ostre", "=ostrog", "=ostrim", "probadajuc*", "sijevajuc*",
    "sevajuc*", "razdiruc*", "=sharp", "=bad", "really bad", "so bad", "=intense", "=strong", "=terrible",
    "=horrible", "=awful", "=extreme", "=extremely", "sve jace", "sve jaci", "sve gore", "sve gori",
    "pogorsava", "getting worse", "worse and worse", "=brutal", "=brutalan", "=brutalno", "=zestok",
    "=zestoka", "=zestoki", "=zestoko", "=grozno", "=grozan", "=grozna",
)
SEVERE_TIER2: TermList = (
    "nepodnosljiv*", "nesnosljiv*", "nesnosn*", "neizdrziv*", "nepodnosiv*", "uzasn*", "uzasan",
    "strasn*", "strasan", "najgor*", "najjac*", "paklen*", "ne mogu da stojim", "ne mogu stajati",
    "ne mogu da stanem", "ne mogu stati na noge", "ne mogu da se uspravim", "ne mogu se uspraviti",
    "ne mogu da se ispravim", "ne mogu se ispraviti", "ne mogu da hodam", "ne mogu hodati",
    "ne mogu da se pomerim", "ne mogu da se pomjerim", "ne mogu se pomaknuti", "ne mogu da se pomaknem",
    "ne mogu da izdrzim", "ne mogu izdrzati", "ne mogu da trpim", "ne mogu trpjeti", "ne mogu trpeti",
    "ne mogu vise da trpim", "ne mogu da se uspravim", "savijam se", "savila sam se", "savijena",
    "previjam se", "presavijam se", "presavila", "presavijena", "previja*", "grcim se", "padam u nesvest",
    "padam u nesvijest", "pala u nesvest", "pala u nesvijest", "onesvest*", "onesvijest*", "nesvest*",
    "nesvjest*", "gubim svest", "gubim svijest", "izgubila svest", "izgubila svijest",
    "crni mi se pred ocima", "pocrnilo mi je", "hladan znoj", "hladnom znoju", "oblivena znojem",
    "=severe", "=unbearable", "excruciating", "=agony", "agonizing", "agonising", "=worst", "worst pain",
    "can t stand", "cannot stand", "can t stand up", "cant stand", "can t walk", "cannot walk",
    "cant walk", "can t move", "cannot move", "cant move", "can t straighten", "doubled over",
    "doubled up", "curled up", "passed out", "pass out", "fainted", "fainting", "blacked out",
    "about to faint", "going to faint", "10 od 10", "10 10", "deset od deset", "ten out of ten",
    "worst pain of my life", "never felt pain like", "nikad takav bol", "nikad takvu bol",
    "nikad jaci bol", "nikad ovakav bol", "nikad ovakvu bol", "vristim", "vrisnem", "placem od bol*",
    "placem od bolova", "urlam od", "screaming", "crying from the pain", "crying in pain",
    "crying from pain", "nozem", "kao nozem", "kao noz", "kao da me seku", "kao da me sijeku",
    "kao da me neko sece", "like a knife", "being stabbed",
)

# ---------------------------------------------------------------------------------------------
# suicidal_ideation
# ---------------------------------------------------------------------------------------------

SUICIDE_TERMS: TermList = (
    # explicit suicide
    "da se ubijem", "ubicu se", "ubit cu se", "ubiti se", "ubijem se", "se ubijem", "ubila bih se",
    "ubila bi se", "ubio bih se", "ubila se", "ubijem sebe", "ubiti sebe", "samoubistv*", "samoubojstv*",
    "suicid*", "oduzm* sebi zivot", "oduze* sebi zivot", "oduzimanj* zivota", "sebi zivot",
    "dign* ruku na sebe", "dic* ruku na sebe", "digla ruku na sebe", "ruku na sebe",
    # not wanting to live
    "ne zelim vise da zivim", "ne zelim da zivim", "ne zelim zivjeti", "ne zelim ziveti",
    "ne zelim vise zivjeti", "ne zelim vise ziveti", "ne zelim vise da zivim", "necu vise da zivim",
    "necu da zivim", "necu vise zivjeti", "necu vise ziveti", "ne mogu vise da zivim",
    "ne mogu vise zivjeti", "ne mogu vise ziveti", "ne zelim biti ziva", "ne zelim da budem ziva",
    "nema smisla zivjeti", "nema smisla ziveti", "nema smisla da zivim", "nema smisla vise zivjeti",
    "nema smisla vise ziveti", "zivot nema smisla", "zivot mi nema smisla", "moj zivot nema smisla",
    "nema svrhe da zivim", "nema svrhe zivjeti", "nema svrhe ziveti", "nema razloga da zivim",
    "nemam razloga da zivim", "nemam razlog da zivim", "nemam za sta da zivim", "nemam za sto zivjeti",
    # wanting to die / be gone
    "zelim da umrem", "hocu da umrem", "zelim umrijeti", "zelim umreti", "hocu umrijeti", "hocu umreti",
    "najradije bih umrla", "radije bih umrla", "radije bih bila mrtva", "voljela bih da umrem",
    "volela bih da umrem", "volela bih da sam mrtva", "voljela bih da sam mrtva", "da sam mrtva",
    "zelim biti mrtva", "bolje da sam mrtva", "bolje mrtva", "da nisam ziva", "bolje da nisam ziva",
    "bolje da me nema", "bolje bi bilo da me nema", "bilo bi bolje da me nema", "da me vise nema",
    "zelim da me nema", "hocu da me nema", "najbolje da me nema", "svima bolje da me nema",
    "lakse da me nema", "da nestanem", "zelim nestati", "zelim da nestanem", "hocu da nestanem",
    "da nestanem zauvijek", "da nestanem zauvek", "da se ne probudim", "ne probudim se",
    "da se nikad ne probudim", "nikad ne probudim", "da zaspim zauvijek", "da zaspim zauvek",
    "zaspim i ne probudim", "da zaspim i da se ne probudim",
    # ending it / methods
    "da okoncam sve", "okoncam sve", "sve okoncam", "okoncati sve", "da sve okoncam", "da prekinem sve",
    "da sve prekinem", "sve ovo prekinem", "stavim tacku na sve", "stavim tacku na zivot",
    "popijem sve tablete", "popijem tablete", "popila sve tablete", "popila bih sve tablete",
    "popijem sve lijekove", "popijem sve lekove", "sve tablete odjednom", "tablete odjednom",
    "da se otrujem", "otrujem se", "prerezem vene", "prerezati vene", "prerezala vene",
    "presjecem vene", "presecem vene", "isjecem vene", "isecem vene", "rezanje vena", "da se objesim",
    "da se obesim", "objesim se", "obesim se", "da skocim sa", "da skocim s", "skocim sa mosta",
    "skocim s mosta", "skocim sa zgrade", "skocim sa terase", "skocim pod", "bacim se pod",
    "bacim se sa", "bacim se s", "bacim pod voz", "bacim pod auto", "bacim pod kamion",
    # self-harm
    "=sijecem se", "=sjecem se", "=secem se", "=rezem se", "rezem ruke", "rezem se po", "rezala sam se",
    "sjekla sam se", "sekla sam se", "povredjujem se", "povrjedjujem se", "povrijedjujem se",
    "povredim se", "povrijedim se", "da se povredim", "da se povrijedim", "samopovred*", "samopovrjed*",
    "samopovrijed*", "nanesem sebi", "nanijela sebi", "nanela sebi", "nanosim sebi", "naudim sebi",
    "nauditi sebi", "da si naudim", "si naudim", "naudila sebi", "naskodim sebi",
    # harm to the baby (perinatal mental-health crisis)
    "povredim bebu", "povrijedim bebu", "naudim bebi", "da naudim bebi", "da povredim bebu",
    "da povrijedim bebu", "povredila bebu", "povrijedila bebu", "hurt my baby", "hurt the baby",
    "harm my baby", "harm the baby", "hurting my baby", "hurting the baby",
    # english
    "kill myself", "killing myself", "end my life", "end it all", "end everything", "ending it all",
    "take my own life", "take my life", "don t want to live", "do not want to live", "dont want to live",
    "want to die", "wanna die", "wish i was dead", "wish i were dead", "wish i d die", "better off dead",
    "better off without me", "no reason to live", "no point in living", "no point living",
    "not worth living", "life isn t worth", "life isnt worth", "hurt myself", "harm myself",
    "harming myself", "hurting myself", "cut myself", "cutting myself", "self harm", "overdose",
    "overdosing", "jump off", "hang myself", "not wake up", "never wake up", "disappear forever",
    "want to disappear", "end my own life", "ending my life", "ready to die", "rather be dead",
    "should just die", "stop existing", "cease to exist", "slit my wrists", "take all my pills",
    "swallow all", "all the pills", "all my pills",
)

# ---------------------------------------------------------------------------------------------
# violence_coercion
# ---------------------------------------------------------------------------------------------

VIOLENCE_TERMS: TermList = (
    # physical violence
    "tuce me", "me tuce", "tukao me", "tukla me", "istukao", "istukla", "pretukao", "pretukla",
    "pretuce", "prebio", "prebije", "prebija", "prebila", "bije me", "biju me", "udara me", "udari me",
    "udario me", "udarao me", "udarila me", "udaraju me", "me udara", "me udario", "me udari", "me udarao",
    "samara me", "osamario", "osamarila", "samarao me", "davi me", "davio me", "davila me", "zadavi",
    "udavi me", "gusio me", "gusila me", "vuce me za kosu", "cupa me", "cupao me", "gura me", "gurao me",
    "gurnuo me", "baca me", "bacio me", "baca stvari", "razbija stvari", "lomi stvari", "prijeti nozem",
    "preti nozem", "nozem mi", "fizicki nasil*", "fizicko nasilje", "fizicki zlostav*", "modric*",
    "masnic*", "plava mjesta", "plave mrlje", "podliv*",
    # sexual violence / coercion
    "silov*", "silom", "na silu", "prisil*", "primorav*", "primora*", "natjerao me", "naterao me",
    "natjerala me", "naterala me", "natjeraju me", "nateraju me", "tjera me da", "tera me da",
    "tjera me na", "tera me na", "tjerao me", "terao me", "iskoristio me", "iskoristila me",
    "iskoristio", "napastv*", "obljub*", "uznemirav*", "zlostavlj*", "maltretir*", "nasilj*", "nasiln*",
    "ucjenjuje me", "ucenjuje me", "ucjenjivanje", "ucenjivanje", "protiv moje volje",
    "bez moje volje", "bez mog pristanka", "bez pristanka", "nisam htjela", "nisam htela",
    "nisam pristala", "nisam zeljela", "nisam zelela", "nisam dala pristanak", "nisam se slozila",
    "nisam mogla da kazem ne", "nisam mogla reci ne", "pod prijetnjom", "pod pretnjom", "drogirao",
    "drogirana", "drogirali", "dok sam spavala", "dok sam bila pijana", "dok sam bila u nesvesti",
    "iskoristio sto sam", "ne mogu da kazem ne", "ne mogu reci ne", "ne smijem reci ne",
    "ne smem reci ne", "ne smijem da kazem ne", "ne smem da kazem ne",
    # threats, control, fear
    "prijeti mi", "preti mi", "prijetio mi", "pretio mi", "prijetnj*", "pretnj*", "prijeti da ce",
    "preti da ce", "prijeti da", "preti da", "ne da mi da izadjem", "ne da mi da izlazim",
    "ne da mi da idem", "ne pusta me", "ne pusta me da", "zakljucava me", "zakljucao me",
    "zakljuca me", "zabranjuje mi", "ne smijem izaci", "ne smem izaci", "ne smijem da izadjem",
    "ne smem da izadjem", "ne smijem nigdje", "ne smem nigde", "uzima mi novac", "uzima mi telefon",
    "oduzeo mi telefon", "kontrolise sve", "kontrolise me", "kontrolira me", "kontrolise sta",
    "prati me stalno", "spijunira me", "ponizava me", "vrijedja me", "vredja me", "vrijedja me stalno",
    "psuje me", "vice na mene stalno", "plasim ga se", "bojim ga se", "bojim se muza", "bojim se partnera",
    "bojim se decka", "bojim se za zivot", "strah me od muza", "strah me od njega", "strah me ga",
    "strah me od partnera", "strah me od decka", "bojim se da ce me", "ubice me", "ubit ce me",
    "da ce me ubiti", "prijeti da ce me ubiti", "preti da ce me ubiti", "sigurna kuca", "sigurne kuce",
    "sklonis*", "pobjegnem od njega", "pobegnem od njega", "pobjeci od njega", "pobeci od njega",
    "pobjegnem od muza", "pobegnem od muza", "nasilna veza", "nasilnoj vezi",
    # english
    "hits me", "hit me", "hitting me", "beats me", "beat me", "beating me", "beaten", "slaps me",
    "slapped me", "punched me", "punches me", "kicks me", "kicked me", "choked me", "chokes me",
    "choking me", "strangl*", "pushed me", "shoves me", "shoved me", "throws things", "threw things",
    "pulls my hair", "pulled my hair", "bruises", "bruised", "=raped", "=rape", "raping", "rapist",
    "forced me", "forces me", "forcing me", "forced sex", "forced to have sex", "made me have sex",
    "makes me have sex", "pressures me into", "pressured me into", "pressuring me", "against my will",
    "without my consent", "didn t consent", "did not consent", "didnt consent", "couldn t say no",
    "could not say no", "can t say no", "threatens me", "threatened me", "threatening me",
    "threatens to", "threatened to", "threats", "abuses me", "abused me", "abusing me", "abusive",
    "being abused", "domestic violence", "domestic abuse", "partner violence", "won t let me leave",
    "won t let me go", "wont let me leave", "doesn t let me leave", "won t let me out", "controls my",
    "controls me", "controlling", "takes my money", "takes my phone", "took my phone", "locks me",
    "locked me in", "afraid of him", "scared of him", "afraid of my husband", "scared of my husband",
    "scared of my partner", "afraid of my partner", "afraid of my boyfriend", "scared of my boyfriend",
    "fear for my life", "sexual assault", "sexually assaulted", "assaulted me", "assaults me",
    "molested", "molests", "molesting", "groped", "gropes", "harasses me", "harassed me", "harassing me",
    "coerced", "coerces", "coercing", "drugged", "while i was asleep", "while i was drunk",
    "safe house", "women s shelter", "shelter", "restraining order",
)

# ---------------------------------------------------------------------------------------------
# minor_sexual_adult
# ---------------------------------------------------------------------------------------------

MINOR_TERMS: TermList = (
    "maloljetn*", "maloletn*", "malodobn*", "malodobna", "nisam punoljetna", "nisam punoletna",
    "nisam punoljetan", "nisam punoletan", "nemam 18", "nemam jos 18", "nemam ni 18", "ispod 18",
    "mladja od 18", "mlada od 18", "idem u osnovnu", "osnovnu skolu", "osnovne skole", "osnovnoj skoli",
    "osmi razred", "sedmi razred", "deveti razred", "sesti razred", "peti razred", "osmog razreda",
    "sedmog razreda", "devetog razreda", "prvi srednje", "prvi razred srednje", "drugi srednje",
    "drugi razred srednje", "=minor", "a minor", "i m a minor", "i am a minor", "im a minor", "underage",
    "under 18", "under eighteen", "not 18 yet", "not yet 18", "still in school", "middle school",
    "8th grade", "9th grade", "7th grade", "eighth grade", "ninth grade", "seventh grade", "tenth grade",
    "10th grade",
)

# Stated own age 9-17. Units that make the number something else (days late, pills ...) are excluded.
MINOR_AGE_PATTERNS: tuple[str, ...] = (
    r"\b(?:imam|ja imam|imala sam|napunila sam|napunicu|napunit cu|napunila|punim|sam|cerka ima|kcerka ima|kci ima|sestra ima|drugarica ima|prijateljica ima|ona ima|on ima|brat ima) (1[0-7]|9)(?: i po)? ?(?:god\w*|g\b|gdn|godina|yrs?|years?)",
    r"\b(1[0-7]|9) ?(?:god\w*|g\b|gdn)\b(?! ?(?:star\w* (?:muskar|decko|momak|tip|lik|covj|cove)|stariji))",
    r"\b(?:imam|ja imam|imala sam|napunila sam|napunila|punim|cerka ima|kcerka ima|kci ima|sestra ima|drugarica ima|prijateljica ima|ona ima|on ima|brat ima) (1[0-7]|9)\b(?! ?(?:dan\w*|ned\w*|tjed\w*|sedmic\w*|mjes\w*|mes\w*|sat\w*|tabl\w*|pil\w*|kg|kil\w*|cm|puta|put|posto|%|godina (?:brak|veze|staza)|stepen\w*|cm|mm|ml|mg|komad\w*|djec\w*|dec\w*|dete|dijete|bebu|bebe|partner\w*|decka|momka|muz\w*))",
    r"\b(?:i m|i am|im|she is|she s|shes|my sister is|my friend is|my daughter is|he is|he s) (1[0-7]|9)\b(?! ?(?:weeks?|days?|months?|cm|kg|pounds?|lbs|hours?|minutes?|pills?|tablets?|years? (?:married|together|into)))",
    r"\b(1[0-7]|9) ?(?:years? old|yrs? old|yo|y o|year old girl|year old boy)\b",
    r"\b(?:only|just|turned|turning) (1[0-7]|9)\b(?! ?(?:weeks?|days?|months?|cm|kg|hours?|minutes?|pills?|tablets?|times?))",
    r"\b(?:tek|samo|napunila|napunicu|punim) (1[0-7]|9)\b(?! ?(?:dan\w*|ned\w*|tjed\w*|sedmic\w*|mjes\w*|mes\w*|sat\w*|tabl\w*|pil\w*|kg|kil\w*|cm|puta|put|posto))",
)

# Another person who is an adult (relation words, or a stated age of 18-69).
ADULT_RELATION_TERMS: TermList = (
    "stariji", "starijim", "starijeg", "starijom", "starija", "stariju", "starijem", "stariji muskarac",
    "stariji decko", "stariji momak", "stariji tip", "stariji lik", "puno stariji", "mnogo stariji",
    "dosta stariji", "odrasl*", "odrastao", "odrasli", "odrasla osoba", "odrastao muskarac",
    "covjek od", "covek od", "muskarac od", "muskarac ima", "muskarac koji ima", "muskarac star",
    "covjek star", "covek star", "ozenjen", "ozenjeni", "ozenjen muskarac", "ozenjenim", "nastavnik*",
    "nastavnic*", "profesor*", "ucitelj*", "trener*", "=ocuh", "=ocuha", "=ocuhom", "poocim", "poocima",
    "=komsija", "=komsiju", "=komsije", "=komsijom", "=susjed", "=susjeda", "=susjedom", "=sused", "=suseda",
    "=susedom", "=ujak", "=ujaka", "=ujakom", "=stric", "=strica", "=stricem", "=tetak", "=tetka", "=teca",
    "=tece", "=dajdza", "=dajdzu", "=amidza", "=amidzu", "=sef", "=sefa", "=sefom", "=gazda", "=gazdu",
    "poslodav*", "svestenik", "svecenik", "=hodza", "=hodzu", "=pop", "=popa", "=zet", "=kum", "=kuma",
    "rodjak", "rodjaka", "rodak", "rodaka", "rodjakom", "=tata", "=tatu", "=otac", "=oca", "=ocem", "=deda",
    "=djed", "=dedo", "=dido", "=dida", "=deka", "=djeda", "=dede", "mamin decko", "mamin momak",
    "mamin partner", "mamin muz", "majcin partner", "majcin decko", "majcin muz", "tatin prijatelj",
    "tatin drug", "prijatelj od tate", "ocev prijatelj", "drug od tate", "ocev drug", "porodicni prijatelj",
    "prijatelj porodice", "prijatelj od roditelja", "roditeljski prijatelj", "stanodavac", "gazdarica",
    "=teacher", "=teachers", "=coach", "stepfather", "stepdad", "step dad", "step father", "neighbor",
    "neighbour", "=uncle", "=boss", "=manager", "older man", "older guy", "older boyfriend", "much older",
    "way older", "grown man", "grown up", "=adult", "an adult", "my dad", "my father", "my grandfather",
    "my grandpa", "=cousin", "=priest", "=pastor", "=imam s", "my mom s boyfriend", "my mum s boyfriend",
    "mom s boyfriend", "mum s boyfriend", "mother s boyfriend", "my mom s husband", "family friend",
    "friend of my dad", "friend of my father", "dad s friend", "father s friend", "landlord",
    "married man", "an older", "a much older",
)
ADULT_AGE_PATTERNS: tuple[str, ...] = (
    r"\b(?:ima|je|od|star|stari|starog|decko ima|momak ima|on ima|partner ima|muz ima|muskarac od|covjek od|covek od|tip od|lik od|ima oko|ima nekih|ima preko|ima vise od) (1[89]|[2-6][0-9])(?: i po)? ?(?:god\w*|g\b|gdn|yrs?|years?)",
    r"\b(1[89]|[2-6][0-9]) ?godisnj\w*",
    r"\b(?:he s|he is|hes|she s|she is|boyfriend is|partner is|husband is|man is|guy is|man of|guy of|he s like|he is like|around|about|over|almost) (1[89]|[2-6][0-9])\b(?! ?(?:weeks?|days?|months?|cm|kg|pounds?|lbs|hours?|minutes?|pills?|tablets?))",
    r"\b(1[89]|[2-6][0-9]) ?(?:years? old|yrs? old|yo|y o|year old man|year old guy)\b",
)

# Any sexual / romantic framing (needed next to an adult-relation word).
SEXUAL_ANY_TERMS: TermList = (
    "=seks", "=seksa", "=seksu", "seksual*", "spolni odnos*", "polni odnos*", "=odnos", "=odnose", "=odnosi",
    "=odnosa", "spolno", "polno", "intimn*", "=spavala", "=spavam", "=spavao", "=spava", "=spavamo",
    "spavala sam sa", "spavala sam s", "spavam sa", "spavam s", "legla sa", "legla s", "u vezi sam",
    "u vezi", "=veza", "=vezi", "=vezu", "zabavljam se", "zabavljamo se", "hodam sa", "hodam s",
    "=decko", "=decka", "=deckom", "=momak", "=momka", "=momkom", "=partner", "=partnera", "=partnerom",
    "=dira", "=dirao", "=dirala", "diranje", "=dodiruje", "=dodirivao", "=dodirivala", "=dodiruju",
    "=pipa", "=pipao", "=pipka", "=pipkao", "=ljubi", "=ljubio", "=poljubio", "=ljubimo", "=ljubili",
    "=skinuo", "=skida", "=skinem", "=skine", "=gola", "=gole", "=goli", "=golu", "=gol", "gole slike",
    "golu sliku", "gole fotke", "golisave", "=slike", "=sliku", "=fotke", "=fotku", "=nudes", "=nude",
    "=naked", "=sex", "=sexual", "sexually", "=sleep", "=slept", "sleeping with", "sleep with",
    "touch*", "kiss*", "intimate", "grooming", "=dating", "relationship", "boyfriend", "=lover",
    "hook up", "hooked up", "hooking up", "make out", "made out", "undress*", "=porn", "pornograf*",
    "=kondom", "=kondoma", "=condom", "=condoms", "=trudna", "=zatrudnim", "=zatrudnila", "=pregnant",
    "pod nasim", "under the covers", "privatne dijelove", "privatne delove", "private parts",
    "medju noge", "medju nogama", "between my legs", "=penis", "=vagin*", "=grudi", "=sise", "=breasts",
    "=guzu", "=guza", "=zadnjicu",
)

# Another person performing a sexual act on the user (enough on its own, with minor context).
SEXUAL_CONTACT_BY_OTHER_TERMS: TermList = (
    "dira me", "dirao me", "dirala me", "diraju me", "me dira", "me dirao", "dodiruje me", "dodirivao me",
    "dodirivala me", "dodiruju me", "me dodiruje", "pipa me", "pipao me", "pipka me", "pipkao me",
    "me pipa", "ljubi me na silu", "ljubi me nasilu", "ljubi me iako", "poljubio me na silu",
    "natjerao me", "naterao me", "natjerala me", "naterala me", "prisiljava me", "prisilio me",
    "prisilila me", "primorava me", "tjera me na seks", "tera me na seks", "tjera me da spavam",
    "tera me da spavam", "trazi od mene seks", "trazi seks", "trazi da spavam", "trazi da spavamo",
    "hoce seks", "hoce da spavamo", "hoce da spava sa mnom", "hoce da spava samnom", "zeli seks",
    "zeli da spava sa mnom", "zeli da spavamo", "nagovara me na seks", "nagovara me da spavam",
    "nudi mi novac za", "nudi mi pare za", "daje mi novac da", "daje mi pare da", "placa mi da",
    "salje mi gole slike", "salje mi slike", "salje mi poruke", "trazi gole slike", "trazi mi gole",
    "trazi da mu posaljem", "trazi slike", "pokazuje mi", "pokazao mi", "pokazuje mi svoj",
    "skinuo me", "skida me", "skinuo mi", "svlaci me", "svukao me", "spavao sa mnom", "spava sa mnom",
    "spavao samnom", "spava samnom", "legao sa mnom", "legao samnom", "imao seks sa mnom",
    "imao odnos sa mnom", "imali smo seks", "imali smo odnos", "imali odnos", "imali seks",
    "ulazi mi u sobu", "ulazi u kupatilo", "gleda me dok se", "gleda me pod tusem", "snima me",
    "snimao me", "slika me", "slikao me", "touches me", "touched me", "touching me", "groped me",
    "kissed me", "kisses me", "makes me touch", "made me touch", "makes me have sex", "made me have sex",
    "wants to have sex with me", "wants sex", "asks me for sex", "asked me for sex", "asks me to sleep",
    "pressures me", "pressured me", "sends me nudes", "sent me nudes", "sends me pictures", "sent me pictures",
    "asks me for nudes", "asked me for nudes", "asks me for pictures", "asked for pictures", "wants pictures",
    "showed me his", "shows me his", "undressed me", "undresses me", "slept with me", "sleeps with me",
    "had sex with me", "we had sex", "we slept together", "offers me money", "offered me money",
    "pays me to", "gives me money to", "watches me", "films me", "filmed me", "recorded me",
    "comes into my room", "walks in on me", "forces me", "forced me",
)

# ---------------------------------------------------------------------------------------------
# Classifier training seeds (normalised text). Rules are the first line of defence; the
# classifier catches paraphrases that the rules miss.
# ---------------------------------------------------------------------------------------------

POSITIVE_SEEDS: dict[str, tuple[str, ...]] = {
    "bleeding_pregnancy": (
        "trudna sam i krvarim",
        "u drugom stanju sam i pojavila se krv",
        "trudna sam 12 nedelja i imam krvarenje sa ugruscima",
        "krvarim jako i natapam ulozak svakih sat vremena",
        "u 20 tjednu trudnoce krvarim i ne prestaje",
        "porodila sam se prije tjedan dana i krvarenje je sve jace",
        "nakon porodjaja krvarim puno i izlaze veliki komadi",
        "trudna i krv curi kao iz slavine",
        "obilno krvarenje u trudnoci sta da radim",
        "trudnoca 8 nedelja svjeze crveno krvarenje",
        "krvarim u trudnoci i boli me stomak",
        "i am pregnant and bleeding heavily",
        "bleeding a lot with clots two weeks after giving birth",
        "pregnant and soaking a pad every hour",
        "heavy bleeding in early pregnancy with clots",
        "krvarenje ne staje trudna sam",
        "trudnica sam i krvarim jace nego menstruacija",
        "nedavno rodila krv lije i ne staje",
        "krvarim obilno vec dva sata trudna sam",
        "krvava sluz i jako krvarenje u trudnoci",
        "izasao mi je veliki ugrusak krvi trudna sam",
        "krv mi tece niz noge trudna sam",
        "krvarenje sa bolovima u trudnoci 10 nedelja",
    ),
    "severe_abdominal_pain": (
        "imam uzasan bol u stomaku ne mogu da stojim",
        "nepodnosljiv bol u donjem dijelu trbuha",
        "ostar bol u stomaku s desne strane i vrti mi se",
        "savijam se od bolova u stomaku",
        "jaki bolovi u karlici ne mogu da hodam",
        "bol u trbuhu kao nozem ne mogu da se ispravim",
        "strasni grcevi u stomaku padam u nesvijest",
        "bol u donjem stomaku 10 od 10 placem",
        "probadajuci bol u jajniku ne mogu da trpim",
        "boli me stomak toliko jako da vristim",
        "najgori bol u zivotu u donjem delu stomaka",
        "severe abdominal pain cannot stand up",
        "sharp pain in my lower belly doubled over",
        "unbearable pain in my pelvis and i fainted",
        "worst stomach pain of my life on one side",
        "excruciating cramps in my abdomen can t walk",
        "bol u stomaku je nesnosan i hladan znoj me oblio",
        "jako me boli stomak s lijeve strane i pozlilo mi je",
        "boli me dolje tako jako da ne mogu da se pomjerim",
        "grcevi u stomaku su nepodnosljivi i sve jaci",
        "bol ispod rebara desno uzasan i povracam",
        "jak bol u preponi skoro sam pala u nesvest",
    ),
    "fever_pregnancy": (
        "trudna sam i imam temperaturu 39",
        "u trudnoci imam visoku temperaturu i jezu",
        "temperatura 38 5 trudna sam 30 nedelja",
        "trudnica groznica tresem se",
        "u drugom stanju sam dobila sam temperaturu 38 7",
        "trudna i gorim od temperature",
        "imam temperaturu preko 38 i trudna sam",
        "trudna sam i trese me groznica cijelu noc",
        "trudnoca 25 tjedana temperatura 39 2",
        "trudna sam temperatura mi ne pada ispod 38",
        "i m pregnant and have a fever of 39",
        "pregnant with chills and high temperature",
        "fever and shivering at 28 weeks pregnant",
        "pregnant running a temperature of 38 5",
        "high fever in pregnancy what to do",
        "trudna sam drhtavica i temperatura 38 4",
        "u trudnoci sam dobila vrucicu 39",
        "temperatura 40 u trudnoci sva gorim",
        "trudna sam imam temperaturu i jezu cijeli dan",
        "trudna skocila mi je temperatura na 38 8",
    ),
    "preeclampsia": (
        "trudna sam i imam jaku glavobolju koja ne prolazi",
        "u trudnoci mi se zamaglio vid",
        "trudna i vidim tackice pred ocima",
        "naglo mi je oteklo lice i ruke trudna sam",
        "trudnoca 34 nedelje glava mi puca",
        "u trudnoci vidim zvjezdice i boli me glava",
        "trudna sam i otekle su mi ruke preko noci",
        "trudna sam i mutno vidim i glava me jako boli",
        "pregnant with a severe headache and blurred vision",
        "sudden swelling of my face and hands at 32 weeks pregnant",
        "pregnant and seeing flashing lights",
        "pregnant terrible headache that won t go away",
        "pregnant my face is puffy and my vision is blurry",
        "trudna sam i glavobolja mi ne prolazi ni od cega",
        "u trudnoci mi oticu prsti i ne mogu skinuti prsten",
        "trudna sam i lice mi je odjednom oteklo",
        "trudna sam i pred ocima mi sijeva",
        "u trudnoci imam strasnu glavobolju i mucninu",
        "trudna i duplo vidim",
        "trudna 36 nedelja otekle ruke lice i glavobolja",
        "pregnant and my hands swelled up suddenly",
    ),
    "reduced_fetal_movement": (
        "beba se ne mrda od jutros",
        "ne osjecam pokrete bebe cijeli dan",
        "beba se manje mrda nego juce",
        "trudna sam 30 nedelja i ne osecam bebu",
        "dijete se ne mice vec satima",
        "beba se pomjera mnogo manje nego inace",
        "nisam osjetila bebu od sinoc",
        "nema pokreta bebe od juce",
        "beba je previse mirna cijeli dan",
        "beba je prestala da se mrda",
        "pokreti bebe su mnogo slabiji",
        "baby hasn t moved all day",
        "i can t feel my baby moving",
        "fewer movements than usual at 34 weeks",
        "baby is not kicking like before",
        "my baby stopped moving since last night",
        "baby has gone very quiet today",
        "beba se jedva mrda danas",
        "trudna 36 nedelja beba skoro da se ne mice",
        "ne osecam da se beba mrda vec dva dana",
        "beba se ne rita vise kao prije",
        "u 32 tjednu beba se jedva pomakne",
    ),
    "suicidal_ideation": (
        "ne zelim vise da zivim",
        "bolje da me nema",
        "zelim da se ubijem",
        "nema smisla zivjeti",
        "razmisljam o samoubistvu",
        "svima bi bilo lakse bez mene",
        "ne vidim izlaz sve je crno",
        "nemam snage za zivot vise",
        "zelim da umrem",
        "da zaspim i da se nikad ne probudim",
        "mislim da bi svima bilo bolje bez mene",
        "ne vidim smisao u icemu vise",
        "ne mogu vise ovako sve je besmisleno",
        "nema me vise svima ce biti lakse",
        "planiram da popijem sve tablete",
        "sve bih prekinula zauvijek",
        "ne mogu vise ovako ne zelim se probuditi",
        "hocu da nestanem zauvijek",
        "rezem se da bih osjetila nesto",
        "i want to kill myself",
        "i don t want to live anymore",
        "everyone would be better off without me",
        "i wish i could just disappear forever",
        "i can t go on there is no way out",
        "i have been thinking about ending it all",
        "no point in living anymore",
        "i want to hurt myself",
        "i feel like ending my life",
        "umorna sam od svega i zelim da sve prestane zauvijek",
        "ne zelim biti tu vise svima sam teret",
        "svima sam teret bolje da nestanem",
        "nemam vise razloga da ostanem ovdje",
    ),
    "violence_coercion": (
        "muz me tuce",
        "decko me udara kad se napije",
        "partner me prisiljava na seks",
        "silovao me je",
        "prijeti mi da ce me ubiti ako odem",
        "zlostavlja me i ne da mi da izadjem iz kuce",
        "tjera me da spavam s njim iako necu",
        "udario me je u stomak trudna sam",
        "muz me maltretira i ponizava svaki dan",
        "bojim se muza on je nasilan",
        "primorao me na odnos bez pristanka",
        "natjerao me na seks nisam htjela",
        "he hits me when he is angry",
        "my husband beats me",
        "he forced me to have sex",
        "i was raped",
        "my partner threatens me and controls my money",
        "my boyfriend won t let me leave the house",
        "he pressures me into sex when i say no",
        "my partner is abusive and i am scared",
        "muz me je istukao i prijeti mi",
        "uzeo mi je telefon i ne da mi da idem nigdje",
        "svekar me dira i prijeti da nikom ne kazem",
        "muz me davio sinoc",
        "partner me tjera na seks dok sam trudna",
        "on me bije pred djecom",
        "drogirao me i iskoristio",
        "prisilio me iako sam rekla ne",
        "ne smijem reci ne jer ce me istuci",
    ),
    "minor_sexual_adult": (
        "imam 14 godina i stariji muskarac me dira",
        "imam 15 godina decko mi ima 28 godina i hoce seks",
        "maloljetna sam i spavala sam sa odraslim muskarcem",
        "imam 13 godina ocuh me pipa nocu",
        "imam 16 godina i u vezi sam sa profesorom",
        "moj nastavnik me ljubi imam 15",
        "imam 12 god i komsija mi pokazuje svoj",
        "trener trazi od mene gole slike imam 14",
        "imam 15 godina a muskarac od 35 godina hoce da spavamo",
        "ujak me dira dok spavam imam 11 godina",
        "imam 16 i stariji tip mi nudi novac za seks",
        "i am 14 and my teacher touches me",
        "i m 15 and my boyfriend is 27",
        "i am 13 and an older man wants to have sex with me",
        "my stepdad comes into my room at night i am 12",
        "i m 16 and a grown man sends me nudes",
        "a 30 year old man wants to sleep with me i m 15",
        "imam 14 godina decko ima 24 i imali smo seks",
        "tatin prijatelj me pipa imam 13 godina",
        "imam 15 godina sef mi se nabacuje i dira me",
        "maloletna sam a on ima 30 godina i spavamo zajedno",
        "imam 16 godina i stariji muskarac mi salje gole slike",
        "imam 14 godina a moj momak ima 22 godine i trazi seks",
        "imam 15 godina i spavala sam sa starijim muskarcem",
        "imam 13 godina komsija me dira i ne smijem nikome reci",
    ),
}

NEGATIVE_SEEDS: tuple[str, ...] = (
    # contraception
    "kako se koristi pilula za kontracepciju",
    "zaboravila sam da popijem pilulu sta da radim",
    "da li kondom stiti od svih polnih bolesti",
    "koliko kosta spirala i gdje mogu da je stavim",
    "koja je najbolja kontracepcija za tinejdzere",
    "da li pilula za dan poslije djeluje nakon 3 dana",
    "da li kontracepcija utice na plodnost kasnije",
    "koje su nuspojave hormonske kontracepcije",
    "moze li se zatrudnjeti uz pilule",
    "koliko dugo traje zastita od injekcije za kontracepciju",
    "koji kontraceptiv je najsigurniji",
    "da li mogu dobiti kontracepciju bez roditelja",
    "pukao je kondom sta sad",
    "kako radi hitna kontracepcija",
    "da li je implant bolan kad se stavlja",
    "can i get the pill without my parents knowing",
    "how effective is the morning after pill",
    "what are the side effects of the iud",
    "does the condom protect against hiv",
    "how do i use a condom correctly",
    # pregnancy (benign)
    "kada mogu da uradim test za trudnocu",
    "koji su prvi znaci trudnoce",
    "da li je normalno da me boli stomak u ranoj trudnoci",
    "koliko kilograma je normalno dobiti u trudnoci",
    "da li smijem da pijem kafu u trudnoci",
    "koja je normalna temperatura u trudnoci",
    "kada se osjete prvi pokreti bebe",
    "beba se puno mrda da li je to normalno",
    "beba se jako mrda nocu",
    "koliko ultrazvuka se radi u trudnoci",
    "koja hrana je dobra za trudnice",
    "da li su otekle noge normalne u trudnoci",
    "da li je blaga glavobolja normalna u trudnoci",
    "sta je folna kiselina i kada se uzima",
    "da li je normalno da imam mucninu ujutru u trudnoci",
    "bazalna temperatura mi je 37 da li sam trudna",
    "koliko traje trudnoca u nedeljama",
    "da li mogu da vjezbam u trudnoci",
    "kako da znam da li sam trudna prije testa",
    "koje preglede trudnica treba da obavi",
    "imam 38 godina i prvi put sam trudna da li je to rizicno",
    "u 38 nedelji sam trudnoce kada da idem u bolnicu",
    "osjecam udarce bebe da li je to normalno",
    "beba udara jako da li je to dobro",
    "da li beba cuje muziku u stomaku",
    "mozete li mi reci kako izgleda pregled kod ginekologa u trudnoci",
    "sta je prenatalni skrining",
    "when can i take a pregnancy test",
    "what are the early signs of pregnancy",
    "is mild cramping normal in early pregnancy",
    "how much weight should i gain in pregnancy",
    "is it normal for my feet to swell when pregnant",
    "what foods should i avoid while pregnant",
    "how many weeks is a full term pregnancy",
    "my baby moves a lot at night is that normal",
    # period / menstruation
    "bole me grcevi tokom menstruacije sta pomaze",
    "menstruacija mi kasni 5 dana",
    "imam krvarenje izmedju ciklusa da li je to normalno",
    "koliko traje normalna menstruacija",
    "koliko krvi je normalno izgubiti za vrijeme menstruacije",
    "imam obilnu menstruaciju svaki mjesec da li je to normalno",
    "da li je normalno da me boli stomak pred menstruaciju",
    "prvi put imam menstruaciju sta da koristim",
    "neredovan ciklus kod tinejdzerki",
    "sta je pms i kako se osjeca",
    "menstruacija mi je kratka i slaba",
    "jaki grcevi tokom menstruacije sta pomaze",
    "da li je normalno da imam ugruske tokom menstruacije",
    "zasto mi menstruacija kasni ako nisam trudna",
    "bazalna temperatura i ovulacija kako se mjeri",
    "my period is late by a week",
    "how long does a normal period last",
    "i have spotting between periods is it normal",
    "period cramps what helps",
    "why is my period so heavy every month",
    # sti / infections
    "koji su simptomi klamidije",
    "da li se hpv moze izlijeciti",
    "imam iscjedak i svrab da li je to infekcija",
    "gdje mogu da se testiram na hiv anonimno",
    "da li je herpes opasan u trudnoci",
    "kako se prenosi sifilis",
    "da li vaginalna infekcija moze sama proci",
    "peckanje pri mokrenju i krv u urinu da li je to infekcija",
    "da li treba testirati partnera na polne bolesti",
    "what are the symptoms of chlamydia",
    "where can i get tested for stis",
    "is a yellow discharge a sign of infection",
    # postnatal
    "koliko traje krvarenje poslije porodjaja",
    "normalno krvarenje nakon poroda koliko dugo",
    "da li je normalno da me bole grudi dok dojim",
    "kako da znam da beba dobija dovoljno mlijeka",
    "kada se vraca menstruacija nakon porodjaja",
    "beba ima temperaturu 37 5 da li da brinem",
    "beba se budi svaki sat nocu da li je to normalno",
    "kako da pomognem bebi kad ima grceve",
    "koliko dugo traju lohije poslije poroda",
    "how long does bleeding last after giving birth",
    "is it normal to feel sad a few days after birth",
    # mental health (non-crisis)
    "osjecam se tuzno nakon porodjaja da li je to normalno",
    "stalno sam umorna i nervozna u trudnoci",
    "kako da se nosim sa stresom u trudnoci",
    "imam anksioznost prije porodjaja sta da radim",
    "bebi bluz koliko traje",
    "i feel anxious about giving birth",
    "feeling low after having a baby is it normal",
    # other overlapping vocabulary
    "krv iz nosa u trudnoci da li je to normalno",
    "trudna sam i curi mi krv iz nosa",
    "krvare mi desni dok perem zube u trudnoci",
    "boli me glava poslije porodjaja da li mogu da uzmem nesto",
    "dete ima temperaturu 38 i kasalj sta da radim",
    "koliko je normalno da beba spava",
    "imam 25 godina i decko ima 27 kad je najbolje vrijeme za bebu",
    "udata sam 5 godina i pokusavamo da dobijemo bebu",
    "radila sam test i pozitivan je sta sad",
    "sjecam se da mi je ljekar rekao da uzimam folnu kiselinu",
    "muz i ja planiramo bebu koje preglede da uradimo",
    "kako da razgovaram sa partnerom o kontracepciji",
    "moj decko ne zeli da koristi kondom kako da ga ubijedim",
    "moj momak ima 17 a ja 16 da li smijemo da koristimo kondom",
    "imam 16 godina i zanima me kako radi pilula",
    "imam 15 godina da li je normalno da mi kasni menstruacija",
    "imam 14 godina i jos nemam menstruaciju",
    "stariji brat kaze da je spirala opasna da li je to tacno",
    "profesorica biologije je rekla da pilula stiti od svega je li to istina",
    "da li je normalno da osjecam pritisak u stomaku u trudnoci",
    "osjecam zatezanje u stomaku u 30 nedelji trudnoce",
    "bol u ledjima u trudnoci kako olaksati",
    "prosirene vene u trudnoci sta pomaze",
    "trudna sam i boli me glava od vrucine",
    "beba udara i rita se cijeli dan da li je to normalno",
    "tata me vozi na preglede svaki mjesec koliko pregleda treba",
    "kada beba pocinje da se mrda u trudnoci",
    "pilule za temperaturu u trudnoci da li su dozvoljene",
    "normalna temperatura kod bebe koliko iznosi",
    "koliko je normalna tjelesna temperatura u trudnoci",
    "krv u stolici u trudnoci da li su to hemoroidi",
    "blago krvarenje desni u trudnoci",
    "how do i talk to my partner about contraception",
    "i am 16 and want to know how the pill works",
    "is it normal to have a headache in the first trimester",
    "my nose bleeds in pregnancy is it normal",
)
