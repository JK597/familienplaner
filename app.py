import os
import sqlite3
import json
import base64
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    request,
    redirect,
    session,
    render_template,
    send_from_directory,
    jsonify
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


try:
    from pywebpush import (
        webpush,
        WebPushException
    )
except ImportError:
    webpush = None
    WebPushException = Exception


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "nur-fuer-lokale-entwicklung"
)

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "1234"
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL"
)

VAPID_PUBLIC_KEY = os.environ.get(
    "VAPID_PUBLIC_KEY",
    ""
).strip()

VAPID_PRIVATE_KEY_B64 = os.environ.get(
    "VAPID_PRIVATE_KEY_B64",
    ""
).strip()

VAPID_SUBJECT = os.environ.get(
    "VAPID_SUBJECT",
    "https://familienplaner-zbwi.onrender.com"
).strip()


REMINDER_SECRET = os.environ.get(
    "REMINDER_SECRET",
    ""
).strip()


# ============================================================
# ZEIT
# ============================================================

def jetzt():
    return datetime.now(
        ZoneInfo("Europe/Berlin")
    )


def heute():
    return jetzt().date()


def datum_lesen(wert):

    if isinstance(wert, date):
        return wert

    return date.fromisoformat(
        str(wert)
    )


def aktueller_periodenstart(
    reset_tag,
    bezugsdatum=None
):

    if bezugsdatum is None:
        bezugsdatum = heute()

    reset_tag = max(
        1,
        min(
            28,
            int(reset_tag)
        )
    )

    if bezugsdatum.day >= reset_tag:

        return date(
            bezugsdatum.year,
            bezugsdatum.month,
            reset_tag
        )

    jahr = bezugsdatum.year
    monat = bezugsdatum.month - 1

    if monat == 0:
        monat = 12
        jahr -= 1

    return date(
        jahr,
        monat,
        reset_tag
    )


def naechster_periodenstart(
    periodenstart,
    reset_tag
):

    reset_tag = max(
        1,
        min(
            28,
            int(reset_tag)
        )
    )

    jahr = periodenstart.year
    monat = periodenstart.month + 1

    if monat == 13:
        monat = 1
        jahr += 1

    return date(
        jahr,
        monat,
        reset_tag
    )


# ============================================================
# DATENBANK
# ============================================================

def postgres_verwenden():
    return bool(DATABASE_URL)


def datenbank():

    if postgres_verwenden():

        if psycopg2 is None:
            raise RuntimeError(
                "psycopg2 fehlt."
            )

        return psycopg2.connect(
            DATABASE_URL
        )

    db = sqlite3.connect(
        "users.db"
    )

    db.row_factory = sqlite3.Row

    db.execute(
        "PRAGMA foreign_keys = ON"
    )

    return db


def query_einen(
    sql_postgres,
    sql_sqlite,
    werte=()
):

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor(
                cursor_factory=
                psycopg2.extras.RealDictCursor
            )

            cursor.execute(
                sql_postgres,
                werte
            )

            ergebnis = cursor.fetchone()

            cursor.close()

        else:

            ergebnis = db.execute(
                sql_sqlite,
                werte
            ).fetchone()

        return ergebnis

    finally:
        db.close()


def query_alle(
    sql_postgres,
    sql_sqlite,
    werte=()
):

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor(
                cursor_factory=
                psycopg2.extras.RealDictCursor
            )

            cursor.execute(
                sql_postgres,
                werte
            )

            ergebnis = cursor.fetchall()

            cursor.close()

        else:

            ergebnis = db.execute(
                sql_sqlite,
                werte
            ).fetchall()

        return ergebnis

    finally:
        db.close()


def execute_query(
    sql_postgres,
    sql_sqlite,
    werte=()
):

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                sql_postgres,
                werte
            )

            cursor.close()

        else:

            db.execute(
                sql_sqlite,
                werte
            )

        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()


# ============================================================
# DATENBANKTABELLEN
# ============================================================

