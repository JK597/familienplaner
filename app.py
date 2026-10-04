import os
import sqlite3
from datetime import date, datetime
from calendar import monthrange
from zoneinfo import ZoneInfo

from flask import Flask, request, redirect, session, render_template
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


app = Flask(__name__)


# ==================================================
# EINSTELLUNGEN
# ==================================================

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


# ==================================================
# DATUM / ZEIT
# ==================================================

def heute():
    return datetime.now(
        ZoneInfo("Europe/Berlin")
    ).date()


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
        min(28, int(reset_tag))
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
        min(28, int(reset_tag))
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


# ==================================================
# DATENBANK
# ==================================================

def postgres_verwenden():
    return bool(DATABASE_URL)


def datenbank():

    if postgres_verwenden():

        if psycopg2 is None:
            raise RuntimeError(
                "DATABASE_URL ist gesetzt, "
                "aber psycopg2 fehlt."
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


# ==================================================
# TABELLEN ERSTELLEN / AKTUALISIEREN
# ==================================================

def datenbank_erstellen():

    db = datenbank()

    try:

        # ==========================================
        # POSTGRESQL
        # ==========================================

        if postgres_verwenden():

            cursor = db.cursor()


            # --------------------------
            # BENUTZER
            # --------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS benutzer (
                    id SERIAL PRIMARY KEY,

                    benutzername VARCHAR(100)
                        UNIQUE NOT NULL,

                    passwort TEXT NOT NULL,

                    rolle VARCHAR(50)
                        NOT NULL,

                    passwort_muss_geaendert
                        BOOLEAN NOT NULL
                        DEFAULT FALSE
                )
            """)


            cursor.execute("""
                ALTER TABLE benutzer
                ADD COLUMN IF NOT EXISTS
                passwort_muss_geaendert
                BOOLEAN NOT NULL
                DEFAULT FALSE
            """)


            # --------------------------
            # FINANZ-EINSTELLUNGEN
            # --------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS
                finanz_einstellungen
                (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER
                        UNIQUE NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    standard_budget
                        NUMERIC(12,2)
                        NOT NULL
                        DEFAULT 0,

                    uebertrag
                        NUMERIC(12,2)
                        NOT NULL
                        DEFAULT 0,

                    reset_tag INTEGER
                        NOT NULL
                        DEFAULT 1,

                    periodenstart DATE
                        NOT NULL
                        DEFAULT CURRENT_DATE
                )
            """)


            # --------------------------
            # AUSGABEN
            # --------------------------

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ausgaben (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER
                        NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    beschreibung VARCHAR(255)
                        NOT NULL,

                    kategorie VARCHAR(100)
                        NOT NULL,

                    betrag NUMERIC(12,2)
                        NOT NULL,

                    datum TIMESTAMP
                        NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    ist_fix BOOLEAN
                        NOT NULL
                        DEFAULT FALSE,

                    periodenstart DATE
                )
            """)


            cursor.execute("""
                ALTER TABLE ausgaben
                ADD COLUMN IF NOT EXISTS
                ist_fix BOOLEAN
                NOT NULL
                DEFAULT FALSE
            """)


            cursor.execute("""
                ALTER TABLE ausgaben
                ADD COLUMN IF NOT EXISTS
                periodenstart DATE
            """)


            cursor.execute("""
                UPDATE ausgaben

                SET periodenstart =
                    CURRENT_DATE

                WHERE periodenstart
                    IS NULL
            """)


            # --------------------------
            # ALTEN BUDGET-WERT
            # ÜBERNEHMEN
            # --------------------------

            cursor.execute("""
                SELECT to_regclass(
                    'public.budgets'
                )
            """)

            budgets_existiert = (
                cursor.fetchone()[0]
            )

            if budgets_existiert:

                cursor.execute("""
                    INSERT INTO
                        finanz_einstellungen
                    (
                        benutzer_id,
                        standard_budget,
                        uebertrag,
                        reset_tag,
                        periodenstart
                    )

                    SELECT
                        benutzer_id,
                        betrag,
                        0,
                        1,
                        CURRENT_DATE

                    FROM budgets

                    ON CONFLICT
                        (benutzer_id)

                    DO NOTHING
                """)


            cursor.close()


        # ==========================================
        # SQLITE
        # ==========================================

        else:

            # --------------------------
            # BENUTZER
            # --------------------------

            db.execute("""
                CREATE TABLE IF NOT EXISTS benutzer (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    benutzername TEXT
                        UNIQUE NOT NULL,

                    passwort TEXT NOT NULL,

                    rolle TEXT NOT NULL,

                    passwort_muss_geaendert
                        INTEGER NOT NULL
                        DEFAULT 0
                )
            """)


            spalten = db.execute(
                "PRAGMA table_info(benutzer)"
            ).fetchall()

            spalten_namen = [
                spalte["name"]
                for spalte in spalten
            ]

            if (
                "passwort_muss_geaendert"
                not in spalten_namen
            ):

                db.execute("""
                    ALTER TABLE benutzer

                    ADD COLUMN
                    passwort_muss_geaendert
                    INTEGER NOT NULL
                    DEFAULT 0
                """)


            # --------------------------
            # FINANZEN
            # --------------------------

            db.execute("""
                CREATE TABLE IF NOT EXISTS
                finanz_einstellungen
                (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    benutzer_id INTEGER
                        UNIQUE NOT NULL,

                    standard_budget REAL
                        NOT NULL DEFAULT 0,

                    uebertrag REAL
                        NOT NULL DEFAULT 0,

                    reset_tag INTEGER
                        NOT NULL DEFAULT 1,

                    periodenstart TEXT
                        NOT NULL,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)


            # --------------------------
            # AUSGABEN
            # --------------------------

            db.execute("""
                CREATE TABLE IF NOT EXISTS ausgaben (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    benutzer_id INTEGER
                        NOT NULL,

                    beschreibung TEXT
                        NOT NULL,

                    kategorie TEXT
                        NOT NULL,

                    betrag REAL
                        NOT NULL,

                    datum TEXT
                        NOT NULL,

                    ist_fix INTEGER
                        NOT NULL
                        DEFAULT 0,

                    periodenstart TEXT,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)


            ausgaben_spalten = db.execute(
                "PRAGMA table_info(ausgaben)"
            ).fetchall()

            ausgaben_spalten_namen = [
                spalte["name"]
                for spalte
                in ausgaben_spalten
            ]


            if (
                "ist_fix"
                not in ausgaben_spalten_namen
            ):

                db.execute("""
                    ALTER TABLE ausgaben

                    ADD COLUMN
                    ist_fix INTEGER
                    NOT NULL DEFAULT 0
                """)


            if (
                "periodenstart"
                not in ausgaben_spalten_namen
            ):

                db.execute("""
                    ALTER TABLE ausgaben

                    ADD COLUMN
                    periodenstart TEXT
                """)


            db.execute(
                """
                UPDATE ausgaben

                SET periodenstart = ?

                WHERE periodenstart
                    IS NULL
                """,
                (
                    heute().isoformat(),
                )
            )


            # Alten Budgetwert übernehmen

            budgets_tabelle = db.execute(
                """
                SELECT name

                FROM sqlite_master

                WHERE
                    type = 'table'
                    AND name = 'budgets'
                """
            ).fetchone()


            if budgets_tabelle:

                alte_budgets = db.execute(
                    """
                    SELECT
                        benutzer_id,
                        betrag

                    FROM budgets
                    """
                ).fetchall()


                for alter_wert in alte_budgets:

                    vorhanden = db.execute(
                        """
                        SELECT id

                        FROM finanz_einstellungen

                        WHERE benutzer_id = ?
                        """,
                        (
                            alter_wert[
                                "benutzer_id"
                            ],
                        )
                    ).fetchone()


                    if vorhanden is None:

                        db.execute(
                            """
                            INSERT INTO
                                finanz_einstellungen
                            (
                                benutzer_id,
                                standard_budget,
                                uebertrag,
                                reset_tag,
                                periodenstart
                            )

                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                alter_wert[
                                    "benutzer_id"
                                ],

                                alter_wert[
                                    "betrag"
                                ],

                                0,

                                1,

                                heute().isoformat()
                            )
                        )


        db.commit()


    finally:

        db.close()


    # ==============================================
    # ADMIN ERSTELLEN
    # ==============================================

    admin = query_einen(

        """
        SELECT *

        FROM benutzer

        WHERE rolle = %s

        LIMIT 1
        """,

        """
        SELECT *

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

            VALUES (?, ?, ?, 0)
            """,

            (
                "joel",

                generate_password_hash(
                    ADMIN_PASSWORD
                ),

                "admin"
            )
        )


