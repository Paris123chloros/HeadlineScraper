"""Reviewable English cues, never claim verification or automatic identity resolution."""

import re

from motorsport_research.storage.repository import normalized_alias

RULES_VERSION = "article-rules:1"
CHAMPIONSHIPS = {
    "F1": r"\b(?:F1|Formula\s*(?:1|One))\b",
    "WEC": r"\b(?:WEC|World Endurance Championship)\b",
    "WRC": r"\b(?:WRC|World Rally Championship)\b",
    "DTM": r"\b(?:DTM|Deutsche Tourenwagen Masters)\b",
}
TOPICS = {
    "race": r"\b(?:race|racing|rally|rallies|qualifying|practice|sprint|podium|"
    r"grand prix|classification|standings|championship|lap|laps)\b",
    "penalties": r"\b(?:penalt\w*|sanction\w*|disqualif\w*|stewards?|appeal\w*)\b",
    "contracts": r"\b(?:contracts?|sign(?:ed|ing|ings)|re-sign\w*|deal|"
    r"negotiat\w*|driver market)\b",
    "driver-news": r"\b(?:driver\w*|co-driver\w*|injur\w*|recover\w*|retirement)\b",
    "team-news": r"\b(?:teams?|manufacturer\w*|sponsor\w*|power unit|engine|line-up|lineup)\b",
    "regulations": r"\b(?:regulat\w*|rules?|safety|technical directive|governance)\b",
    "calendar": r"\b(?:calendars?|schedule\w*|postpon\w*|cancel\w*)\b",
    "controversies": r"\b(?:scandal\w*|controvers\w*|cheat\w*|corrupt\w*|misconduct|"
    r"manipulat\w*|rule breach\w*|financial breach\w*|allegation\w*|"
    r"accus\w*|cost cap|governance dispute\w*)\b",
    "investigations": r"\b(?:investigat\w*|inquiry|inquiries)\b",
    "sport-news": r"\b(?:motorsport|motor sport|race|racing|rally|driver|championship|"
    r"paddock|circuit|FIA)\b",
}
CUES = {
    "rumor": r"\b(?:rumou?r\w*|reportedly|unconfirmed|sources say|could sign|may join)\b",
    "opinion": r"\b(?:opinion|commentary|editorial|column|analysis)\b",
    "allegation": r"\b(?:alleg\w*|accus\w*|suspect\w*)\b",
    "response": r"\b(?:den(?:y|ies|ied|ial)|reject\w* allegations|response|respond\w*)\b",
    "investigation": TOPICS["investigations"],
    "finding": r"\b(?:findings?|found guilty|cleared|exonerat\w*)\b",
    "decision": r"\b(?:decision|sanction\w*|penalt\w*|overturned)\b",
    "correction": r"\b(?:correction|corrected|retract\w*|amended)\b",
}
# These are name mentions. Database aliases supply identities and retain ambiguity.
NAMES = (
    "Max Verstappen",
    "Lewis Hamilton",
    "Charles Leclerc",
    "Lando Norris",
    "Oscar Piastri",
    "Carlos Sainz",
    "Fernando Alonso",
    "George Russell",
    "Sébastien Ogier",
    "Thierry Neuville",
    "Kalle Rovanperä",
    "Oliver Solberg",
    "Sébastien Buemi",
    "Brendon Hartley",
    "Ryo Hirakawa",
    "Kevin Estre",
    "René Rast",
    "Marco Wittmann",
    "Mirko Bortolotti",
    "Thomas Preining",
    "FIA",
    "Ferrari",
    "McLaren",
    "Red Bull",
    "Toyota",
    "Porsche",
    "Hyundai",
    "BMW",
)


def _matches(pattern, title, body):
    return [
        {
            "field": field,
            "quote": match.group(),
            "start_offset": match.start(),
            "end_offset": match.end(),
        }
        for field, text in (("title", title), ("body", body))
        for match in re.finditer(pattern, text, flags=re.I)
    ][:100]


def classify(article, source, aliases):
    title, body = article["title"], article["body"]
    championships = [
        {"championship": name, "basis": "text_mention", "evidence": evidence}
        for name, pattern in CHAMPIONSHIPS.items()
        if (evidence := _matches(pattern, title, body))
    ]
    topics = [
        {"topic": name, "evidence": evidence}
        for name, pattern in TOPICS.items()
        if (evidence := _matches(pattern, title, body))
    ]
    fia = _matches(r"\b(?:FIA|Fédération Internationale de l.Automobile)\b", title, body)
    official_fia = source["kind"] == "official" and source["url"].split("/")[2] == "www.fia.com"
    if official_fia:
        topics.append(
            {
                "topic": "fia-announcements",
                "evidence": fia,
                "basis": "reviewed_publisher_attribution",
            }
        )
    cues = [
        {"label": name, "evidence": evidence}
        for name, pattern in CUES.items()
        if (evidence := _matches(pattern, title, body))
    ]
    # Genre terms anywhere in the body are retained as cues; only title/publisher
    # genre metadata labels the entire article as opinion.
    genre_text = title + " " + " ".join(article["genre_metadata"])
    labels = []
    if re.search(CUES["opinion"], genre_text, re.I):
        labels.append("opinion")
    if any(cue["label"] == "rumor" for cue in cues):
        labels.append("rumor_reporting")
    if not labels:
        labels.append("reporting")
    entities = []
    names = sorted({normalized_alias(name) for name in NAMES} | set(aliases))
    if len(names) > 10_000:
        raise ValueError("Entity hint registry exceeds 10000 aliases")
    for name in names:
        if len(name) < 3:
            continue
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(word) for word in name.split()) + r"(?!\w)"
        if evidence := _matches(pattern, title, body):
            candidates = aliases.get(name, [])
            identities = sorted({candidate["entity_id"] for candidate in candidates})
            entities.append(
                {
                    "mention": name,
                    "evidence": evidence,
                    "candidates": candidates,
                    "status": "unresolved"
                    if not identities
                    else "unique_candidate"
                    if len(identities) == 1
                    else "ambiguous",
                }
            )
    topic_names = {topic["topic"] for topic in topics}
    contract_cues = [
        {"label": label, "evidence": evidence}
        for label, pattern in {
            "signing_report": r"\b(?:signed|re-signed|signs|contract announced)\b",
            "negotiation_report": r"\b(?:negotiat\w*|talks|discussions)\b",
            "uncertain_future": r"\b(?:unconfirmed|undecided|could sign|may join)\b",
        }.items()
        if "contracts" in topic_names and (evidence := _matches(pattern, title, body))
    ]
    relevant = (bool(championships) and bool(topic_names - {"sport-news"})) or official_fia
    return {
        "relevance": {
            "status": "relevant" if relevant else "irrelevant",
            "reasons": (
                ["tracked championship mention and sporting topic"]
                if championships and relevant
                else []
            )
            + (["reviewed FIA publisher"] if official_fia else []),
            "rules_version": RULES_VERSION,
        },
        "championship_hints": championships,
        "topics": topics,
        "labels": labels,
        "procedural_cues": cues,
        "contract_cues": contract_cues,
        "entity_hints": entities,
        "warning": "Hints describe published wording; identity, applicability and truth "
        "remain unassessed. Procedural cues are not case findings.",
    }