def datenbank_erstellen():

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS benutzer
                (
                    id SERIAL PRIMARY KEY,
                    benutzername VARCHAR(100) UNIQUE NOT NULL,
                    passwort TEXT NOT NULL,
                    rolle VARCHAR(50) NOT NULL DEFAULT 'benutzer',
                    passwort_muss_geaendert BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)

            cursor.execute("""
                ALTER TABLE benutzer
                ADD COLUMN IF NOT EXISTS
                passwort_muss_geaendert
                BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS finanz_einstellungen
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER UNIQUE NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    standard_budget NUMERIC(12,2)
                        NOT NULL DEFAULT 0,

                    uebertrag NUMERIC(12,2)
                        NOT NULL DEFAULT 0,

                    reset_tag INTEGER
                        NOT NULL DEFAULT 1,

                    periodenstart DATE
                        NOT NULL DEFAULT CURRENT_DATE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ausgaben
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    beschreibung VARCHAR(255) NOT NULL,
                    kategorie VARCHAR(100) NOT NULL,
                    betrag NUMERIC(12,2) NOT NULL,

                    datum TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    ist_fix BOOLEAN
                        NOT NULL DEFAULT FALSE,

                    periodenstart DATE
                )
            """)

            cursor.execute("""
                ALTER TABLE ausgaben
                ADD COLUMN IF NOT EXISTS
                ist_fix BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cursor.execute("""
                ALTER TABLE ausgaben
                ADD COLUMN IF NOT EXISTS
                periodenstart DATE
            """)

            cursor.execute("""
                UPDATE ausgaben
                SET periodenstart = CURRENT_DATE
                WHERE periodenstart IS NULL
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS einkaufsliste
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    artikel VARCHAR(255) NOT NULL,
                    menge VARCHAR(100) DEFAULT '',
                    notiz VARCHAR(500) DEFAULT '',

                    erledigt BOOLEAN
                        NOT NULL DEFAULT FALSE,

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS verbesserungsvorschlaege
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    titel VARCHAR(255) NOT NULL,
                    beschreibung TEXT NOT NULL,

                    status VARCHAR(50)
                        NOT NULL DEFAULT 'Neu',

                    admin_notiz TEXT DEFAULT '',

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    bearbeitet_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ==================================================
            # AUFGABEN-FREIGABEN
            # ==================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aufgaben_freigaben
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id_1 INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    benutzer_id_2 INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    UNIQUE (
                        benutzer_id_1,
                        benutzer_id_2
                    ),

                    CHECK (
                        benutzer_id_1
                        <
                        benutzer_id_2
                    )
                )
            """)

            # ==================================================
            # AUFGABEN
            # ==================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aufgaben
                (
                    id SERIAL PRIMARY KEY,

                    ersteller_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    titel VARCHAR(255) NOT NULL,

                    beschreibung TEXT
                        DEFAULT '',

                    erledigt BOOLEAN
                        NOT NULL DEFAULT FALSE,

                    erledigt_von_id INTEGER
                        REFERENCES benutzer(id)
                        ON DELETE SET NULL,

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ==================================================
            # WER DARF EINE AUFGABE SEHEN?
            # ==================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aufgaben_geteilt
                (
                    id SERIAL PRIMARY KEY,

                    aufgabe_id INTEGER NOT NULL
                        REFERENCES aufgaben(id)
                        ON DELETE CASCADE,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    UNIQUE (
                        aufgabe_id,
                        benutzer_id
                    )
                )
            """)

            # ==================================================
            # KALENDER
            # ==================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS termine
                (
                    id SERIAL PRIMARY KEY,

                    ersteller_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    titel VARCHAR(255) NOT NULL,
                    beschreibung TEXT DEFAULT '',

                    start_datum DATE NOT NULL,
                    start_zeit TIME,
                    end_datum DATE,
                    end_zeit TIME,

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS termine_geteilt
                (
                    id SERIAL PRIMARY KEY,

                    termin_id INTEGER NOT NULL
                        REFERENCES termine(id)
                        ON DELETE CASCADE,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    UNIQUE (
                        termin_id,
                        benutzer_id
                    )
                )
            """)

            # ==================================================
            # PUSH-BENACHRICHTIGUNGEN
            # ==================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS push_abonnements
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    endpoint TEXT UNIQUE NOT NULL,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ==================================================
            # FAMILIEN-PINNWAND
            # ==================================================

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pinnwand
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    inhalt TEXT NOT NULL,

                    wichtig BOOLEAN
                        NOT NULL DEFAULT FALSE,

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS erinnerungen_gesendet
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    typ VARCHAR(50) NOT NULL,
                    referenz_id INTEGER,
                    schluessel VARCHAR(120) NOT NULL,

                    gesendet_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    UNIQUE (
                        benutzer_id,
                        typ,
                        schluessel
                    )
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS familienaktivitaeten
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    ziel_benutzer_id INTEGER
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    symbol VARCHAR(20) NOT NULL DEFAULT '•',
                    text TEXT NOT NULL,

                    erstellt_am TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.close()

        else:

            db.execute("""
                CREATE TABLE IF NOT EXISTS benutzer
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    benutzername TEXT UNIQUE NOT NULL,
                    passwort TEXT NOT NULL,
                    rolle TEXT NOT NULL DEFAULT 'benutzer',
                    passwort_muss_geaendert INTEGER NOT NULL DEFAULT 0
                )
            """)

            spalten = db.execute(
                "PRAGMA table_info(benutzer)"
            ).fetchall()

            namen = [
                spalte["name"]
                for spalte in spalten
            ]

            if (
                "passwort_muss_geaendert"
                not in namen
            ):

                db.execute("""
                    ALTER TABLE benutzer
                    ADD COLUMN
                    passwort_muss_geaendert
                    INTEGER NOT NULL DEFAULT 0
                """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS finanz_einstellungen
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER UNIQUE NOT NULL,

                    standard_budget REAL
                        NOT NULL DEFAULT 0,

                    uebertrag REAL
                        NOT NULL DEFAULT 0,

                    reset_tag INTEGER
                        NOT NULL DEFAULT 1,

                    periodenstart TEXT NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS ausgaben
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,

                    beschreibung TEXT NOT NULL,
                    kategorie TEXT NOT NULL,
                    betrag REAL NOT NULL,

                    datum TEXT NOT NULL,

                    ist_fix INTEGER
                        NOT NULL DEFAULT 0,

                    periodenstart TEXT,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            spalten = db.execute(
                "PRAGMA table_info(ausgaben)"
            ).fetchall()

            namen = [
                spalte["name"]
                for spalte in spalten
            ]

            if "ist_fix" not in namen:

                db.execute("""
                    ALTER TABLE ausgaben
                    ADD COLUMN ist_fix
                    INTEGER NOT NULL DEFAULT 0
                """)

            if "periodenstart" not in namen:

                db.execute("""
                    ALTER TABLE ausgaben
                    ADD COLUMN periodenstart TEXT
                """)

            db.execute(
                """
                UPDATE ausgaben
                SET periodenstart = ?
                WHERE periodenstart IS NULL
                """,
                (
                    heute().isoformat(),
                )
            )

            db.execute("""
                CREATE TABLE IF NOT EXISTS einkaufsliste
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,

                    artikel TEXT NOT NULL,
                    menge TEXT DEFAULT '',
                    notiz TEXT DEFAULT '',

                    erledigt INTEGER
                        NOT NULL DEFAULT 0,

                    erstellt_am TEXT NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS verbesserungsvorschlaege
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,

                    titel TEXT NOT NULL,
                    beschreibung TEXT NOT NULL,

                    status TEXT
                        NOT NULL DEFAULT 'Neu',

                    admin_notiz TEXT DEFAULT '',

                    erstellt_am TEXT NOT NULL,
                    bearbeitet_am TEXT NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS aufgaben_freigaben
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id_1 INTEGER NOT NULL,
                    benutzer_id_2 INTEGER NOT NULL,

                    UNIQUE (
                        benutzer_id_1,
                        benutzer_id_2
                    ),

                    CHECK (
                        benutzer_id_1
                        <
                        benutzer_id_2
                    ),

                    FOREIGN KEY (benutzer_id_1)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE,

                    FOREIGN KEY (benutzer_id_2)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS aufgaben
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    ersteller_id INTEGER NOT NULL,

                    titel TEXT NOT NULL,
                    beschreibung TEXT DEFAULT '',

                    erledigt INTEGER
                        NOT NULL DEFAULT 0,

                    erledigt_von_id INTEGER,

                    erstellt_am TEXT NOT NULL,

                    FOREIGN KEY (ersteller_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE,

                    FOREIGN KEY (erledigt_von_id)
                    REFERENCES benutzer(id)
                    ON DELETE SET NULL
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS aufgaben_geteilt
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    aufgabe_id INTEGER NOT NULL,
                    benutzer_id INTEGER NOT NULL,

                    UNIQUE (
                        aufgabe_id,
                        benutzer_id
                    ),

                    FOREIGN KEY (aufgabe_id)
                    REFERENCES aufgaben(id)
                    ON DELETE CASCADE,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            # ==================================================
            # KALENDER
            # ==================================================

            db.execute("""
                CREATE TABLE IF NOT EXISTS termine
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    ersteller_id INTEGER NOT NULL,

                    titel TEXT NOT NULL,
                    beschreibung TEXT DEFAULT '',

                    start_datum TEXT NOT NULL,
                    start_zeit TEXT,
                    end_datum TEXT,
                    end_zeit TEXT,

                    erstellt_am TEXT NOT NULL,

                    FOREIGN KEY (ersteller_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS termine_geteilt
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    termin_id INTEGER NOT NULL,
                    benutzer_id INTEGER NOT NULL,

                    UNIQUE (
                        termin_id,
                        benutzer_id
                    ),

                    FOREIGN KEY (termin_id)
                    REFERENCES termine(id)
                    ON DELETE CASCADE,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            # ==================================================
            # PUSH-BENACHRICHTIGUNGEN
            # ==================================================

            db.execute("""
                CREATE TABLE IF NOT EXISTS push_abonnements
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,

                    endpoint TEXT UNIQUE NOT NULL,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,

                    erstellt_am TEXT NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            # ==================================================
            # FAMILIEN-PINNWAND
            # ==================================================

            db.execute("""
                CREATE TABLE IF NOT EXISTS pinnwand
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,

                    inhalt TEXT NOT NULL,

                    wichtig INTEGER
                        NOT NULL DEFAULT 0,

                    erstellt_am TEXT NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS erinnerungen_gesendet
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,

                    typ TEXT NOT NULL,
                    referenz_id INTEGER,
                    schluessel TEXT NOT NULL,

                    gesendet_am TEXT NOT NULL,

                    UNIQUE (
                        benutzer_id,
                        typ,
                        schluessel
                    ),

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS familienaktivitaeten
                (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    benutzer_id INTEGER NOT NULL,
                    ziel_benutzer_id INTEGER,

                    symbol TEXT NOT NULL DEFAULT '•',
                    text TEXT NOT NULL,
                    erstellt_am TEXT NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE,

                    FOREIGN KEY (ziel_benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

        db.commit()

    finally:

        db.close()


    # ========================================================
    # ADMIN ANLEGEN
    # ========================================================

    admin = query_einen(

        """
        SELECT id
        FROM benutzer
        WHERE rolle = %s
        LIMIT 1
        """,

        """
        SELECT id
        FROM benutzer
        WHERE rolle = ?
        LIMIT 1
        """,

        (
            "admin",
        )
    )

    if admin is None:

        execute_query(

            """
            INSERT INTO benutzer
            (
                benutzername,
                passwort,
                rolle,
                passwort_muss_geaendert
            )

            VALUES (
                %s,
                %s,
                %s,
                FALSE
            )
            """,

            """
            INSERT INTO benutzer
            (
                benutzername,
                passwort,
                rolle,
                passwort_muss_geaendert
            )

            VALUES (
                ?,
                ?,
                ?,
                0
            )
            """,

            (
                "joel",

                generate_password_hash(
                    ADMIN_PASSWORD
                ),

                "admin"
            )
        )


# ============================================================
# FINANZ-HILFSFUNKTIONEN
# ============================================================

def finanz_einstellungen_sicherstellen(
    benutzer_id
):

    einstellungen = query_einen(

        """
        SELECT *
        FROM finanz_einstellungen
        WHERE benutzer_id = %s
        """,

        """
        SELECT *
        FROM finanz_einstellungen
        WHERE benutzer_id = ?
        """,

        (
            benutzer_id,
        )
    )

    if einstellungen:
        return einstellungen

    start = aktueller_periodenstart(
        1
    )

    execute_query(

        """
        INSERT INTO finanz_einstellungen
        (
            benutzer_id,
            standard_budget,
            uebertrag,
            reset_tag,
            periodenstart
        )

        VALUES (
            %s,
            0,
            0,
            1,
            %s
        )
        """,

        """
        INSERT INTO finanz_einstellungen
        (
            benutzer_id,
            standard_budget,
            uebertrag,
            reset_tag,
            periodenstart
        )

        VALUES (
            ?,
            0,
            0,
            1,
            ?
        )
        """,

        (
            benutzer_id,

            start
            if postgres_verwenden()
            else start.isoformat()
        )
    )

    return finanz_einstellungen_sicherstellen(
        benutzer_id
    )


def monatswechsel_pruefen(
    benutzer_id
):

    einstellungen = (
        finanz_einstellungen_sicherstellen(
            benutzer_id
        )
    )

    reset_tag = int(
        einstellungen["reset_tag"]
    )

    periodenstart = datum_lesen(
        einstellungen["periodenstart"]
    )

    standard_budget = float(
        einstellungen["standard_budget"]
    )

    uebertrag = float(
        einstellungen["uebertrag"]
    )

    while True:

        naechster_start = (
            naechster_periodenstart(
                periodenstart,
                reset_tag
            )
        )

        if naechster_start > heute():
            break

        summe = query_einen(

            """
            SELECT
                COALESCE(
                    SUM(betrag),
                    0
                ) AS summe

            FROM ausgaben

            WHERE
                benutzer_id = %s
                AND periodenstart = %s
            """,

            """
            SELECT
                COALESCE(
                    SUM(betrag),
                    0
                ) AS summe

            FROM ausgaben

            WHERE
                benutzer_id = ?
                AND periodenstart = ?
            """,

            (
                benutzer_id,

                periodenstart
                if postgres_verwenden()
                else periodenstart.isoformat()
            )
        )

        ausgegeben = float(
            summe["summe"] or 0
        )

        rest = (
            standard_budget
            + uebertrag
            - ausgegeben
        )

        neuer_uebertrag = max(
            rest,
            0
        )

        fixkosten = query_alle(

            """
            SELECT
                beschreibung,
                kategorie,
                betrag

            FROM ausgaben

            WHERE
                benutzer_id = %s
                AND periodenstart = %s
                AND ist_fix = TRUE
            """,

            """
            SELECT
                beschreibung,
                kategorie,
                betrag

            FROM ausgaben

            WHERE
                benutzer_id = ?
                AND periodenstart = ?
                AND ist_fix = 1
            """,

            (
                benutzer_id,

                periodenstart
                if postgres_verwenden()
                else periodenstart.isoformat()
            )
        )

        execute_query(

            """
            UPDATE finanz_einstellungen

            SET
                uebertrag = %s,
                periodenstart = %s

            WHERE benutzer_id = %s
            """,

            """
            UPDATE finanz_einstellungen

            SET
                uebertrag = ?,
                periodenstart = ?

            WHERE benutzer_id = ?
            """,

            (
                neuer_uebertrag,

                naechster_start
                if postgres_verwenden()
                else naechster_start.isoformat(),

                benutzer_id
            )
        )

        for fixkosten_eintrag in fixkosten:

            if postgres_verwenden():

                execute_query(

                    """
                    INSERT INTO ausgaben
                    (
                        benutzer_id,
                        beschreibung,
                        kategorie,
                        betrag,
                        ist_fix,
                        periodenstart
                    )

                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        TRUE,
                        %s
                    )
                    """,

                    "",

                    (
                        benutzer_id,
                        fixkosten_eintrag[
                            "beschreibung"
                        ],
                        fixkosten_eintrag[
                            "kategorie"
                        ],
                        fixkosten_eintrag[
                            "betrag"
                        ],
                        naechster_start
                    )
                )

            else:

                execute_query(

                    "",

                    """
                    INSERT INTO ausgaben
                    (
                        benutzer_id,
                        beschreibung,
                        kategorie,
                        betrag,
                        datum,
                        ist_fix,
                        periodenstart
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        1,
                        ?
                    )
                    """,

                    (
                        benutzer_id,
                        fixkosten_eintrag[
                            "beschreibung"
                        ],
                        fixkosten_eintrag[
                            "kategorie"
                        ],
                        fixkosten_eintrag[
                            "betrag"
                        ],
                        jetzt().strftime(
                            "%d.%m.%Y %H:%M"
                        ),
                        naechster_start.isoformat()
                    )
                )

        uebertrag = neuer_uebertrag
        periodenstart = naechster_start

    return finanz_einstellungen_sicherstellen(
        benutzer_id
    )


# ============================================================
# AUFGABEN-HILFSFUNKTIONEN
# ============================================================

def freigegebene_kontakte(
    benutzer_id
):

    return query_alle(

        """
        SELECT
            b.id,
            b.benutzername

        FROM benutzer b

        WHERE
            b.id != %s

            AND EXISTS
            (
                SELECT 1

                FROM aufgaben_freigaben f

                WHERE
                    (
                        f.benutzer_id_1 = %s
                        AND
                        f.benutzer_id_2 = b.id
                    )

                    OR

                    (
                        f.benutzer_id_2 = %s
                        AND
                        f.benutzer_id_1 = b.id
                    )
            )

        ORDER BY
            b.benutzername
        """,

        """
        SELECT
            b.id,
            b.benutzername

        FROM benutzer b

        WHERE
            b.id != ?

            AND EXISTS
            (
                SELECT 1

                FROM aufgaben_freigaben f

                WHERE
                    (
                        f.benutzer_id_1 = ?
                        AND
                        f.benutzer_id_2 = b.id
                    )

                    OR

                    (
                        f.benutzer_id_2 = ?
                        AND
                        f.benutzer_id_1 = b.id
                    )
            )

        ORDER BY
            b.benutzername
        """,

        (
            benutzer_id,
            benutzer_id,
            benutzer_id
        )
    )


def benutzer_darf_aufgabe_sehen(
    aufgabe_id,
    benutzer_id
):

    eintrag = query_einen(

        """
        SELECT a.id

        FROM aufgaben a

        WHERE
            a.id = %s

            AND
            (
                a.ersteller_id = %s

                OR EXISTS
                (
                    SELECT 1
                    FROM aufgaben_geteilt ag

                    WHERE
                        ag.aufgabe_id = a.id
                        AND
                        ag.benutzer_id = %s
                )
            )
        """,

        """
        SELECT a.id

        FROM aufgaben a

        WHERE
            a.id = ?

            AND
            (
                a.ersteller_id = ?

                OR EXISTS
                (
                    SELECT 1
                    FROM aufgaben_geteilt ag

                    WHERE
                        ag.aufgabe_id = a.id
                        AND
                        ag.benutzer_id = ?
                )
            )
        """,

        (
            aufgabe_id,
            benutzer_id,
            benutzer_id
        )
    )

    return eintrag is not None


def benutzer_ist_ersteller(
    aufgabe_id,
    benutzer_id
):

    eintrag = query_einen(

        """
        SELECT id
        FROM aufgaben

        WHERE
            id = %s
            AND ersteller_id = %s
        """,

        """
        SELECT id
        FROM aufgaben

        WHERE
            id = ?
            AND ersteller_id = ?
        """,

        (
            aufgabe_id,
            benutzer_id
        )
    )

    return eintrag is not None


def aufgaben_fuer_benutzer(
    benutzer_id
):

    aufgaben = query_alle(

        """
        SELECT
            a.id,
            a.ersteller_id,
            a.titel,
            a.beschreibung,
            a.erledigt,

            TO_CHAR(
                a.erstellt_am,
                'DD.MM.YYYY HH24:MI'
            ) AS erstellt_am,

            ersteller.benutzername
                AS ersteller_name,

            erlediger.benutzername
                AS erledigt_von_name

        FROM aufgaben a

        JOIN benutzer ersteller
            ON ersteller.id =
               a.ersteller_id

        LEFT JOIN benutzer erlediger
            ON erlediger.id =
               a.erledigt_von_id

        WHERE
            a.ersteller_id = %s

            OR EXISTS
            (
                SELECT 1
                FROM aufgaben_geteilt ag

                WHERE
                    ag.aufgabe_id = a.id
                    AND
                    ag.benutzer_id = %s
            )

        ORDER BY
            a.erledigt ASC,
            a.id DESC
        """,

        """
        SELECT
            a.id,
            a.ersteller_id,
            a.titel,
            a.beschreibung,
            a.erledigt,
            a.erstellt_am,

            ersteller.benutzername
                AS ersteller_name,

            erlediger.benutzername
                AS erledigt_von_name

        FROM aufgaben a

        JOIN benutzer ersteller
            ON ersteller.id =
               a.ersteller_id

        LEFT JOIN benutzer erlediger
            ON erlediger.id =
               a.erledigt_von_id

        WHERE
            a.ersteller_id = ?

            OR EXISTS
            (
                SELECT 1
                FROM aufgaben_geteilt ag

                WHERE
                    ag.aufgabe_id = a.id
                    AND
                    ag.benutzer_id = ?
            )

        ORDER BY
            a.erledigt ASC,
            a.id DESC
        """,

        (
            benutzer_id,
            benutzer_id
        )
    )

    ergebnis = []

    for aufgabe in aufgaben:

        geteilt = query_alle(

            """
            SELECT
                b.id,
                b.benutzername

            FROM aufgaben_geteilt ag

            JOIN benutzer b
                ON b.id =
                   ag.benutzer_id

            WHERE
                ag.aufgabe_id = %s

            ORDER BY
                b.benutzername
            """,

            """
            SELECT
                b.id,
                b.benutzername

            FROM aufgaben_geteilt ag

            JOIN benutzer b
                ON b.id =
                   ag.benutzer_id

            WHERE
                ag.aufgabe_id = ?

            ORDER BY
                b.benutzername
            """,

            (
                aufgabe["id"],
            )
        )

        geteilt_ids = [
            person["id"]
            for person in geteilt
        ]

        daten = dict(
            aufgabe
        )

        daten["ist_eigene"] = (
            aufgabe[
                "ersteller_id"
            ]
            == benutzer_id
        )

        daten["geteilt_mit"] = geteilt
        daten["geteilt_ids"] = geteilt_ids

        ergebnis.append(
            daten
        )

    return ergebnis


# ============================================================
# KALENDER-HILFSFUNKTIONEN
# ============================================================

def datum_als_iso(wert):

    if wert is None or wert == "":
        return ""

    if isinstance(wert, datetime):
        wert = wert.date()

    if isinstance(wert, date):
        return wert.isoformat()

    text = str(wert).strip()

    if " " in text:
        text = text.split(" ", 1)[0]

    return text[:10]


def datum_als_anzeige(wert):

    iso = datum_als_iso(wert)

    if not iso:
        return ""

    try:
        return date.fromisoformat(
            iso
        ).strftime(
            "%d.%m.%Y"
        )
    except ValueError:
        return iso


def zeit_als_text(wert):

    if wert is None or wert == "":
        return ""

    if hasattr(wert, "strftime"):

        try:
            return wert.strftime(
                "%H:%M"
            )
        except Exception:
            pass

    text = str(wert).strip()

    if len(text) >= 5:
        return text[:5]

    return text


def termin_ist_ersteller(
    termin_id,
    benutzer_id
):

    eintrag = query_einen(

        """
        SELECT id
        FROM termine

        WHERE
            id = %s
            AND ersteller_id = %s
        """,

        """
        SELECT id
        FROM termine

        WHERE
            id = ?
            AND ersteller_id = ?
        """,

        (
            termin_id,
            benutzer_id
        )
    )

    return eintrag is not None


def termine_fuer_benutzer(
    benutzer_id
):

    termine = query_alle(

        """
        SELECT
            t.id,
            t.ersteller_id,
            t.titel,
            t.beschreibung,
            t.start_datum,
            t.start_zeit,
            t.end_datum,
            t.end_zeit,
            t.erstellt_am,
            ersteller.benutzername AS ersteller_name

        FROM termine t

        JOIN benutzer ersteller
            ON ersteller.id = t.ersteller_id

        WHERE
            t.ersteller_id = %s

            OR EXISTS
            (
                SELECT 1
                FROM termine_geteilt tg

                WHERE
                    tg.termin_id = t.id
                    AND tg.benutzer_id = %s

                    AND EXISTS
                    (
                        SELECT 1
                        FROM aufgaben_freigaben f

                        WHERE
                            (
                                f.benutzer_id_1 = LEAST(
                                    t.ersteller_id,
                                    tg.benutzer_id
                                )
                                AND
                                f.benutzer_id_2 = GREATEST(
                                    t.ersteller_id,
                                    tg.benutzer_id
                                )
                            )
                    )
            )

        ORDER BY
            t.start_datum ASC,
            t.start_zeit ASC NULLS FIRST,
            t.id ASC
        """,

        """
        SELECT
            t.id,
            t.ersteller_id,
            t.titel,
            t.beschreibung,
            t.start_datum,
            t.start_zeit,
            t.end_datum,
            t.end_zeit,
            t.erstellt_am,
            ersteller.benutzername AS ersteller_name

        FROM termine t

        JOIN benutzer ersteller
            ON ersteller.id = t.ersteller_id

        WHERE
            t.ersteller_id = ?

            OR EXISTS
            (
                SELECT 1
                FROM termine_geteilt tg

                WHERE
                    tg.termin_id = t.id
                    AND tg.benutzer_id = ?

                    AND EXISTS
                    (
                        SELECT 1
                        FROM aufgaben_freigaben f

                        WHERE
                            (
                                f.benutzer_id_1 = MIN(
                                    t.ersteller_id,
                                    tg.benutzer_id
                                )
                                AND
                                f.benutzer_id_2 = MAX(
                                    t.ersteller_id,
                                    tg.benutzer_id
                                )
                            )
                    )
            )

        ORDER BY
            t.start_datum ASC,
            CASE
                WHEN t.start_zeit IS NULL
                OR t.start_zeit = ''
                THEN '00:00'
                ELSE t.start_zeit
            END ASC,
            t.id ASC
        """,

        (
            benutzer_id,
            benutzer_id
        )
    )

    ergebnis = []

    for termin in termine:

        geteilt = query_alle(

            """
            SELECT
                b.id,
                b.benutzername

            FROM termine_geteilt tg

            JOIN benutzer b
                ON b.id = tg.benutzer_id

            JOIN termine t
                ON t.id = tg.termin_id

            WHERE
                tg.termin_id = %s

                AND EXISTS
                (
                    SELECT 1
                    FROM aufgaben_freigaben f

                    WHERE
                        f.benutzer_id_1 = LEAST(
                            t.ersteller_id,
                            tg.benutzer_id
                        )
                        AND
                        f.benutzer_id_2 = GREATEST(
                            t.ersteller_id,
                            tg.benutzer_id
                        )
                )

            ORDER BY
                b.benutzername
            """,

            """
            SELECT
                b.id,
                b.benutzername

            FROM termine_geteilt tg

            JOIN benutzer b
                ON b.id = tg.benutzer_id

            JOIN termine t
                ON t.id = tg.termin_id

            WHERE
                tg.termin_id = ?

                AND EXISTS
                (
                    SELECT 1
                    FROM aufgaben_freigaben f

                    WHERE
                        f.benutzer_id_1 = MIN(
                            t.ersteller_id,
                            tg.benutzer_id
                        )
                        AND
                        f.benutzer_id_2 = MAX(
                            t.ersteller_id,
                            tg.benutzer_id
                        )
                )

            ORDER BY
                b.benutzername
            """,

            (
                termin["id"],
            )
        )

        daten = dict(
            termin
        )

        daten["ist_eigener"] = (
            int(termin["ersteller_id"])
            == int(benutzer_id)
        )

        daten["start_datum"] = (
            datum_als_iso(
                termin["start_datum"]
            )
        )

        daten["start_datum_anzeige"] = (
            datum_als_anzeige(
                termin["start_datum"]
            )
        )

        daten["start_zeit"] = (
            zeit_als_text(
                termin["start_zeit"]
            )
        )

        daten["end_datum"] = (
            datum_als_iso(
                termin["end_datum"]
            )
        )

        daten["end_datum_anzeige"] = (
            datum_als_anzeige(
                termin["end_datum"]
            )
        )

        daten["end_zeit"] = (
            zeit_als_text(
                termin["end_zeit"]
            )
        )

        daten["geteilt_mit"] = geteilt

        daten["geteilt_ids"] = [
            int(person["id"])
            for person in geteilt
        ]

        ergebnis.append(
            daten
        )

    return ergebnis


# ============================================================
# PUSH-BENACHRICHTIGUNGEN - HILFSFUNKTIONEN
# ============================================================

def vapid_private_key_datei():

    if not VAPID_PRIVATE_KEY_B64:
        return None

    try:

        key_bytes = base64.b64decode(
            VAPID_PRIVATE_KEY_B64
        )

    except Exception:
        return None

    pfad = os.path.join(
        tempfile.gettempdir(),
        "familienplaner_vapid_private_key.pem"
    )

    try:

        with open(
            pfad,
            "wb"
        ) as datei:

            datei.write(
                key_bytes
            )

    except OSError:
        return None

    return pfad


def push_konfiguriert():

    return bool(
        webpush
        and
        VAPID_PUBLIC_KEY
        and
        VAPID_PRIVATE_KEY_B64
    )


def push_abonnement_loeschen(
    endpoint
):

    if not endpoint:
        return

    execute_query(

        """
        DELETE FROM push_abonnements
        WHERE endpoint = %s
        """,

        """
        DELETE FROM push_abonnements
        WHERE endpoint = ?
        """,

        (
            endpoint,
        )
    )


def push_an_benutzer(
    benutzer_id,
    titel,
    nachricht,
    url="/dashboard"
):

    if not push_konfiguriert():
        return

    abonnements = query_alle(

        """
        SELECT
            endpoint,
            p256dh,
            auth

        FROM push_abonnements

        WHERE benutzer_id = %s
        """,

        """
        SELECT
            endpoint,
            p256dh,
            auth

        FROM push_abonnements

        WHERE benutzer_id = ?
        """,

        (
            benutzer_id,
        )
    )

    if not abonnements:
        return

    private_key = (
        vapid_private_key_datei()
    )

    if not private_key:
        return

    payload = json.dumps(
        {
            "title": titel,
            "body": nachricht,
            "url": url
        },
        ensure_ascii=False
    )

    for abonnement in abonnements:

        subscription_info = {
            "endpoint":
                abonnement["endpoint"],

            "keys": {
                "p256dh":
                    abonnement["p256dh"],

                "auth":
                    abonnement["auth"]
            }
        }

        try:

            webpush(
                subscription_info=
                    subscription_info,

                data=
                    payload,

                vapid_private_key=
                    private_key,

                vapid_claims={
                    "sub":
                        VAPID_SUBJECT
                }
            )

        except WebPushException as fehler:

            status_code = None

            antwort = getattr(
                fehler,
                "response",
                None
            )

            if antwort is not None:

                status_code = getattr(
                    antwort,
                    "status_code",
                    None
                )

            if status_code in (
                404,
                410
            ):

                try:

                    push_abonnement_loeschen(
                        abonnement["endpoint"]
                    )

                except Exception:
                    pass

        except Exception:
            pass


# ============================================================
# PUSH-BENACHRICHTIGUNGEN - ROUTEN
# ============================================================

@app.route(
    "/benachrichtigungen"
)
def benachrichtigungen():

    if "benutzer_id" not in session:
        return redirect("/")

    return render_template(
        "benachrichtigungen.html",

        benutzer=
            session.get(
                "benutzer",
                ""
            ),

        vapid_public_key=
            VAPID_PUBLIC_KEY,

        push_bereit=
            push_konfiguriert()
    )


@app.route(
    "/push-public-key"
)
def push_public_key():

    if "benutzer_id" not in session:

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Nicht angemeldet."
            }
        ), 401

    return jsonify(
        {
            "ok":
                bool(
                    VAPID_PUBLIC_KEY
                ),

            "publicKey":
                VAPID_PUBLIC_KEY
        }
    )


@app.route(
    "/push-abonnieren",
    methods=[
        "POST"
    ]
)
def push_abonnieren():

    if "benutzer_id" not in session:

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Nicht angemeldet."
            }
        ), 401

    daten = request.get_json(
        silent=True
    ) or {}

    endpoint = str(
        daten.get(
            "endpoint",
            ""
        )
    ).strip()

    keys = daten.get(
        "keys",
        {}
    ) or {}

    p256dh = str(
        keys.get(
            "p256dh",
            ""
        )
    ).strip()

    auth = str(
        keys.get(
            "auth",
            ""
        )
    ).strip()

    if (
        not endpoint
        or
        not p256dh
        or
        not auth
    ):

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Ungültiges Push-Abonnement."
            }
        ), 400

    benutzer_id = session[
        "benutzer_id"
    ]

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                """
                INSERT INTO push_abonnements
                (
                    benutzer_id,
                    endpoint,
                    p256dh,
                    auth
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s
                )

                ON CONFLICT (
                    endpoint
                )

                DO UPDATE SET
                    benutzer_id =
                        EXCLUDED.benutzer_id,

                    p256dh =
                        EXCLUDED.p256dh,

                    auth =
                        EXCLUDED.auth
                """,
                (
                    benutzer_id,
                    endpoint,
                    p256dh,
                    auth
                )
            )

            cursor.close()

        else:

            db.execute(
                """
                INSERT INTO push_abonnements
                (
                    benutzer_id,
                    endpoint,
                    p256dh,
                    auth,
                    erstellt_am
                )

                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                )

                ON CONFLICT(endpoint)
                DO UPDATE SET

                    benutzer_id =
                        excluded.benutzer_id,

                    p256dh =
                        excluded.p256dh,

                    auth =
                        excluded.auth
                """,
                (
                    benutzer_id,
                    endpoint,
                    p256dh,
                    auth,
                    jetzt().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
            )

        db.commit()

    except Exception:

        db.rollback()

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Abonnement konnte nicht gespeichert werden."
            }
        ), 500

    finally:
        db.close()

    return jsonify(
        {
            "ok": True
        }
    )


@app.route(
    "/push-abmelden",
    methods=[
        "POST"
    ]
)
def push_abmelden():

    if "benutzer_id" not in session:

        return jsonify(
            {
                "ok": False
            }
        ), 401

    daten = request.get_json(
        silent=True
    ) or {}

    endpoint = str(
        daten.get(
            "endpoint",
            ""
        )
    ).strip()

    if endpoint:

        execute_query(

            """
            DELETE FROM push_abonnements

            WHERE
                endpoint = %s
                AND benutzer_id = %s
            """,

            """
            DELETE FROM push_abonnements

            WHERE
                endpoint = ?
                AND benutzer_id = ?
            """,

            (
                endpoint,
                session["benutzer_id"]
            )
        )

    return jsonify(
        {
            "ok": True
        }
    )


@app.route(
    "/push-test",
    methods=[
        "POST"
    ]
)
def push_test():

    if "benutzer_id" not in session:

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Nicht angemeldet."
            }
        ), 401

    if not push_konfiguriert():

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Push ist auf dem Server noch nicht eingerichtet."
            }
        ), 503

    push_an_benutzer(
        session["benutzer_id"],
        "Familienplaner",
        "🎉 Deine Handy-Benachrichtigungen funktionieren.",
        "/dashboard"
    )

    return jsonify(
        {
            "ok": True
        }
    )


# ============================================================
# AUTOMATISCHE ERINNERUNGEN
# ============================================================

def erinnerung_wurde_gesendet(
    benutzer_id,
    typ,
    schluessel
):

    eintrag = query_einen(

        """
        SELECT id
        FROM erinnerungen_gesendet

        WHERE
            benutzer_id = %s
            AND typ = %s
            AND schluessel = %s
        """,

        """
        SELECT id
        FROM erinnerungen_gesendet

        WHERE
            benutzer_id = ?
            AND typ = ?
            AND schluessel = ?
        """,

        (
            benutzer_id,
            typ,
            schluessel
        )
    )

    return eintrag is not None


def erinnerung_markieren(
    benutzer_id,
    typ,
    referenz_id,
    schluessel
):

    if postgres_verwenden():

        execute_query(

            """
            INSERT INTO erinnerungen_gesendet
            (
                benutzer_id,
                typ,
                referenz_id,
                schluessel
            )

            VALUES (
                %s,
                %s,
                %s,
                %s
            )

            ON CONFLICT
            (
                benutzer_id,
                typ,
                schluessel
            )

            DO NOTHING
            """,

            "",

            (
                benutzer_id,
                typ,
                referenz_id,
                schluessel
            )
        )

    else:

        execute_query(

            "",

            """
            INSERT OR IGNORE
            INTO erinnerungen_gesendet
            (
                benutzer_id,
                typ,
                referenz_id,
                schluessel,
                gesendet_am
            )

            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,

            (
                benutzer_id,
                typ,
                referenz_id,
                schluessel,
                jetzt().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        )


def aktive_benutzer():

    return query_alle(

        """
        SELECT
            id,
            benutzername

        FROM benutzer

        ORDER BY id
        """,

        """
        SELECT
            id,
            benutzername

        FROM benutzer

        ORDER BY id
        """
    )


def termin_start_datetime(
    termin
):

    start_datum = datum_lesen(
        termin["start_datum"]
    )

    start_zeit_text = (
        termin["start_zeit"]
        or "09:00"
    )

    try:

        start_zeit_obj = (
            datetime.strptime(
                start_zeit_text,
                "%H:%M"
            ).time()
        )

    except ValueError:

        start_zeit_obj = (
            datetime.strptime(
                "09:00",
                "%H:%M"
            ).time()
        )

    return datetime.combine(
        start_datum,
        start_zeit_obj,
        tzinfo=ZoneInfo(
            "Europe/Berlin"
        )
    )


@app.route(
    "/interne-erinnerungen",
    methods=[
        "GET"
    ]
)
def interne_erinnerungen():

    secret = request.args.get(
        "secret",
        ""
    )

    if (
        not REMINDER_SECRET
        or
        secret != REMINDER_SECRET
    ):

        return jsonify(
            {
                "ok": False,
                "fehler":
                    "Nicht erlaubt."
            }
        ), 403


    jetzt_berlin = jetzt()

    gesendet = 0


    for benutzer in aktive_benutzer():

        benutzer_id = int(
            benutzer["id"]
        )


        # ----------------------------------------------------
        # TERMINE:
        # Erinnerung ungefähr 24 Stunden vorher.
        # Da der externe Prüfer stündlich läuft,
        # wird ein 23-25h Fenster verwendet.
        # ----------------------------------------------------

        termine = termine_fuer_benutzer(
            benutzer_id
        )

        for termin in termine:

            termin_start = (
                termin_start_datetime(
                    termin
                )
            )

            differenz = (
                termin_start
                - jetzt_berlin
            )

            if (
                timedelta(
                    hours=23
                )
                <= differenz
                <= timedelta(
                    hours=25
                )
            ):

                schluessel = (
                    str(
                        termin["id"]
                    )
                    + ":24h"
                )

                if not erinnerung_wurde_gesendet(
                    benutzer_id,
                    "termin_24h",
                    schluessel
                ):

                    zeit_text = (
                        termin["start_zeit"]
                        or "ganztägig"
                    )

                    push_an_benutzer(
                        benutzer_id,
                        "Termin morgen",
                        (
                            "📅 "
                            + termin["titel"]
                            + " · "
                            + termin[
                                "start_datum_anzeige"
                            ]
                            + " · "
                            + zeit_text
                        ),
                        "/kalender"
                    )

                    erinnerung_markieren(
                        benutzer_id,
                        "termin_24h",
                        termin["id"],
                        schluessel
                    )

                    gesendet += 1


        # ----------------------------------------------------
        # AUFGABEN:
        # Einmal täglich morgens zwischen 08:00 und 09:59,
        # falls offene Aufgaben vorhanden sind.
        # ----------------------------------------------------

        if (
            jetzt_berlin.hour
            in (
                8,
                9
            )
        ):

            aufgaben = (
                aufgaben_fuer_benutzer(
                    benutzer_id
                )
            )

            offene = sum(
                1
                for aufgabe in aufgaben
                if not bool(
                    aufgabe["erledigt"]
                )
            )

            if offene > 0:

                schluessel = (
                    jetzt_berlin.date()
                    .isoformat()
                )

                if not erinnerung_wurde_gesendet(
                    benutzer_id,
                    "aufgaben_morgens",
                    schluessel
                ):

                    push_an_benutzer(
                        benutzer_id,
                        "Offene Aufgaben",
                        (
                            "✅ Du hast noch "
                            + str(
                                offene
                            )
                            + (
                                " offene Aufgabe."
                                if offene == 1
                                else " offene Aufgaben."
                            )
                        ),
                        "/aufgaben"
                    )

                    erinnerung_markieren(
                        benutzer_id,
                        "aufgaben_morgens",
                        None,
                        schluessel
                    )

                    gesendet += 1


    return jsonify(
        {
            "ok": True,
            "gesendet":
                gesendet,
            "zeit":
                jetzt_berlin.strftime(
                    "%d.%m.%Y %H:%M"
                )
        }
    )


# ============================================================
# PWA
# ============================================================

@app.route(
    "/service-worker.js"
)
def service_worker():

    antwort = send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript"
    )

    antwort.headers[
        "Service-Worker-Allowed"
    ] = "/"

    antwort.headers[
        "Cache-Control"
    ] = "no-cache"

    return antwort


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    if (
        request.method == "GET"
        and
        "benutzer_id" in session
    ):

        return redirect(
            "/dashboard"
        )

    fehler = ""

    if request.method == "POST":

        benutzername = request.form.get(
            "benutzername",
            ""
        ).strip()

        passwort = request.form.get(
            "passwort",
            ""
        )

        benutzer = query_einen(

            """
            SELECT *
            FROM benutzer
            WHERE benutzername = %s
            """,

            """
            SELECT *
            FROM benutzer
            WHERE benutzername = ?
            """,

            (
                benutzername,
            )
        )

        if (
            benutzer
            and
            check_password_hash(
                benutzer["passwort"],
                passwort
            )
        ):

            session.clear()

            session[
                "benutzer_id"
            ] = benutzer["id"]

            session[
                "benutzer"
            ] = benutzer[
                "benutzername"
            ]

            session[
                "rolle"
            ] = benutzer["rolle"]

            session[
                "passwort_muss_geaendert"
            ] = bool(
                benutzer[
                    "passwort_muss_geaendert"
                ]
            )

            if session[
                "passwort_muss_geaendert"
            ]:

                return redirect(
                    "/erstes-passwort"
                )

            return redirect(
                "/dashboard"
            )

        fehler = (
            "Benutzername oder Passwort ist falsch."
        )

    return render_template(
        "login.html",
        fehler=fehler
    )


