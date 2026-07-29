#!/usr/bin/env python3
"""Einmalig: Prioritäten anhand der Relevanz in der Musikwelt setzen.

A = Major Acts mit hohem News-Aufkommen (aktiv tourend, Medien-Dauerpräsenz,
    oder deutsche Ikonen mit NDR-1-MV-Relevanz). Ziel: ~30–35 Acts.
B = Etablierte, bekannte Künstler mit solidem Wiedererkennungswert in der
    Zielgruppe 30–60, aber weniger aktuellem News-Aufkommen.
C = Katalog-Acts, One-Hit-Wonder, Nischen-Künstler.
"""

import sqlite3
from config import DB_PATH

# --- A-Priorität: Major Acts, hohe News-Relevanz ---
PRIO_A = {
    # International — aktiv/legendär, hohes Medieninteresse
    "a-ha",
    "ABBA",
    "Adele",
    "Beyoncé",
    "Bruce Springsteen",
    "Bruno Mars",
    "Bryan Adams",
    "Coldplay",
    "Depeche Mode",
    "Ed Sheeran",
    "Elton John",
    "Fleetwood Mac",
    "Lady Gaga",
    "Madonna",
    "P!nk",
    "Phil Collins",
    "Queen",
    "Rihanna",
    "Robbie Williams",
    "Rod Stewart",
    "Shakira",
    "Taylor Swift",
    "The Rolling Stones",
    # Deutsch — Ikonen / NDR-1-Kernzielgruppe
    "Adel Tawil",
    "Die Ärzte",
    "Herbert Grönemeyer",
    "Johannes Oerding",
    "Max Giesinger",
    "Nena",
    "Peter Maffay",
    "Rea Garvey",
    "Santiano",
    "Silbermond",
    "Udo Lindenberg",
    "Westernhagen",
}

# --- B-Priorität: bekannt, solide Basis, weniger aktuell ---
PRIO_B = {
    # International Classic
    "Aerosmith",
    "Anastacia",
    "Bachman-Turner Overdrive",
    "Barbra Streisand",
    "Barry White",
    "Bee Gees",
    "Billy Joel",
    "Blondie",
    "Bob Dylan",
    "Bob Marley",
    "Boney M.",
    "Bonnie Tyler",
    "Cher",
    "Chicago",
    "Chris Rea",
    "Cliff Richard",
    "Creedence Clearwater Revival",
    "Culture Club",
    "Cyndi Lauper",
    "Céline Dion",
    "David Bowie",
    "Diana Ross",
    "Dire Straits",
    "Dolly Parton",
    "Duran Duran",
    "Dusty Springfield",
    "Eagles",
    "Electric Light Orchestra",
    "Elvis Presley",
    "Erasure",
    "Eurythmics",
    "Europe",
    "Falco",
    "Foreigner",
    "Frank Sinatra",
    "Freddie Mercury",
    "Genesis",
    "Gloria Gaynor",
    "Hall & Oates",
    "Heart",
    "Huey Lewis & The News",
    "Imagine Dragons",
    "INXS",
    "James Blunt",
    "Janet Jackson",
    "Jennifer Lopez",
    "Joe Cocker",
    "John Legend",
    "KC And The Sunshine Band",
    "Kenny Rogers",
    "Kim Wilde",
    "Kool & The Gang",
    "Kylie Minogue",
    "Lionel Richie",
    "Michael Jackson",
    "Miley Cyrus",
    "Mike Oldfield",
    "Nelly Furtado",
    "Olivia Newton-John",
    "Paul McCartney",
    "Pat Benatar",
    "Prince & The Revolution",
    "R.E.M.",
    "Rick Astley",
    "Roxette",
    "Santana",
    "Shania Twain",
    "Shawn Mendes",
    "Simon & Garfunkel",
    "Smokie",
    "Spice Girls",
    "Status Quo",
    "Stevie Wonder",
    "Supertramp",
    "Suzanne Vega",
    "Tears For Fears",
    "The Animals",
    "The Beach Boys",
    "The Beatles",
    "The Cars",
    "The Cure",
    "The Doors",
    "The Human League",
    "The Killers",
    "The Mamas And The Papas",
    "The Police",
    "The Supremes",
    "The Weeknd",
    "Tina Turner",
    "Tom Petty",
    "Tracy Chapman",
    "UB40",
    "Van Morrison",
    "Wham!",
    # Deutsch — bekannt, weniger aktuell
    "Alphaville",
    "Andreas Bourani",
    "Annett Louisan",
    "Camouflage",
    "Clueso",
    "Die Prinzen",
    "Felix Jaehn",
    "Frida Gold",
    "Gentleman",
    "Heinz Rudolf Kunze",
    "Ich + Ich",
    "Joris",
    "Juli",
    "Kamrad",
    "Laith Al-Deen",
    "Michael Patrick Kelly",
    "Michael Schulte",
    "Münchener Freiheit",
    "Namika",
    "Nico Santos",
    "Peter Fox",
    "Peter Schilling",
    "Philipp Dittberner",
    "Puhdys",
    "Revolverheld",
    "Rosenstolz",
    "Sandra",
    "Silly",
    "The BossHoss",
    "Wincent Weiss",
    "Zoe Wees",
    # International modern — bekannt
    "Amy Macdonald",
    "Charlie Puth",
    "David Guetta",
    "Enrique Iglesias",
    "Meghan Trainor",
    "Passenger",
    "Rita Ora",
    "The Chainsmokers",
    "The Lumineers",
    "Train",
}


def run():
    conn = sqlite3.connect(DB_PATH)

    a_found, b_found = 0, 0
    for name in PRIO_A:
        cur = conn.execute(
            "UPDATE kuenstler SET prioritaet = 'A' WHERE name = ? COLLATE NOCASE",
            (name,))
        a_found += cur.rowcount
    for name in PRIO_B:
        cur = conn.execute(
            "UPDATE kuenstler SET prioritaet = 'B' WHERE name = ? COLLATE NOCASE",
            (name,))
        b_found += cur.rowcount

    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM kuenstler").fetchone()[0]
    counts = {}
    for row in conn.execute("SELECT prioritaet, COUNT(*) FROM kuenstler GROUP BY prioritaet"):
        counts[row[0]] = row[1]

    conn.close()

    a_missing = [n for n in PRIO_A if n not in {n for n in PRIO_A}]
    print(f"Prioritäten gesetzt ({total} Künstler gesamt):")
    print(f"  A: {counts.get('A', 0)} (zugewiesen: {a_found}/{len(PRIO_A)})")
    print(f"  B: {counts.get('B', 0)} (zugewiesen: {b_found}/{len(PRIO_B)})")
    print(f"  C: {counts.get('C', 0)}")

    if a_found < len(PRIO_A):
        print(f"\n  ⚠ {len(PRIO_A) - a_found} A-Künstler nicht in DB gefunden")
    if b_found < len(PRIO_B):
        print(f"  ⚠ {len(PRIO_B) - b_found} B-Künstler nicht in DB gefunden")


if __name__ == "__main__":
    run()