# ==================================================
# FINANZ-EINSTELLUNGEN SICHERSTELLEN
# ==================================================

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
            %s,
            %s,
            %s,
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

        VALUES (?, ?, ?, ?, ?)
        """,

        (
            benutzer_id,
            0,
            0,
            1,
            start
            if postgres_verwenden()
            else start.isoformat()
        )
    )


    return finanz_einstellungen_sicherstellen(
        benutzer_id
    )


# ==================================================
# MONATS-RESET
# ==================================================

def monatswechsel_pruefen(
    benutzer_id
):

    einstellungen = (
        finanz_einstellungen_sicherstellen(
            benutzer_id
        )
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


    aktuelles_datum = heute()


    while True:

        naechster_start = (
            naechster_periodenstart(
                periodenstart,
                reset_tag
            )
        )


        if (
            naechster_start
            > aktuelles_datum
        ):

            break


        # ------------------------------------------
        # AUSGABEN DER ALTEN PERIODE
        # ------------------------------------------

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


        aktuelles_budget = (
            standard_budget
            + uebertrag
        )


        rest = (
            aktuelles_budget
            - ausgegeben
        )


        # Nur positives Restbudget
        # wird gutgeschrieben

        neuer_uebertrag = max(
            rest,
            0
        )


        # ------------------------------------------
        # FIXKOSTEN DER ALTEN PERIODE
        # ------------------------------------------

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


        # ------------------------------------------
        # NEUE PERIODE SETZEN
        # ------------------------------------------

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


        # ------------------------------------------
        # FIXKOSTEN AUTOMATISCH
        # NEU EINTRAGEN
        # ------------------------------------------

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

                        datetime.now().strftime(
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


# ==================================================
# LOGIN
# ==================================================

@app.route(
    "/",
    methods=[
        "GET",
        "POST"
    ]
)
def login():

    fehler = ""


    if request.method == "POST":

        benutzername = request.form[
            "benutzername"
        ].strip()

        passwort = request.form[
            "passwort"
        ]


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
            and check_password_hash(
                benutzer[
                    "passwort"
                ],
                passwort
            )
        ):

            session[
                "benutzer_id"
            ] = benutzer[
                "id"
            ]

            session[
                "benutzer"
            ] = benutzer[
                "benutzername"
            ]

            session[
                "rolle"
            ] = benutzer[
                "rolle"
            ]

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
            "Benutzername oder "
            "Passwort falsch."
        )


    return render_template(
        "login.html",
        fehler=fehler
    )


# ==================================================
# ERSTES EIGENES PASSWORT
# ==================================================

@app.route(
    "/erstes-passwort",
    methods=[
        "GET",
        "POST"
    ]
)
def erstes_passwort():

    if (
        "benutzer_id"
        not in session
    ):

        return redirect("/")


    if not session.get(
        "passwort_muss_geaendert"
    ):

        return redirect(
            "/dashboard"
        )


    fehler = ""


    if request.method == "POST":

        passwort1 = request.form[
            "passwort"
        ]

        passwort2 = request.form[
            "passwort_wiederholen"
        ]


        if len(passwort1) < 6:

            fehler = (
                "Das Passwort muss "
                "mindestens 6 Zeichen haben."
            )


        elif passwort1 != passwort2:

            fehler = (
                "Die Passwörter stimmen "
                "nicht überein."
            )


        else:

            benutzer_id = session[
                "benutzer_id"
            ]


            execute_query(

                """
                UPDATE benutzer

                SET
                    passwort = %s,

                    passwort_muss_geaendert
                        = FALSE

                WHERE id = %s
                """,

                """
                UPDATE benutzer

                SET
                    passwort = ?,

                    passwort_muss_geaendert
                        = 0

                WHERE id = ?
                """,

                (
                    generate_password_hash(
                        passwort1
                    ),

                    benutzer_id
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


# ==================================================
# DASHBOARD
# ==================================================

@app.route("/dashboard")
def dashboard():

    if (
        "benutzer_id"
        not in session
    ):

        return redirect("/")


    if session.get(
        "passwort_muss_geaendert"
    ):

        return redirect(
            "/erstes-passwort"
        )


    return render_template(
        "dashboard.html",

        benutzer=session[
            "benutzer"
        ],

        rolle=session[
            "rolle"
        ]
    )


# ==================================================
# FINANZEN
# ==================================================

@app.route("/finanzen")
def finanzen():

    if (
        "benutzer_id"
        not in session
    ):

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


# ==================================================
# FINANZ-EINSTELLUNGEN SPEICHERN
# ==================================================

@app.route(
    "/finanz-einstellungen-speichern",
    methods=[
        "POST"
    ]
)
def finanz_einstellungen_speichern():

    if (
        "benutzer_id"
        not in session
    ):

        return redirect("/")


    benutzer_id = session[
        "benutzer_id"
    ]


    try:

        standard_budget = float(
            request.form[
                "standard_budget"
            ]
        )

        reset_tag = int(
            request.form[
                "reset_tag"
            ]
        )

    except (
        ValueError,
        KeyError
    ):

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


    finanz_einstellungen_sicherstellen(
        benutzer_id
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
            benutzer_id
        )
    )


    return redirect(
        "/finanzen"
    )


# Alter Link bleibt kompatibel

@app.route(
    "/budget-speichern",
    methods=[
        "POST"
    ]
)
def budget_speichern():

    if (
        "benutzer_id"
        not in session
    ):

        return redirect("/")


    benutzer_id = session[
        "benutzer_id"
    ]


    try:

        betrag = float(
            request.form[
                "budget"
            ]
        )

    except (
        ValueError,
        KeyError
    ):

        return redirect(
            "/finanzen"
        )


    finanz_einstellungen_sicherstellen(
        benutzer_id
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

            benutzer_id
        )
    )


    return redirect(
        "/finanzen"
    )


# ==================================================
# AUSGABE HINZUFÜGEN
# ==================================================

@app.route(
    "/ausgabe-hinzufuegen",
    methods=[
        "POST"
    ]
)
def ausgabe_hinzufuegen():

    if (
        "benutzer_id"
        not in session
    ):

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


    beschreibung = request.form[
        "beschreibung"
    ].strip()


    kategorie = request.form[
        "kategorie"
    ].strip()


    ist_fix = (
        request.form.get(
            "ist_fix"
        )
        == "on"
    )


    try:

        betrag = float(
            request.form[
                "betrag"
            ]
        )

    except ValueError:

        return redirect(
            "/finanzen"
        )


    if (
        beschreibung == ""
        or betrag <= 0
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

                datetime.now().strftime(
                    "%d.%m.%Y %H:%M"
                ),

                1
                if ist_fix
                else 0,

                periodenstart.isoformat()
            )
        )


    return redirect(
        "/finanzen"
    )


# ==================================================
# AUSGABE BEARBEITEN
# ==================================================

@app.route(
    "/ausgabe-bearbeiten/<int:ausgabe_id>",
    methods=[
        "POST"
    ]
)
def ausgabe_bearbeiten(
    ausgabe_id
):

    if (
        "benutzer_id"
        not in session
    ):

        return redirect("/")


    benutzer_id = session[
        "benutzer_id"
    ]


    ausgabe = query_einen(

        """
        SELECT *

        FROM ausgaben

        WHERE
            id = %s
            AND benutzer_id = %s
        """,

        """
        SELECT *

        FROM ausgaben

        WHERE
            id = ?
            AND benutzer_id = ?
        """,

        (
            ausgabe_id,
            benutzer_id
        )
    )


    if ausgabe is None:

        return redirect(
            "/finanzen"
        )


    beschreibung = request.form[
        "beschreibung"
    ].strip()


    kategorie = request.form[
        "kategorie"
    ].strip()


    ist_fix = (
        request.form.get(
            "ist_fix"
        )
        == "on"
    )


    try:

        betrag = float(
            request.form[
                "betrag"
            ]
        )

    except ValueError:

        return redirect(
            "/finanzen"
        )


    if (
        beschreibung == ""
        or betrag <= 0
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


    return redirect(
        "/finanzen"
    )


# ==================================================
# AUSGABE LÖSCHEN
# ==================================================

@app.route(
    "/ausgabe-loeschen/<int:ausgabe_id>",
    methods=[
        "POST"
    ]
)
def ausgabe_loeschen(
    ausgabe_id
):

    if (
        "benutzer_id"
        not in session
    ):

        return redirect("/")


    benutzer_id = session[
        "benutzer_id"
    ]


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
            benutzer_id
        )
    )


    return redirect(
        "/finanzen"
    )


# ==================================================
# ADMIN
# ==================================================

@app.route(
    "/admin",
    methods=[
        "GET",
        "POST"
    ]
)
def admin():

    if (
        session.get("rolle")
        != "admin"
    ):

        return redirect(
            "/dashboard"
        )


    meldung = ""


    if request.method == "POST":

        neuer_name = request.form[
            "benutzername"
        ].strip()

        einmalpasswort = request.form[
            "passwort"
        ]


        if neuer_name == "":

            meldung = (
                "Bitte einen "
                "Benutzernamen eingeben."
            )


        elif len(
            einmalpasswort
        ) < 4:

            meldung = (
                "Das Einmalpasswort muss "
                "mindestens 4 Zeichen haben."
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
                        %s,
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
                        ?,
                        1
                    )
                    """,

                    (
                        neuer_name,

                        generate_password_hash(
                            einmalpasswort
                        ),

                        "benutzer"
                    )
                )


                meldung = (
                    "Benutzer wurde erstellt. "
                    "Das Passwort ist ein "
                    "Einmalpasswort."
                )


            except Exception:

                meldung = (
                    "Dieser Benutzername "
                    "existiert bereits."
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


# ==================================================
# BENUTZERNAME ÄNDERN
# ==================================================

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

    if (
        session.get("rolle")
        != "admin"
    ):

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

        neuer_name = request.form[
            "benutzername"
        ].strip()


        if neuer_name == "":

            meldung = (
                "Bitte einen "
                "Benutzernamen eingeben."
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


                meldung = (
                    "Benutzername wurde "
                    "dauerhaft geändert."
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
                    "Dieser Benutzername "
                    "existiert bereits."
                )


    return render_template(
        "benutzername.html",
        benutzer=benutzer,
        meldung=meldung
    )


# ==================================================
# PASSWORT / EINMALPASSWORT
# ==================================================

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

    if (
        session.get("rolle")
        != "admin"
    ):

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

        neues_passwort = request.form[
            "passwort"
        ]


        if len(
            neues_passwort
        ) < 4:

            meldung = (
                "Das Passwort muss "
                "mindestens 4 Zeichen haben."
            )


        else:

            if (
                benutzer["rolle"]
                != "admin"
            ):

                execute_query(

                    """
                    UPDATE benutzer

                    SET
                        passwort = %s,

                        passwort_muss_geaendert
                            = TRUE

                    WHERE id = %s
                    """,

                    """
                    UPDATE benutzer

                    SET
                        passwort = ?,

                        passwort_muss_geaendert
                            = 1

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
                    "Neues Einmalpasswort "
                    "wurde gesetzt."
                )


            else:

                execute_query(

                    """
                    UPDATE benutzer

                    SET passwort = %s

                    WHERE id = %s
                    """,

                    """
                    UPDATE benutzer

                    SET passwort = ?

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
                    "Admin-Passwort "
                    "wurde geändert."
                )


    return render_template(
        "passwort.html",
        benutzer=benutzer,
        meldung=meldung
    )


# ==================================================
# BENUTZER LÖSCHEN
# ==================================================

@app.route(
    "/benutzer-loeschen/<int:benutzer_id>",
    methods=[
        "POST"
    ]
)
def benutzer_loeschen(
    benutzer_id
):

    if (
        session.get("rolle")
        != "admin"
    ):

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
        and benutzer[
            "rolle"
        ] != "admin"
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


# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ==================================================
# START
# ==================================================

datenbank_erstellen()


if __name__ == "__main__":

    app.run(
        debug=True
    )