# ============================================================
# ERSTES PASSWORT
# ============================================================

@app.route(
    "/erstes-passwort",
    methods=[
        "GET",
        "POST"
    ]
)
def erstes_passwort():

    if "benutzer_id" not in session:
        return redirect("/")

    fehler = ""

    if request.method == "POST":

        passwort1 = request.form.get(
            "passwort",
            ""
        )

        passwort2 = request.form.get(
            "passwort_wiederholen",
            ""
        )

        if len(passwort1) < 6:

            fehler = (
                "Das Passwort muss mindestens 6 Zeichen haben."
            )

        elif passwort1 != passwort2:

            fehler = (
                "Die Passwörter stimmen nicht überein."
            )

        else:

            execute_query(

                """
                UPDATE benutzer

                SET
                    passwort = %s,
                    passwort_muss_geaendert = FALSE

                WHERE id = %s
                """,

                """
                UPDATE benutzer

                SET
                    passwort = ?,
                    passwort_muss_geaendert = 0

                WHERE id = ?
                """,

                (
                    generate_password_hash(
                        passwort1
                    ),

                    session[
                        "benutzer_id"
                    ]
                )
            )

            session[
                "passwort_muss_geaendert"
            ] = False

            return redirect(
                "/dashboard"
            )

    return render_template(
        "erstes_passwort.html",
        fehler=fehler,
        benutzer=session.get(
            "benutzer"
        )
    )


# ============================================================
# FAMILIENAKTIVITÄTEN
# ============================================================

def familienaktivitaet_speichern(
    benutzer_id,
    symbol,
    text,
    ziel_benutzer_id=None
):

    erstellt_am = jetzt().replace(
        tzinfo=None
    )

    execute_query(
        """
        INSERT INTO familienaktivitaeten
        (
            benutzer_id,
            ziel_benutzer_id,
            symbol,
            text,
            erstellt_am
        )

        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s
        )
        """,
        """
        INSERT INTO familienaktivitaeten
        (
            benutzer_id,
            ziel_benutzer_id,
            symbol,
            text,
            erstellt_am
        )

        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        (
            benutzer_id,
            ziel_benutzer_id,
            symbol,
            text,
            erstellt_am
            if postgres_verwenden()
            else erstellt_am.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
    )


def letzte_familienaktivitaeten(
    benutzer_id,
    limit=5
):

    if postgres_verwenden():

        db = datenbank()

        try:

            cursor = db.cursor(
                cursor_factory=
                psycopg2.extras.RealDictCursor
            )

            cursor.execute(
                """
                SELECT
                    f.id,
                    f.symbol,
                    f.text,
                    TO_CHAR(
                        f.erstellt_am,
                        'DD.MM.YYYY HH24:MI'
                    ) AS erstellt_am,
                    b.benutzername

                FROM familienaktivitaeten f

                JOIN benutzer b
                    ON b.id = f.benutzer_id

                WHERE
                    f.ziel_benutzer_id IS NULL
                    OR f.ziel_benutzer_id = %s

                ORDER BY
                    f.erstellt_am DESC,
                    f.id DESC

                LIMIT %s
                """,
                (
                    benutzer_id,
                    limit
                )
            )

            ergebnis = cursor.fetchall()
            cursor.close()
            return ergebnis

        finally:
            db.close()

    return query_alle(
        "",
        """
        SELECT
            f.id,
            f.symbol,
            f.text,
            strftime(
                '%d.%m.%Y %H:%M',
                f.erstellt_am
            ) AS erstellt_am,
            b.benutzername

        FROM familienaktivitaeten f

        JOIN benutzer b
            ON b.id = f.benutzer_id

        WHERE
            f.ziel_benutzer_id IS NULL
            OR f.ziel_benutzer_id = ?

        ORDER BY
            f.erstellt_am DESC,
            f.id DESC

        LIMIT ?
        """,
        (
            benutzer_id,
            limit
        )
    )


# ============================================================
# PROFIL
# ============================================================

@app.route(
    "/profil",
    methods=[
        "GET",
        "POST"
    ]
)
def profil():

    if "benutzer_id" not in session:

        return redirect(
            "/"
        )

    benutzer_id = session[
        "benutzer_id"
    ]

    meldung = ""
    meldung_typ = ""

    benutzer = query_einen(
        """
        SELECT
            id,
            benutzername,
            rolle,
            passwort_hash

        FROM benutzer

        WHERE id = %s
        """,
        """
        SELECT
            id,
            benutzername,
            rolle,
            passwort_hash

        FROM benutzer

        WHERE id = ?
        """,
        (
            benutzer_id,
        )
    )

    if benutzer is None:

        session.clear()

        return redirect(
            "/"
        )

    if request.method == "POST":

        aktion = request.form.get(
            "aktion",
            ""
        ).strip()

        if aktion == "benutzername":

            neuer_name = request.form.get(
                "benutzername",
                ""
            ).strip()

            if len(
                neuer_name
            ) < 2:

                meldung = (
                    "Der Benutzername muss mindestens "
                    "2 Zeichen lang sein."
                )

                meldung_typ = "fehler"

            else:

                try:

                    execute_query(
                        """
                        UPDATE benutzer

                        SET benutzername = %s

                        WHERE id = %s
                        """,
                        """
                        UPDATE benutzer

                        SET benutzername = ?

                        WHERE id = ?
                        """,
                        (
                            neuer_name,
                            benutzer_id
                        )
                    )

                    session[
                        "benutzer"
                    ] = neuer_name

                    meldung = (
                        "Dein Benutzername wurde geändert."
                    )

                    meldung_typ = "erfolg"

                except Exception:

                    meldung = (
                        "Dieser Benutzername ist bereits vergeben."
                    )

                    meldung_typ = "fehler"


        elif aktion == "passwort":

            aktuelles_passwort = request.form.get(
                "aktuelles_passwort",
                ""
            )

            neues_passwort = request.form.get(
                "neues_passwort",
                ""
            )

            neues_passwort_wiederholen = request.form.get(
                "neues_passwort_wiederholen",
                ""
            )

            if not check_password_hash(
                benutzer["passwort_hash"],
                aktuelles_passwort
            ):

                meldung = (
                    "Das aktuelle Passwort ist nicht korrekt."
                )

                meldung_typ = "fehler"

            elif len(
                neues_passwort
            ) < 4:

                meldung = (
                    "Das neue Passwort muss mindestens "
                    "4 Zeichen lang sein."
                )

                meldung_typ = "fehler"

            elif (
                neues_passwort
                != neues_passwort_wiederholen
            ):

                meldung = (
                    "Die neuen Passwörter stimmen "
                    "nicht überein."
                )

                meldung_typ = "fehler"

            else:

                execute_query(
                    """
                    UPDATE benutzer

                    SET passwort_hash = %s,
                        passwort_muss_geaendert = FALSE

                    WHERE id = %s
                    """,
                    """
                    UPDATE benutzer

                    SET passwort_hash = ?,
                        passwort_muss_geaendert = 0

                    WHERE id = ?
                    """,
                    (
                        generate_password_hash(
                            neues_passwort
                        ),
                        benutzer_id
                    )
                )

                meldung = (
                    "Dein Passwort wurde erfolgreich geändert."
                )

                meldung_typ = "erfolg"


        benutzer = query_einen(
            """
            SELECT
                id,
                benutzername,
                rolle,
                passwort_hash

            FROM benutzer

            WHERE id = %s
            """,
            """
            SELECT
                id,
                benutzername,
                rolle,
                passwort_hash

            FROM benutzer

            WHERE id = ?
            """,
            (
                benutzer_id,
            )
        )

    return render_template(
        "profil.html",
        benutzer=
            benutzer,
        meldung=
            meldung,
        meldung_typ=
            meldung_typ
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route(
    "/dashboard"
)
def dashboard():

    if "benutzer_id" not in session:
        return redirect("/")

    if session.get(
        "passwort_muss_geaendert"
    ):

        return redirect(
            "/erstes-passwort"
        )

    benutzer_id = session[
        "benutzer_id"
    ]

    # ========================================================
    # KOMPAKTE DASHBOARD-ÜBERSICHT
    # ========================================================

    # Offene Aufgaben
    aufgaben_liste = aufgaben_fuer_benutzer(
        benutzer_id
    )

    offene_aufgaben = sum(
        1
        for aufgabe in aufgaben_liste
        if not bool(
            aufgabe["erledigt"]
        )
    )

    # Offene Einkaufsartikel
    einkauf_status = query_einen(

        """
        SELECT
            COUNT(*) AS anzahl

        FROM einkaufsliste

        WHERE
            benutzer_id = %s
            AND erledigt = FALSE
        """,

        """
        SELECT
            COUNT(*) AS anzahl

        FROM einkaufsliste

        WHERE
            benutzer_id = ?
            AND erledigt = 0
        """,

        (
            benutzer_id,
        )
    )

    offene_einkaeufe = int(
        einkauf_status["anzahl"] or 0
    )

    # Nächster Termin
    alle_termine = termine_fuer_benutzer(
        benutzer_id
    )

    naechster_termin = None
    heute_datum = heute()

    for termin in alle_termine:

        start_datum = datum_lesen(
            termin["start_datum"]
        )

        if start_datum >= heute_datum:

            naechster_termin = termin
            break

    if naechster_termin:

        termin_titel = (
            naechster_termin["titel"]
        )

        termin_datum = datum_als_anzeige(
            naechster_termin[
                "start_datum"
            ]
        )

        termin_zeit = (
            naechster_termin[
                "start_zeit"
            ]
            or ""
        )

    else:

        termin_titel = "Kein Termin"
        termin_datum = "–"
        termin_zeit = ""

    # Verfügbares Budget
    einstellungen = monatswechsel_pruefen(
        benutzer_id
    )

    standard_budget = float(
        einstellungen[
            "standard_budget"
        ]
    )

    uebertrag = float(
        einstellungen[
            "uebertrag"
        ]
    )

    periodenstart = datum_lesen(
        einstellungen[
            "periodenstart"
        ]
    )

    budget_summe = query_einen(

        """
        SELECT
            COALESCE(
                SUM(betrag),
                0
            ) AS summe

        FROM ausgaben

        WHERE
            benutzer_id = %s
            AND periodenstart = %s
        """,

        """
        SELECT
            COALESCE(
                SUM(betrag),
                0
            ) AS summe

        FROM ausgaben

        WHERE
            benutzer_id = ?
            AND periodenstart = ?
        """,

        (
            benutzer_id,

            periodenstart
            if postgres_verwenden()
            else periodenstart.isoformat()
        )
    )

    ausgegeben = float(
        budget_summe["summe"] or 0
    )

    verfuegbar = (
        standard_budget
        + uebertrag
        - ausgegeben
    )

    verfuegbar_text = (
        f"{verfuegbar:,.2f}"
        .replace(
            ",",
            "X"
        )
        .replace(
            ".",
            ","
        )
        .replace(
            "X",
            "."
        )
        + " €"
    )

    aktivitaeten = letzte_familienaktivitaeten(
        benutzer_id,
        5
    )

    return render_template(
        "dashboard.html",

        benutzer=session[
            "benutzer"
        ],

        rolle=session[
            "rolle"
        ],

        offene_aufgaben=
            offene_aufgaben,

        offene_einkaeufe=
            offene_einkaeufe,

        termin_titel=
            termin_titel,

        termin_datum=
            termin_datum,

        termin_zeit=
            termin_zeit,

        verfuegbar_text=
            verfuegbar_text,

        aktivitaeten=
            aktivitaeten
    )


# ============================================================
# AUFGABEN
# ============================================================

@app.route(
    "/aufgaben"
)
def aufgaben():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    kontakte = freigegebene_kontakte(
        benutzer_id
    )

    aufgaben_liste = (
        aufgaben_fuer_benutzer(
            benutzer_id
        )
    )

    offene_anzahl = 0
    erledigte_anzahl = 0

    for aufgabe in aufgaben_liste:

        if bool(
            aufgabe["erledigt"]
        ):

            erledigte_anzahl += 1

        else:

            offene_anzahl += 1

    return render_template(
        "aufgaben.html",

        benutzer=session[
            "benutzer"
        ],

        kontakte=kontakte,

        aufgaben=aufgaben_liste,

        offene_anzahl=
            offene_anzahl,

        erledigte_anzahl=
            erledigte_anzahl
    )


# ============================================================
# AUFGABE HINZUFÜGEN
# ============================================================

@app.route(
    "/aufgabe-hinzufuegen",
    methods=[
        "POST"
    ]
)
def aufgabe_hinzufuegen():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    titel = request.form.get(
        "titel",
        ""
    ).strip()

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    if titel == "":
        return redirect(
            "/aufgaben"
        )

    erlaubte_kontakte = (
        freigegebene_kontakte(
            benutzer_id
        )
    )

    erlaubte_ids = {
        int(person["id"])
        for person in erlaubte_kontakte
    }

    ausgewaehlt = []

    for wert in request.form.getlist(
        "geteilt_mit"
    ):

        try:
            ziel_id = int(wert)
        except ValueError:
            continue

        if ziel_id in erlaubte_ids:
            ausgewaehlt.append(
                ziel_id
            )

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                """
                INSERT INTO aufgaben
                (
                    ersteller_id,
                    titel,
                    beschreibung
                )

                VALUES (
                    %s,
                    %s,
                    %s
                )

                RETURNING id
                """,
                (
                    benutzer_id,
                    titel,
                    beschreibung
                )
            )

            aufgabe_id = (
                cursor.fetchone()[0]
            )

            for ziel_id in set(
                ausgewaehlt
            ):

                cursor.execute(
                    """
                    INSERT INTO aufgaben_geteilt
                    (
                        aufgabe_id,
                        benutzer_id
                    )

                    VALUES (
                        %s,
                        %s
                    )

                    ON CONFLICT
                    (
                        aufgabe_id,
                        benutzer_id
                    )

                    DO NOTHING
                    """,
                    (
                        aufgabe_id,
                        ziel_id
                    )
                )

            cursor.close()

        else:

            cursor = db.execute(
                """
                INSERT INTO aufgaben
                (
                    ersteller_id,
                    titel,
                    beschreibung,
                    erledigt,
                    erstellt_am
                )

                VALUES (
                    ?,
                    ?,
                    ?,
                    0,
                    ?
                )
                """,
                (
                    benutzer_id,
                    titel,
                    beschreibung,
                    jetzt().strftime(
                        "%d.%m.%Y %H:%M"
                    )
                )
            )

            aufgabe_id = (
                cursor.lastrowid
            )

            for ziel_id in set(
                ausgewaehlt
            ):

                db.execute(
                    """
                    INSERT OR IGNORE
                    INTO aufgaben_geteilt
                    (
                        aufgabe_id,
                        benutzer_id
                    )

                    VALUES (
                        ?,
                        ?
                    )
                    """,
                    (
                        aufgabe_id,
                        ziel_id
                    )
                )

        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()


    geteilte_ids = set(
        ausgewaehlt
    )

    if geteilte_ids:

        for ziel_id in geteilte_ids:

            push_an_benutzer(
                ziel_id,
                "Geteilte Aufgabe",
                (
                    "📋 "
                    + session.get(
                        "benutzer",
                        "Ein Familienmitglied"
                    )
                    + " hat die Aufgabe „"
                    + titel
                    + "“ mit dir geteilt."
                ),
                "/aufgaben"
            )

    else:

        push_an_benutzer(
            session["benutzer_id"],
            "Aufgaben",
            "✅ Eine Aufgabe wurde hinzugefügt.",
            "/aufgaben"
        )

    familienaktivitaet_speichern(
        session["benutzer_id"],
        "✅",
        "hat eine Aufgabe erstellt.",
        session["benutzer_id"]
    )

    for ziel_id in set(
        ausgewaehlt
    ):
        familienaktivitaet_speichern(
            session["benutzer_id"],
            "🤝",
            "hat eine Aufgabe mit dir geteilt.",
            ziel_id
        )

    return redirect(
        "/aufgaben"
    )


# ============================================================
# AUFGABENSTATUS
# ============================================================

@app.route(
    "/aufgabe-status/<int:aufgabe_id>",
    methods=[
        "POST"
    ]
)
def aufgabe_status(
    aufgabe_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    if not benutzer_darf_aufgabe_sehen(
        aufgabe_id,
        benutzer_id
    ):

        return redirect(
            "/aufgaben"
        )

    aufgabe = query_einen(

        """
        SELECT
            erledigt

        FROM aufgaben

        WHERE id = %s
        """,

        """
        SELECT
            erledigt

        FROM aufgaben

        WHERE id = ?
        """,

        (
            aufgabe_id,
        )
    )

    if aufgabe is None:

        return redirect(
            "/aufgaben"
        )

    neuer_status = not bool(
        aufgabe["erledigt"]
    )

    execute_query(

        """
        UPDATE aufgaben

        SET
            erledigt = %s,
            erledigt_von_id = %s

        WHERE id = %s
        """,

        """
        UPDATE aufgaben

        SET
            erledigt = ?,
            erledigt_von_id = ?

        WHERE id = ?
        """,

        (
            neuer_status
            if postgres_verwenden()
            else (
                1
                if neuer_status
                else 0
            ),

            benutzer_id
            if neuer_status
            else None,

            aufgabe_id
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Aufgaben",
        "✅ Der Status einer Aufgabe wurde geändert.",
        "/aufgaben"
    )

    return redirect(
        "/aufgaben"
    )


# ============================================================
# AUFGABE BEARBEITEN
# ============================================================

@app.route(
    "/aufgabe-bearbeiten/<int:aufgabe_id>",
    methods=[
        "POST"
    ]
)
def aufgabe_bearbeiten(
    aufgabe_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    if not benutzer_ist_ersteller(
        aufgabe_id,
        benutzer_id
    ):

        return redirect(
            "/aufgaben"
        )

    titel = request.form.get(
        "titel",
        ""
    ).strip()

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    if titel == "":

        return redirect(
            "/aufgaben"
        )

    erlaubte_kontakte = (
        freigegebene_kontakte(
            benutzer_id
        )
    )

    erlaubte_ids = {
        int(person["id"])
        for person in erlaubte_kontakte
    }

    neue_freigaben = []

    for wert in request.form.getlist(
        "geteilt_mit"
    ):

        try:
            ziel_id = int(wert)
        except ValueError:
            continue

        if ziel_id in erlaubte_ids:

            neue_freigaben.append(
                ziel_id
            )

    alte_freigaben = query_alle(

        """
        SELECT benutzer_id
        FROM aufgaben_geteilt
        WHERE aufgabe_id = %s
        """,

        """
        SELECT benutzer_id
        FROM aufgaben_geteilt
        WHERE aufgabe_id = ?
        """,

        (
            aufgabe_id,
        )
    )

    alte_freigabe_ids = {
        int(eintrag["benutzer_id"])
        for eintrag in alte_freigaben
    }

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                """
                UPDATE aufgaben

                SET
                    titel = %s,
                    beschreibung = %s

                WHERE
                    id = %s
                    AND ersteller_id = %s
                """,
                (
                    titel,
                    beschreibung,
                    aufgabe_id,
                    benutzer_id
                )
            )

            cursor.execute(
                """
                DELETE FROM aufgaben_geteilt
                WHERE aufgabe_id = %s
                """,
                (
                    aufgabe_id,
                )
            )

            for ziel_id in set(
                neue_freigaben
            ):

                cursor.execute(
                    """
                    INSERT INTO aufgaben_geteilt
                    (
                        aufgabe_id,
                        benutzer_id
                    )

                    VALUES (
                        %s,
                        %s
                    )

                    ON CONFLICT
                    (
                        aufgabe_id,
                        benutzer_id
                    )

                    DO NOTHING
                    """,
                    (
                        aufgabe_id,
                        ziel_id
                    )
                )

            cursor.close()

        else:

            db.execute(
                """
                UPDATE aufgaben

                SET
                    titel = ?,
                    beschreibung = ?

                WHERE
                    id = ?
                    AND ersteller_id = ?
                """,
                (
                    titel,
                    beschreibung,
                    aufgabe_id,
                    benutzer_id
                )
            )

            db.execute(
                """
                DELETE FROM aufgaben_geteilt
                WHERE aufgabe_id = ?
                """,
                (
                    aufgabe_id,
                )
            )

            for ziel_id in set(
                neue_freigaben
            ):

                db.execute(
                    """
                    INSERT OR IGNORE
                    INTO aufgaben_geteilt
                    (
                        aufgabe_id,
                        benutzer_id
                    )

                    VALUES (
                        ?,
                        ?
                    )
                    """,
                    (
                        aufgabe_id,
                        ziel_id
                    )
                )

        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()

    neue_geteilte_ids = (
        set(
            neue_freigaben
        )
        - alte_freigabe_ids
    )

    if neue_geteilte_ids:

        for ziel_id in neue_geteilte_ids:

            push_an_benutzer(
                ziel_id,
                "Geteilte Aufgabe",
                (
                    "📋 "
                    + session.get(
                        "benutzer",
                        "Ein Familienmitglied"
                    )
                    + " hat die Aufgabe „"
                    + titel
                    + "“ mit dir geteilt."
                ),
                "/aufgaben"
            )

    else:

        push_an_benutzer(
            session["benutzer_id"],
            "Aufgaben",
            "✏️ Eine Aufgabe wurde bearbeitet.",
            "/aufgaben"
        )

    return redirect(
        "/aufgaben"
    )


# ============================================================
# AUFGABE LÖSCHEN
# ============================================================

@app.route(
    "/aufgabe-loeschen/<int:aufgabe_id>",
    methods=[
        "POST"
    ]
)
def aufgabe_loeschen(
    aufgabe_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    execute_query(

        """
        DELETE FROM aufgaben

        WHERE
            id = %s
            AND ersteller_id = %s
        """,

        """
        DELETE FROM aufgaben

        WHERE
            id = ?
            AND ersteller_id = ?
        """,

        (
            aufgabe_id,
            benutzer_id
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Aufgaben",
        "🗑️ Eine Aufgabe wurde gelöscht.",
        "/aufgaben"
    )

    return redirect(
        "/aufgaben"
    )


# ============================================================
# KALENDER
# ============================================================

@app.route(
    "/kalender"
)
def kalender():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    kontakte = freigegebene_kontakte(
        benutzer_id
    )

    alle_termine = termine_fuer_benutzer(
        benutzer_id
    )

    kommende_termine = []
    vergangene_termine = []

    heute_datum = heute()

    for termin in alle_termine:

        start = datum_lesen(
            termin["start_datum"]
        )

        if termin["end_datum"]:
            ende = datum_lesen(
                termin["end_datum"]
            )
        else:
            ende = start

        if ende < heute_datum:
            vergangene_termine.append(
                termin
            )
        else:
            kommende_termine.append(
                termin
            )

    vergangene_termine.sort(
        key=lambda eintrag: (
            eintrag["start_datum"],
            eintrag["start_zeit"] or "00:00",
            eintrag["id"]
        ),
        reverse=True
    )

    return render_template(
        "kalender.html",
        benutzer=session[
            "benutzer"
        ],
        kontakte=kontakte,
        kommende_termine=kommende_termine,
        vergangene_termine=vergangene_termine,
        kommende_anzahl=len(
            kommende_termine
        ),
        vergangene_anzahl=len(
            vergangene_termine
        ),
        heute_iso=heute().isoformat()
    )


# ============================================================
# TERMIN HINZUFÜGEN
# ============================================================

@app.route(
    "/termin-hinzufuegen",
    methods=[
        "POST"
    ]
)
def termin_hinzufuegen():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    titel = request.form.get(
        "titel",
        ""
    ).strip()

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    start_datum_text = request.form.get(
        "start_datum",
        ""
    ).strip()

    start_zeit = request.form.get(
        "start_zeit",
        ""
    ).strip()

    end_datum_text = request.form.get(
        "end_datum",
        ""
    ).strip()

    end_zeit = request.form.get(
        "end_zeit",
        ""
    ).strip()

    if titel == "" or start_datum_text == "":
        return redirect(
            "/kalender"
        )

    try:
        start_datum = date.fromisoformat(
            start_datum_text
        )
    except ValueError:
        return redirect(
            "/kalender"
        )

    end_datum = None

    if end_datum_text:

        try:
            end_datum = date.fromisoformat(
                end_datum_text
            )
        except ValueError:
            return redirect(
                "/kalender"
            )

        if end_datum < start_datum:
            return redirect(
                "/kalender"
            )

    erlaubte_kontakte = (
        freigegebene_kontakte(
            benutzer_id
        )
    )

    erlaubte_ids = {
        int(person["id"])
        for person in erlaubte_kontakte
    }

    ausgewaehlt = []

    for wert in request.form.getlist(
        "geteilt_mit"
    ):

        try:
            ziel_id = int(wert)
        except ValueError:
            continue

        if ziel_id in erlaubte_ids:
            ausgewaehlt.append(
                ziel_id
            )

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                """
                INSERT INTO termine
                (
                    ersteller_id,
                    titel,
                    beschreibung,
                    start_datum,
                    start_zeit,
                    end_datum,
                    end_zeit
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )

                RETURNING id
                """,
                (
                    benutzer_id,
                    titel,
                    beschreibung,
                    start_datum,
                    start_zeit or None,
                    end_datum,
                    end_zeit or None
                )
            )

            termin_id = (
                cursor.fetchone()[0]
            )

            for ziel_id in set(
                ausgewaehlt
            ):

                cursor.execute(
                    """
                    INSERT INTO termine_geteilt
                    (
                        termin_id,
                        benutzer_id
                    )

                    VALUES (
                        %s,
                        %s
                    )

                    ON CONFLICT
                    (
                        termin_id,
                        benutzer_id
                    )

                    DO NOTHING
                    """,
                    (
                        termin_id,
                        ziel_id
                    )
                )

            cursor.close()

        else:

            cursor = db.execute(
                """
                INSERT INTO termine
                (
                    ersteller_id,
                    titel,
                    beschreibung,
                    start_datum,
                    start_zeit,
                    end_datum,
                    end_zeit,
                    erstellt_am
                )

                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    benutzer_id,
                    titel,
                    beschreibung,
                    start_datum.isoformat(),
                    start_zeit or None,
                    (
                        end_datum.isoformat()
                        if end_datum
                        else None
                    ),
                    end_zeit or None,
                    jetzt().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
            )

            termin_id = (
                cursor.lastrowid
            )

            for ziel_id in set(
                ausgewaehlt
            ):

                db.execute(
                    """
                    INSERT OR IGNORE
                    INTO termine_geteilt
                    (
                        termin_id,
                        benutzer_id
                    )

                    VALUES (
                        ?,
                        ?
                    )
                    """,
                    (
                        termin_id,
                        ziel_id
                    )
                )

        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()


    geteilte_ids = set(
        ausgewaehlt
    )

    if geteilte_ids:

        for ziel_id in geteilte_ids:

            push_an_benutzer(
                ziel_id,
                "Geteilter Termin",
                (
                    "📅 "
                    + session.get(
                        "benutzer",
                        "Ein Familienmitglied"
                    )
                    + " hat den Termin „"
                    + titel
                    + "“ mit dir geteilt."
                ),
                "/kalender"
            )

    else:

        push_an_benutzer(
            session["benutzer_id"],
            "Kalender",
            "📅 Ein Termin wurde hinzugefügt.",
            "/kalender"
        )

    familienaktivitaet_speichern(
        session["benutzer_id"],
        "📅",
        "hat einen Termin erstellt.",
        session["benutzer_id"]
    )

    for ziel_id in set(
        ausgewaehlt
    ):
        familienaktivitaet_speichern(
            session["benutzer_id"],
            "🤝",
            "hat einen Termin mit dir geteilt.",
            ziel_id
        )

    return redirect(
        "/kalender"
    )


# ============================================================
# TERMIN BEARBEITEN
# ============================================================

@app.route(
    "/termin-bearbeiten/<int:termin_id>",
    methods=[
        "POST"
    ]
)
def termin_bearbeiten(
    termin_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    if not termin_ist_ersteller(
        termin_id,
        benutzer_id
    ):

        return redirect(
            "/kalender"
        )

    titel = request.form.get(
        "titel",
        ""
    ).strip()

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    start_datum_text = request.form.get(
        "start_datum",
        ""
    ).strip()

    start_zeit = request.form.get(
        "start_zeit",
        ""
    ).strip()

    end_datum_text = request.form.get(
        "end_datum",
        ""
    ).strip()

    end_zeit = request.form.get(
        "end_zeit",
        ""
    ).strip()

    if titel == "" or start_datum_text == "":
        return redirect(
            "/kalender"
        )

    try:
        start_datum = date.fromisoformat(
            start_datum_text
        )
    except ValueError:
        return redirect(
            "/kalender"
        )

    end_datum = None

    if end_datum_text:

        try:
            end_datum = date.fromisoformat(
                end_datum_text
            )
        except ValueError:
            return redirect(
                "/kalender"
            )

        if end_datum < start_datum:
            return redirect(
                "/kalender"
            )

    erlaubte_kontakte = (
        freigegebene_kontakte(
            benutzer_id
        )
    )

    erlaubte_ids = {
        int(person["id"])
        for person in erlaubte_kontakte
    }

    neue_freigaben = []

    for wert in request.form.getlist(
        "geteilt_mit"
    ):

        try:
            ziel_id = int(wert)
        except ValueError:
            continue

        if ziel_id in erlaubte_ids:
            neue_freigaben.append(
                ziel_id
            )

    alte_freigaben = query_alle(

        """
        SELECT benutzer_id
        FROM termine_geteilt
        WHERE termin_id = %s
        """,

        """
        SELECT benutzer_id
        FROM termine_geteilt
        WHERE termin_id = ?
        """,

        (
            termin_id,
        )
    )

    alte_freigabe_ids = {
        int(eintrag["benutzer_id"])
        for eintrag in alte_freigaben
    }

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                """
                UPDATE termine

                SET
                    titel = %s,
                    beschreibung = %s,
                    start_datum = %s,
                    start_zeit = %s,
                    end_datum = %s,
                    end_zeit = %s

                WHERE
                    id = %s
                    AND ersteller_id = %s
                """,
                (
                    titel,
                    beschreibung,
                    start_datum,
                    start_zeit or None,
                    end_datum,
                    end_zeit or None,
                    termin_id,
                    benutzer_id
                )
            )

            cursor.execute(
                """
                DELETE FROM termine_geteilt
                WHERE termin_id = %s
                """,
                (
                    termin_id,
                )
            )

            for ziel_id in set(
                neue_freigaben
            ):

                cursor.execute(
                    """
                    INSERT INTO termine_geteilt
                    (
                        termin_id,
                        benutzer_id
                    )

                    VALUES (
                        %s,
                        %s
                    )

                    ON CONFLICT
                    (
                        termin_id,
                        benutzer_id
                    )

                    DO NOTHING
                    """,
                    (
                        termin_id,
                        ziel_id
                    )
                )

            cursor.close()

        else:

            db.execute(
                """
                UPDATE termine

                SET
                    titel = ?,
                    beschreibung = ?,
                    start_datum = ?,
                    start_zeit = ?,
                    end_datum = ?,
                    end_zeit = ?

                WHERE
                    id = ?
                    AND ersteller_id = ?
                """,
                (
                    titel,
                    beschreibung,
                    start_datum.isoformat(),
                    start_zeit or None,
                    (
                        end_datum.isoformat()
                        if end_datum
                        else None
                    ),
                    end_zeit or None,
                    termin_id,
                    benutzer_id
                )
            )

            db.execute(
                """
                DELETE FROM termine_geteilt
                WHERE termin_id = ?
                """,
                (
                    termin_id,
                )
            )

            for ziel_id in set(
                neue_freigaben
            ):

                db.execute(
                    """
                    INSERT OR IGNORE
                    INTO termine_geteilt
                    (
                        termin_id,
                        benutzer_id
                    )

                    VALUES (
                        ?,
                        ?
                    )
                    """,
                    (
                        termin_id,
                        ziel_id
                    )
                )

        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()

    neue_geteilte_ids = (
        set(
            neue_freigaben
        )
        - alte_freigabe_ids
    )

    if neue_geteilte_ids:

        for ziel_id in neue_geteilte_ids:

            push_an_benutzer(
                ziel_id,
                "Geteilter Termin",
                (
                    "📅 "
                    + session.get(
                        "benutzer",
                        "Ein Familienmitglied"
                    )
                    + " hat den Termin „"
                    + titel
                    + "“ mit dir geteilt."
                ),
                "/kalender"
            )

    else:

        push_an_benutzer(
            session["benutzer_id"],
            "Kalender",
            "✏️ Ein Termin wurde bearbeitet.",
            "/kalender"
        )

    return redirect(
        "/kalender"
    )


# ============================================================
# TERMIN LÖSCHEN
# ============================================================

@app.route(
    "/termin-loeschen/<int:termin_id>",
    methods=[
        "POST"
    ]
)
def termin_loeschen(
    termin_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    execute_query(

        """
        DELETE FROM termine

        WHERE
            id = %s
            AND ersteller_id = %s
        """,

        """
        DELETE FROM termine

        WHERE
            id = ?
            AND ersteller_id = ?
        """,

        (
            termin_id,
            benutzer_id
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Kalender",
        "🗑️ Ein Termin wurde gelöscht.",
        "/kalender"
    )

    return redirect(
        "/kalender"
    )


# ============================================================
# ADMIN AUFGABEN-FREIGABEN
# ============================================================

@app.route(
    "/admin/aufgaben-freigaben"
)
def admin_aufgaben_freigaben():

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    benutzer_liste_roh = query_alle(

        """
        SELECT
            id,
            benutzername,
            rolle

        FROM benutzer

        ORDER BY
            benutzername
        """,

        """
        SELECT
            id,
            benutzername,
            rolle

        FROM benutzer

        ORDER BY
            benutzername
        """
    )

    benutzer_liste = []

    for person in benutzer_liste_roh:

        freigaben = query_alle(

            """
            SELECT
                CASE

                    WHEN benutzer_id_1 = %s
                    THEN benutzer_id_2

                    ELSE benutzer_id_1

                END AS kontakt_id

            FROM aufgaben_freigaben

            WHERE
                benutzer_id_1 = %s
                OR
                benutzer_id_2 = %s
            """,

            """
            SELECT
                CASE

                    WHEN benutzer_id_1 = ?
                    THEN benutzer_id_2

                    ELSE benutzer_id_1

                END AS kontakt_id

            FROM aufgaben_freigaben

            WHERE
                benutzer_id_1 = ?
                OR
                benutzer_id_2 = ?
            """,

            (
                person["id"],
                person["id"],
                person["id"]
            )
        )

        daten = dict(
            person
        )

        daten[
            "freigabe_ids"
        ] = [
            int(eintrag[
                "kontakt_id"
            ])
            for eintrag in freigaben
        ]

        benutzer_liste.append(
            daten
        )

    return render_template(
        "admin_aufgaben_freigaben.html",

        benutzer_liste=
            benutzer_liste,

        meldung=request.args.get(
            "meldung",
            ""
        )
    )


@app.route(
    "/admin/aufgaben-freigaben/<int:benutzer_id>",
    methods=[
        "POST"
    ]
)
def admin_aufgaben_freigaben_speichern(
    benutzer_id
):

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    person = query_einen(

        """
        SELECT id
        FROM benutzer
        WHERE id = %s
        """,

        """
        SELECT id
        FROM benutzer
        WHERE id = ?
        """,

        (
            benutzer_id,
        )
    )

    if person is None:

        return redirect(
            "/admin/aufgaben-freigaben"
        )

    alle_benutzer = query_alle(

        """
        SELECT id
        FROM benutzer
        WHERE id != %s
        """,

        """
        SELECT id
        FROM benutzer
        WHERE id != ?
        """,

        (
            benutzer_id,
        )
    )

    erlaubte_ids = {
        int(person["id"])
        for person in alle_benutzer
    }

    ausgewaehlt = set()

    for wert in request.form.getlist(
        "freigaben"
    ):

        try:
            andere_id = int(wert)
        except ValueError:
            continue

        if andere_id in erlaubte_ids:

            ausgewaehlt.add(
                andere_id
            )

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute(
                """
                DELETE FROM aufgaben_freigaben

                WHERE
                    benutzer_id_1 = %s
                    OR
                    benutzer_id_2 = %s
                """,
                (
                    benutzer_id,
                    benutzer_id
                )
            )

            for andere_id in ausgewaehlt:

                kleiner = min(
                    benutzer_id,
                    andere_id
                )

                groesser = max(
                    benutzer_id,
                    andere_id
                )

                cursor.execute(
                    """
                    INSERT INTO aufgaben_freigaben
                    (
                        benutzer_id_1,
                        benutzer_id_2
                    )

                    VALUES (
                        %s,
                        %s
                    )

                    ON CONFLICT
                    (
                        benutzer_id_1,
                        benutzer_id_2
                    )

                    DO NOTHING
                    """,
                    (
                        kleiner,
                        groesser
                    )
                )

            cursor.close()

        else:

            db.execute(
                """
                DELETE FROM aufgaben_freigaben

                WHERE
                    benutzer_id_1 = ?
                    OR
                    benutzer_id_2 = ?
                """,
                (
                    benutzer_id,
                    benutzer_id
                )
            )

            for andere_id in ausgewaehlt:

                kleiner = min(
                    benutzer_id,
                    andere_id
                )

                groesser = max(
                    benutzer_id,
                    andere_id
                )

                db.execute(
                    """
                    INSERT OR IGNORE
                    INTO aufgaben_freigaben
                    (
                        benutzer_id_1,
                        benutzer_id_2
                    )

                    VALUES (
                        ?,
                        ?
                    )
                    """,
                    (
                        kleiner,
                        groesser
                    )
                )

        # Aufgabenfreigaben entfernen,
        # wenn die Benutzer nicht mehr miteinander
        # teilen dürfen.

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute("""
                DELETE FROM aufgaben_geteilt ag

                USING aufgaben a

                WHERE
                    ag.aufgabe_id = a.id

                    AND
                    (
                        a.ersteller_id = %s
                        OR
                        ag.benutzer_id = %s
                    )

                    AND NOT EXISTS
                    (
                        SELECT 1

                        FROM aufgaben_freigaben f

                        WHERE
                            (
                                f.benutzer_id_1 =
                                LEAST(
                                    a.ersteller_id,
                                    ag.benutzer_id
                                )

                                AND

                                f.benutzer_id_2 =
                                GREATEST(
                                    a.ersteller_id,
                                    ag.benutzer_id
                                )
                            )
                    )
            """,
            (
                benutzer_id,
                benutzer_id
            ))

            cursor.close()

        else:

            geteilte = db.execute(
                """
                SELECT
                    ag.id,
                    a.ersteller_id,
                    ag.benutzer_id

                FROM aufgaben_geteilt ag

                JOIN aufgaben a
                    ON a.id =
                       ag.aufgabe_id

                WHERE
                    a.ersteller_id = ?
                    OR
                    ag.benutzer_id = ?
                """,
                (
                    benutzer_id,
                    benutzer_id
                )
            ).fetchall()

            for eintrag in geteilte:

                kleiner = min(
                    eintrag[
                        "ersteller_id"
                    ],
                    eintrag[
                        "benutzer_id"
                    ]
                )

                groesser = max(
                    eintrag[
                        "ersteller_id"
                    ],
                    eintrag[
                        "benutzer_id"
                    ]
                )

                erlaubt = db.execute(
                    """
                    SELECT id

                    FROM aufgaben_freigaben

                    WHERE
                        benutzer_id_1 = ?
                        AND
                        benutzer_id_2 = ?
                    """,
                    (
                        kleiner,
                        groesser
                    )
                ).fetchone()

                if erlaubt is None:

                    db.execute(
                        """
                        DELETE FROM aufgaben_geteilt
                        WHERE id = ?
                        """,
                        (
                            eintrag["id"],
                        )
                    )

        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()

    return redirect(
        "/admin/aufgaben-freigaben"
        "?meldung=Freigaben wurden gespeichert."
    )


# ============================================================
# EINKAUFSLISTE
# ============================================================

@app.route(
    "/einkaufsliste"
)
def einkaufsliste():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    eintraege = query_alle(

        """
        SELECT
            id,
            artikel,
            menge,
            notiz,
            erledigt,

            TO_CHAR(
                erstellt_am,
                'DD.MM.YYYY HH24:MI'
            ) AS erstellt_am

        FROM einkaufsliste

        WHERE benutzer_id = %s

        ORDER BY
            erledigt ASC,
            id DESC
        """,

        """
        SELECT
            id,
            artikel,
            menge,
            notiz,
            erledigt,
            erstellt_am

        FROM einkaufsliste

        WHERE benutzer_id = ?

        ORDER BY
            erledigt ASC,
            id DESC
        """,

        (
            benutzer_id,
        )
    )

    offene_anzahl = 0
    erledigte_anzahl = 0

    for eintrag in eintraege:

        if bool(
            eintrag["erledigt"]
        ):
            erledigte_anzahl += 1
        else:
            offene_anzahl += 1

    return render_template(
        "einkaufsliste.html",

        benutzer=session[
            "benutzer"
        ],

        eintraege=eintraege,

        offene_anzahl=
            offene_anzahl,

        erledigte_anzahl=
            erledigte_anzahl
    )


@app.route(
    "/einkauf-hinzufuegen",
    methods=["POST"]
)
def einkauf_hinzufuegen():

    if "benutzer_id" not in session:
        return redirect("/")

    artikel = request.form.get(
        "artikel",
        ""
    ).strip()

    menge = request.form.get(
        "menge",
        ""
    ).strip()

    notiz = request.form.get(
        "notiz",
        ""
    ).strip()

    if artikel == "":

        return redirect(
            "/einkaufsliste"
        )

    if postgres_verwenden():

        execute_query(

            """
            INSERT INTO einkaufsliste
            (
                benutzer_id,
                artikel,
                menge,
                notiz
            )

            VALUES (
                %s,
                %s,
                %s,
                %s
            )
            """,

            "",

            (
                session[
                    "benutzer_id"
                ],
                artikel,
                menge,
                notiz
            )
        )

    else:

        execute_query(

            "",

            """
            INSERT INTO einkaufsliste
            (
                benutzer_id,
                artikel,
                menge,
                notiz,
                erledigt,
                erstellt_am
            )

            VALUES (
                ?,
                ?,
                ?,
                ?,
                0,
                ?
            )
            """,

            (
                session[
                    "benutzer_id"
                ],
                artikel,
                menge,
                notiz,
                jetzt().strftime(
                    "%d.%m.%Y %H:%M"
                )
            )
        )

    push_an_benutzer(
        session["benutzer_id"],
        "Einkaufsliste",
        "🛒 Ein Artikel wurde hinzugefügt.",
        "/einkaufsliste"
    )

    return redirect(
        "/einkaufsliste"
    )


@app.route(
    "/einkauf-status/<int:eintrag_id>",
    methods=["POST"]
)
def einkauf_status(
    eintrag_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    eintrag = query_einen(

        """
        SELECT erledigt
        FROM einkaufsliste

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        SELECT erledigt
        FROM einkaufsliste

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            eintrag_id,
            benutzer_id
        )
    )

    if eintrag is None:

        return redirect(
            "/einkaufsliste"
        )

    neuer_status = not bool(
        eintrag["erledigt"]
    )

    execute_query(

        """
        UPDATE einkaufsliste

        SET erledigt = %s

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        UPDATE einkaufsliste

        SET erledigt = ?

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            neuer_status
            if postgres_verwenden()
            else (
                1
                if neuer_status
                else 0
            ),

            eintrag_id,
            benutzer_id
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Einkaufsliste",
        "✅ Der Status eines Artikels wurde geändert.",
        "/einkaufsliste"
    )

    return redirect(
        "/einkaufsliste"
    )


@app.route(
    "/einkauf-bearbeiten/<int:eintrag_id>",
    methods=["POST"]
)
def einkauf_bearbeiten(
    eintrag_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    artikel = request.form.get(
        "artikel",
        ""
    ).strip()

    menge = request.form.get(
        "menge",
        ""
    ).strip()

    notiz = request.form.get(
        "notiz",
        ""
    ).strip()

    if artikel == "":

        return redirect(
            "/einkaufsliste"
        )

    execute_query(

        """
        UPDATE einkaufsliste

        SET
            artikel = %s,
            menge = %s,
            notiz = %s

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        UPDATE einkaufsliste

        SET
            artikel = ?,
            menge = ?,
            notiz = ?

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            artikel,
            menge,
            notiz,
            eintrag_id,
            benutzer_id
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Einkaufsliste",
        "✏️ Ein Artikel wurde bearbeitet.",
        "/einkaufsliste"
    )

    return redirect(
        "/einkaufsliste"
    )


@app.route(
    "/einkauf-loeschen/<int:eintrag_id>",
    methods=["POST"]
)
def einkauf_loeschen(
    eintrag_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    execute_query(

        """
        DELETE FROM einkaufsliste

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        DELETE FROM einkaufsliste

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            eintrag_id,
            session[
                "benutzer_id"
            ]
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Einkaufsliste",
        "🗑️ Ein Artikel wurde gelöscht.",
        "/einkaufsliste"
    )

    return redirect(
        "/einkaufsliste"
    )


@app.route(
    "/einkauf-erledigte-loeschen",
    methods=["POST"]
)
def einkauf_erledigte_loeschen():

    if "benutzer_id" not in session:
        return redirect("/")

    execute_query(

        """
        DELETE FROM einkaufsliste

        WHERE
            benutzer_id = %s
            AND erledigt = TRUE
        """,

        """
        DELETE FROM einkaufsliste

        WHERE
            benutzer_id = ?
            AND erledigt = 1
        """,

        (
            session[
                "benutzer_id"
            ],
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Einkaufsliste",
        "🧹 Erledigte Artikel wurden gelöscht.",
        "/einkaufsliste"
    )

    return redirect(
        "/einkaufsliste"
    )


# ============================================================
# FINANZEN
# ============================================================

@app.route(
    "/finanzen"
)
def finanzen():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    einstellungen = (
        monatswechsel_pruefen(
            benutzer_id
        )
    )

    standard_budget = float(
        einstellungen[
            "standard_budget"
        ]
    )

    uebertrag = float(
        einstellungen[
            "uebertrag"
        ]
    )

    reset_tag = int(
        einstellungen[
            "reset_tag"
        ]
    )

    periodenstart = datum_lesen(
        einstellungen[
            "periodenstart"
        ]
    )

    budget = (
        standard_budget
        + uebertrag
    )

    summe = query_einen(

        """
        SELECT
            COALESCE(
                SUM(betrag),
                0
            ) AS summe

        FROM ausgaben

        WHERE
            benutzer_id = %s
            AND periodenstart = %s
        """,

        """
        SELECT
            COALESCE(
                SUM(betrag),
                0
            ) AS summe

        FROM ausgaben

        WHERE
            benutzer_id = ?
            AND periodenstart = ?
        """,

        (
            benutzer_id,

            periodenstart
            if postgres_verwenden()
            else periodenstart.isoformat()
        )
    )

    ausgegeben = float(
        summe["summe"] or 0
    )

    verfuegbar = (
        budget - ausgegeben
    )

    if budget > 0:

        prozent_verbraucht = (
            ausgegeben
            / budget
            * 100
        )

        prozent_verbraucht = min(
            max(
                prozent_verbraucht,
                0
            ),
            100
        )

    else:

        prozent_verbraucht = 0

    ausgaben = query_alle(

        """
        SELECT
            id,
            beschreibung,
            kategorie,
            betrag,
            ist_fix,

            TO_CHAR(
                datum,
                'DD.MM.YYYY HH24:MI'
            ) AS datum

        FROM ausgaben

        WHERE
            benutzer_id = %s
            AND periodenstart = %s

        ORDER BY
            datum DESC
        """,

        """
        SELECT
            id,
            beschreibung,
            kategorie,
            betrag,
            ist_fix,
            datum

        FROM ausgaben

        WHERE
            benutzer_id = ?
            AND periodenstart = ?

        ORDER BY
            id DESC
        """,

        (
            benutzer_id,

            periodenstart
            if postgres_verwenden()
            else periodenstart.isoformat()
        )
    )

    naechster_reset = (
        naechster_periodenstart(
            periodenstart,
            reset_tag
        )
    )

    return render_template(
        "finanzen.html",

        benutzer=session[
            "benutzer"
        ],

        standard_budget=
            standard_budget,

        uebertrag=
            uebertrag,

        budget=
            budget,

        ausgegeben=
            ausgegeben,

        verfuegbar=
            verfuegbar,

        prozent_verbraucht=
            prozent_verbraucht,

        reset_tag=
            reset_tag,

        naechster_reset=
            naechster_reset.strftime(
                "%d.%m.%Y"
            ),

        ausgaben=
            ausgaben
    )


@app.route(
    "/finanz-einstellungen-speichern",
    methods=["POST"]
)
def finanz_einstellungen_speichern():

    if "benutzer_id" not in session:
        return redirect("/")

    try:

        standard_budget = float(
            request.form.get(
                "standard_budget",
                "0"
            )
        )

        reset_tag = int(
            request.form.get(
                "reset_tag",
                "1"
            )
        )

    except ValueError:

        return redirect(
            "/finanzen"
        )

    standard_budget = max(
        standard_budget,
        0
    )

    reset_tag = max(
        1,
        min(
            reset_tag,
            28
        )
    )

    execute_query(

        """
        UPDATE finanz_einstellungen

        SET
            standard_budget = %s,
            reset_tag = %s

        WHERE benutzer_id = %s
        """,

        """
        UPDATE finanz_einstellungen

        SET
            standard_budget = ?,
            reset_tag = ?

        WHERE benutzer_id = ?
        """,

        (
            standard_budget,
            reset_tag,
            session[
                "benutzer_id"
            ]
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Finanzen",
        "💶 Deine Budget-Einstellungen wurden geändert.",
        "/finanzen"
    )

    return redirect(
        "/finanzen"
    )


@app.route(
    "/budget-speichern",
    methods=["POST"]
)
def budget_speichern():

    if "benutzer_id" not in session:
        return redirect("/")

    try:

        betrag = float(
            request.form.get(
                "budget",
                "0"
            )
        )

    except ValueError:

        return redirect(
            "/finanzen"
        )

    finanz_einstellungen_sicherstellen(
        session[
            "benutzer_id"
        ]
    )

    execute_query(

        """
        UPDATE finanz_einstellungen

        SET standard_budget = %s

        WHERE benutzer_id = %s
        """,

        """
        UPDATE finanz_einstellungen

        SET standard_budget = ?

        WHERE benutzer_id = ?
        """,

        (
            max(
                betrag,
                0
            ),

            session[
                "benutzer_id"
            ]
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Finanzen",
        "💶 Dein Budget wurde aktualisiert.",
        "/finanzen"
    )

    return redirect(
        "/finanzen"
    )


@app.route(
    "/ausgabe-hinzufuegen",
    methods=["POST"]
)
def ausgabe_hinzufuegen():

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    einstellungen = (
        monatswechsel_pruefen(
            benutzer_id
        )
    )

    periodenstart = datum_lesen(
        einstellungen[
            "periodenstart"
        ]
    )

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    kategorie = request.form.get(
        "kategorie",
        ""
    ).strip()

    try:

        betrag = float(
            request.form.get(
                "betrag",
                "0"
            )
        )

    except ValueError:

        return redirect(
            "/finanzen"
        )

    ist_fix = (
        request.form.get(
            "ist_fix"
        )
        == "on"
    )

    if (
        beschreibung == ""
        or
        betrag <= 0
    ):

        return redirect(
            "/finanzen"
        )

    if postgres_verwenden():

        execute_query(

            """
            INSERT INTO ausgaben
            (
                benutzer_id,
                beschreibung,
                kategorie,
                betrag,
                ist_fix,
                periodenstart
            )

            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,

            "",

            (
                benutzer_id,
                beschreibung,
                kategorie,
                betrag,
                ist_fix,
                periodenstart
            )
        )

    else:

        execute_query(

            "",

            """
            INSERT INTO ausgaben
            (
                benutzer_id,
                beschreibung,
                kategorie,
                betrag,
                datum,
                ist_fix,
                periodenstart
            )

            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,

            (
                benutzer_id,
                beschreibung,
                kategorie,
                betrag,

                jetzt().strftime(
                    "%d.%m.%Y %H:%M"
                ),

                1
                if ist_fix
                else 0,

                periodenstart.isoformat()
            )
        )

    push_an_benutzer(
        session["benutzer_id"],
        "Finanzen",
        "💶 Eine Ausgabe wurde hinzugefügt.",
        "/finanzen"
    )

    return redirect(
        "/finanzen"
    )


@app.route(
    "/ausgabe-bearbeiten/<int:ausgabe_id>",
    methods=["POST"]
)
def ausgabe_bearbeiten(
    ausgabe_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    benutzer_id = session[
        "benutzer_id"
    ]

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    kategorie = request.form.get(
        "kategorie",
        ""
    ).strip()

    ist_fix = (
        request.form.get(
            "ist_fix"
        )
        == "on"
    )

    try:

        betrag = float(
            request.form.get(
                "betrag",
                "0"
            )
        )

    except ValueError:

        return redirect(
            "/finanzen"
        )

    if (
        beschreibung == ""
        or
        betrag <= 0
    ):

        return redirect(
            "/finanzen"
        )

    execute_query(

        """
        UPDATE ausgaben

        SET
            beschreibung = %s,
            kategorie = %s,
            betrag = %s,
            ist_fix = %s

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        UPDATE ausgaben

        SET
            beschreibung = ?,
            kategorie = ?,
            betrag = ?,
            ist_fix = ?

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            beschreibung,
            kategorie,
            betrag,

            ist_fix
            if postgres_verwenden()
            else (
                1
                if ist_fix
                else 0
            ),

            ausgabe_id,
            benutzer_id
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Finanzen",
        "✏️ Eine Ausgabe wurde bearbeitet.",
        "/finanzen"
    )

    return redirect(
        "/finanzen"
    )


@app.route(
    "/ausgabe-loeschen/<int:ausgabe_id>",
    methods=["POST"]
)
def ausgabe_loeschen(
    ausgabe_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    execute_query(

        """
        DELETE FROM ausgaben

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        DELETE FROM ausgaben

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            ausgabe_id,

            session[
                "benutzer_id"
            ]
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Finanzen",
        "🗑️ Eine Ausgabe wurde gelöscht.",
        "/finanzen"
    )

    return redirect(
        "/finanzen"
    )


# ============================================================
# VERBESSERUNGSVORSCHLÄGE
# ============================================================

@app.route(
    "/vorschlag",
    methods=[
        "GET",
        "POST"
    ]
)
def vorschlag():

    if "benutzer_id" not in session:
        return redirect("/")

    if session.get(
        "rolle"
    ) == "admin":

        return redirect(
            "/admin/vorschlaege"
        )

    benutzer_id = session[
        "benutzer_id"
    ]

    meldung = ""
    fehler = ""

    if request.method == "POST":

        titel = request.form.get(
            "titel",
            ""
        ).strip()

        beschreibung = request.form.get(
            "beschreibung",
            ""
        ).strip()

        if titel == "":

            fehler = (
                "Bitte gib einen Titel ein."
            )

        elif beschreibung == "":

            fehler = (
                "Bitte gib eine Beschreibung ein."
            )

        else:

            if postgres_verwenden():

                execute_query(

                    """
                    INSERT INTO verbesserungsvorschlaege
                    (
                        benutzer_id,
                        titel,
                        beschreibung,
                        status,
                        admin_notiz
                    )

                    VALUES (
                        %s,
                        %s,
                        %s,
                        'Neu',
                        ''
                    )
                    """,

                    "",

                    (
                        benutzer_id,
                        titel,
                        beschreibung
                    )
                )

            else:

                zeit = jetzt().strftime(
                    "%d.%m.%Y %H:%M"
                )

                execute_query(

                    "",

                    """
                    INSERT INTO verbesserungsvorschlaege
                    (
                        benutzer_id,
                        titel,
                        beschreibung,
                        status,
                        admin_notiz,
                        erstellt_am,
                        bearbeitet_am
                    )

                    VALUES (
                        ?,
                        ?,
                        ?,
                        'Neu',
                        '',
                        ?,
                        ?
                    )
                    """,

                    (
                        benutzer_id,
                        titel,
                        beschreibung,
                        zeit,
                        zeit
                    )
                )

            meldung = (
                "Dein Vorschlag wurde gesendet."
            )

    meine_vorschlaege = query_alle(

        """
        SELECT
            id,
            titel,
            beschreibung,
            status,
            admin_notiz,

            TO_CHAR(
                erstellt_am,
                'DD.MM.YYYY HH24:MI'
            ) AS erstellt_am,

            TO_CHAR(
                bearbeitet_am,
                'DD.MM.YYYY HH24:MI'
            ) AS bearbeitet_am

        FROM verbesserungsvorschlaege

        WHERE benutzer_id = %s

        ORDER BY id DESC
        """,

        """
        SELECT
            id,
            titel,
            beschreibung,
            status,
            admin_notiz,
            erstellt_am,
            bearbeitet_am

        FROM verbesserungsvorschlaege

        WHERE benutzer_id = ?

        ORDER BY id DESC
        """,

        (
            benutzer_id,
        )
    )

    return render_template(
        "vorschlag.html",

        benutzer=session[
            "benutzer"
        ],

        meldung=meldung,
        fehler=fehler,

        meine_vorschlaege=
            meine_vorschlaege
    )


@app.route(
    "/admin/vorschlaege"
)
def admin_vorschlaege():

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    vorschlaege = query_alle(

        """
        SELECT
            v.id,
            v.titel,
            v.beschreibung,
            v.status,
            v.admin_notiz,

            b.benutzername,

            TO_CHAR(
                v.erstellt_am,
                'DD.MM.YYYY HH24:MI'
            ) AS erstellt_am,

            TO_CHAR(
                v.bearbeitet_am,
                'DD.MM.YYYY HH24:MI'
            ) AS bearbeitet_am

        FROM verbesserungsvorschlaege v

        JOIN benutzer b
            ON b.id =
               v.benutzer_id

        ORDER BY
            CASE v.status
                WHEN 'Neu' THEN 1
                WHEN 'In Prüfung' THEN 2
                WHEN 'Geplant' THEN 3
                WHEN 'Erledigt' THEN 4
                WHEN 'Abgelehnt' THEN 5
                ELSE 6
            END,

            v.id DESC
        """,

        """
        SELECT
            v.id,
            v.titel,
            v.beschreibung,
            v.status,
            v.admin_notiz,

            b.benutzername,

            v.erstellt_am,
            v.bearbeitet_am

        FROM verbesserungsvorschlaege v

        JOIN benutzer b
            ON b.id =
               v.benutzer_id

        ORDER BY
            v.id DESC
        """
    )

    return render_template(
        "admin_vorschlaege.html",

        vorschlaege=
            vorschlaege
    )


@app.route(
    "/admin/vorschlag-bearbeiten/<int:vorschlag_id>",
    methods=["POST"]
)
def admin_vorschlag_bearbeiten(
    vorschlag_id
):

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    titel = request.form.get(
        "titel",
        ""
    ).strip()

    beschreibung = request.form.get(
        "beschreibung",
        ""
    ).strip()

    status = request.form.get(
        "status",
        "Neu"
    ).strip()

    admin_notiz = request.form.get(
        "admin_notiz",
        ""
    ).strip()

    erlaubte_status = [
        "Neu",
        "In Prüfung",
        "Geplant",
        "Erledigt",
        "Abgelehnt"
    ]

    if status not in erlaubte_status:

        status = "Neu"

    if (
        titel == ""
        or
        beschreibung == ""
    ):

        return redirect(
            "/admin/vorschlaege"
        )

    if postgres_verwenden():

        execute_query(

            """
            UPDATE verbesserungsvorschlaege

            SET
                titel = %s,
                beschreibung = %s,
                status = %s,
                admin_notiz = %s,
                bearbeitet_am =
                    CURRENT_TIMESTAMP

            WHERE id = %s
            """,

            "",

            (
                titel,
                beschreibung,
                status,
                admin_notiz,
                vorschlag_id
            )
        )

    else:

        execute_query(

            "",

            """
            UPDATE verbesserungsvorschlaege

            SET
                titel = ?,
                beschreibung = ?,
                status = ?,
                admin_notiz = ?,
                bearbeitet_am = ?

            WHERE id = ?
            """,

            (
                titel,
                beschreibung,
                status,
                admin_notiz,

                jetzt().strftime(
                    "%d.%m.%Y %H:%M"
                ),

                vorschlag_id
            )
        )

    return redirect(
        "/admin/vorschlaege"
    )


@app.route(
    "/admin/vorschlag-loeschen/<int:vorschlag_id>",
    methods=["POST"]
)
def admin_vorschlag_loeschen(
    vorschlag_id
):

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    execute_query(

        """
        DELETE FROM verbesserungsvorschlaege
        WHERE id = %s
        """,

        """
        DELETE FROM verbesserungsvorschlaege
        WHERE id = ?
        """,

        (
            vorschlag_id,
        )
    )

    return redirect(
        "/admin/vorschlaege"
    )


# ============================================================
# ADMIN BENUTZER
# ============================================================

@app.route(
    "/admin",
    methods=[
        "GET",
        "POST"
    ]
)
def admin():

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    meldung = ""

    if request.method == "POST":

        neuer_name = request.form.get(
            "benutzername",
            ""
        ).strip()

        einmalpasswort = request.form.get(
            "passwort",
            ""
        )

        if neuer_name == "":

            meldung = (
                "Bitte einen Benutzernamen eingeben."
            )

        elif len(
            einmalpasswort
        ) < 4:

            meldung = (
                "Das Einmalpasswort muss mindestens 4 Zeichen haben."
            )

        else:

            try:

                execute_query(

                    """
                    INSERT INTO benutzer
                    (
                        benutzername,
                        passwort,
                        rolle,
                        passwort_muss_geaendert
                    )

                    VALUES (
                        %s,
                        %s,
                        'benutzer',
                        TRUE
                    )
                    """,

                    """
                    INSERT INTO benutzer
                    (
                        benutzername,
                        passwort,
                        rolle,
                        passwort_muss_geaendert
                    )

                    VALUES (
                        ?,
                        ?,
                        'benutzer',
                        1
                    )
                    """,

                    (
                        neuer_name,

                        generate_password_hash(
                            einmalpasswort
                        )
                    )
                )

                meldung = (
                    "Benutzer wurde erstellt."
                )

            except Exception:

                meldung = (
                    "Dieser Benutzername existiert bereits."
                )

    benutzer_liste = query_alle(

        """
        SELECT
            id,
            benutzername,
            rolle,
            passwort_muss_geaendert

        FROM benutzer

        ORDER BY id
        """,

        """
        SELECT
            id,
            benutzername,
            rolle,
            passwort_muss_geaendert

        FROM benutzer

        ORDER BY id
        """
    )

    return render_template(
        "admin.html",

        benutzer_liste=
            benutzer_liste,

        meldung=
            meldung
    )


@app.route(
    "/benutzername-aendern/<int:benutzer_id>",
    methods=[
        "GET",
        "POST"
    ]
)
def benutzername_aendern(
    benutzer_id
):

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    benutzer = query_einen(

        """
        SELECT *
        FROM benutzer
        WHERE id = %s
        """,

        """
        SELECT *
        FROM benutzer
        WHERE id = ?
        """,

        (
            benutzer_id,
        )
    )

    if benutzer is None:

        return redirect(
            "/admin"
        )

    meldung = ""

    if request.method == "POST":

        neuer_name = request.form.get(
            "benutzername",
            ""
        ).strip()

        if neuer_name == "":

            meldung = (
                "Bitte einen Benutzernamen eingeben."
            )

        else:

            try:

                execute_query(

                    """
                    UPDATE benutzer

                    SET benutzername = %s

                    WHERE id = %s
                    """,

                    """
                    UPDATE benutzer

                    SET benutzername = ?

                    WHERE id = ?
                    """,

                    (
                        neuer_name,
                        benutzer_id
                    )
                )

                if (
                    session.get(
                        "benutzer_id"
                    )
                    == benutzer_id
                ):

                    session[
                        "benutzer"
                    ] = neuer_name

                meldung = (
                    "Benutzername wurde geändert."
                )

                benutzer = query_einen(

                    """
                    SELECT *
                    FROM benutzer
                    WHERE id = %s
                    """,

                    """
                    SELECT *
                    FROM benutzer
                    WHERE id = ?
                    """,

                    (
                        benutzer_id,
                    )
                )

            except Exception:

                meldung = (
                    "Dieser Benutzername existiert bereits."
                )

    return render_template(
        "benutzername.html",

        benutzer=
            benutzer,

        meldung=
            meldung
    )


@app.route(
    "/passwort-aendern/<int:benutzer_id>",
    methods=[
        "GET",
        "POST"
    ]
)
def passwort_aendern(
    benutzer_id
):

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    benutzer = query_einen(

        """
        SELECT *
        FROM benutzer
        WHERE id = %s
        """,

        """
        SELECT *
        FROM benutzer
        WHERE id = ?
        """,

        (
            benutzer_id,
        )
    )

    if benutzer is None:

        return redirect(
            "/admin"
        )

    meldung = ""

    if request.method == "POST":

        neues_passwort = request.form.get(
            "passwort",
            ""
        )

        if len(
            neues_passwort
        ) < 4:

            meldung = (
                "Das Passwort muss mindestens 4 Zeichen haben."
            )

        else:

            muss_geaendert = (
                benutzer["rolle"]
                != "admin"
            )

            execute_query(

                """
                UPDATE benutzer

                SET
                    passwort = %s,
                    passwort_muss_geaendert = %s

                WHERE id = %s
                """,

                """
                UPDATE benutzer

                SET
                    passwort = ?,
                    passwort_muss_geaendert = ?

                WHERE id = ?
                """,

                (
                    generate_password_hash(
                        neues_passwort
                    ),

                    muss_geaendert
                    if postgres_verwenden()
                    else (
                        1
                        if muss_geaendert
                        else 0
                    ),

                    benutzer_id
                )
            )

            if muss_geaendert:

                meldung = (
                    "Neues Einmalpasswort wurde gesetzt."
                )

            else:

                meldung = (
                    "Admin-Passwort wurde geändert."
                )

    return render_template(
        "passwort.html",

        benutzer=
            benutzer,

        meldung=
            meldung
    )


@app.route(
    "/benutzer-loeschen/<int:benutzer_id>",
    methods=["POST"]
)
def benutzer_loeschen(
    benutzer_id
):

    if session.get(
        "rolle"
    ) != "admin":

        return redirect(
            "/dashboard"
        )

    benutzer = query_einen(

        """
        SELECT *
        FROM benutzer
        WHERE id = %s
        """,

        """
        SELECT *
        FROM benutzer
        WHERE id = ?
        """,

        (
            benutzer_id,
        )
    )

    if (
        benutzer
        and
        benutzer["rolle"]
        != "admin"
    ):

        execute_query(

            """
            DELETE FROM benutzer
            WHERE id = %s
            """,

            """
            DELETE FROM benutzer
            WHERE id = ?
            """,

            (
                benutzer_id,
            )
        )

    return redirect(
        "/admin"
    )


# ============================================================
# FAMILIEN-PINNWAND
# ============================================================

@app.route(
    "/pinnwand"
)
def pinnwand():

    if "benutzer_id" not in session:
        return redirect("/")

    beitraege = query_alle(

        """
        SELECT
            p.id,
            p.benutzer_id,
            p.inhalt,
            p.wichtig,

            TO_CHAR(
                p.erstellt_am,
                'DD.MM.YYYY HH24:MI'
            ) AS erstellt_am,

            b.benutzername

        FROM pinnwand p

        JOIN benutzer b
            ON b.id = p.benutzer_id

        ORDER BY
            p.wichtig DESC,
            p.erstellt_am DESC,
            p.id DESC
        """,

        """
        SELECT
            p.id,
            p.benutzer_id,
            p.inhalt,
            p.wichtig,

            strftime(
                '%d.%m.%Y %H:%M',
                p.erstellt_am
            ) AS erstellt_am,

            b.benutzername

        FROM pinnwand p

        JOIN benutzer b
            ON b.id = p.benutzer_id

        ORDER BY
            p.wichtig DESC,
            p.erstellt_am DESC,
            p.id DESC
        """
    )

    eigene_id = int(
        session["benutzer_id"]
    )

    ergebnis = []

    for beitrag in beitraege:

        daten = dict(
            beitrag
        )

        daten["ist_eigener"] = (
            int(
                beitrag["benutzer_id"]
            )
            == eigene_id
        )

        daten["wichtig"] = bool(
            beitrag["wichtig"]
        )

        ergebnis.append(
            daten
        )

    return render_template(
        "pinnwand.html",

        benutzer=session[
            "benutzer"
        ],

        beitraege=ergebnis,

        anzahl=len(
            ergebnis
        ),

        wichtige_anzahl=sum(
            1
            for beitrag in ergebnis
            if beitrag["wichtig"]
        )
    )


@app.route(
    "/pinnwand-hinzufuegen",
    methods=["POST"]
)
def pinnwand_hinzufuegen():

    if "benutzer_id" not in session:
        return redirect("/")

    inhalt = request.form.get(
        "inhalt",
        ""
    ).strip()

    if not inhalt:
        return redirect(
            "/pinnwand"
        )

    inhalt = inhalt[:1200]

    wichtig = (
        request.form.get(
            "wichtig"
        )
        == "1"
    )

    erstellt_am = jetzt().replace(
        tzinfo=None
    )

    execute_query(

        """
        INSERT INTO pinnwand
        (
            benutzer_id,
            inhalt,
            wichtig,
            erstellt_am
        )

        VALUES (
            %s,
            %s,
            %s,
            %s
        )
        """,

        """
        INSERT INTO pinnwand
        (
            benutzer_id,
            inhalt,
            wichtig,
            erstellt_am
        )

        VALUES (
            ?,
            ?,
            ?,
            ?
        )
        """,

        (
            session[
                "benutzer_id"
            ],

            inhalt,

            wichtig
            if postgres_verwenden()
            else (
                1
                if wichtig
                else 0
            ),

            erstellt_am
            if postgres_verwenden()
            else erstellt_am.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Familien-Pinnwand",
        "📌 Deine Nachricht wurde angepinnt.",
        "/pinnwand"
    )

    familienaktivitaet_speichern(
        session["benutzer_id"],
        "📌",
        "hat etwas an die Pinnwand geschrieben."
    )

    return redirect(
        "/pinnwand"
    )


@app.route(
    "/pinnwand-wichtig/<int:beitrag_id>",
    methods=["POST"]
)
def pinnwand_wichtig(
    beitrag_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    beitrag = query_einen(

        """
        SELECT
            id,
            wichtig

        FROM pinnwand

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        SELECT
            id,
            wichtig

        FROM pinnwand

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            beitrag_id,
            session[
                "benutzer_id"
            ]
        )
    )

    if beitrag is None:
        return redirect(
            "/pinnwand"
        )

    neuer_wert = not bool(
        beitrag["wichtig"]
    )

    execute_query(

        """
        UPDATE pinnwand

        SET wichtig = %s

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        UPDATE pinnwand

        SET wichtig = ?

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            neuer_wert
            if postgres_verwenden()
            else (
                1
                if neuer_wert
                else 0
            ),

            beitrag_id,

            session[
                "benutzer_id"
            ]
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Familien-Pinnwand",
        "⭐ Der Wichtig-Status wurde geändert.",
        "/pinnwand"
    )

    return redirect(
        "/pinnwand"
    )


@app.route(
    "/pinnwand-loeschen/<int:beitrag_id>",
    methods=["POST"]
)
def pinnwand_loeschen(
    beitrag_id
):

    if "benutzer_id" not in session:
        return redirect("/")

    execute_query(

        """
        DELETE FROM pinnwand

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        DELETE FROM pinnwand

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            beitrag_id,
            session[
                "benutzer_id"
            ]
        )
    )

    push_an_benutzer(
        session["benutzer_id"],
        "Familien-Pinnwand",
        "🗑️ Deine Nachricht wurde gelöscht.",
        "/pinnwand"
    )

    return redirect(
        "/pinnwand"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route(
    "/logout"
)
def logout():

    session.clear()

    return redirect(
        "/"
    )


# ============================================================
# START
# ============================================================

datenbank_erstellen()


if __name__ == "__main__":

    app.run(
        debug=True
    )
