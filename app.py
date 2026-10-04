import os
import sqlite3
from datetime import datetime

from flask import Flask, request, redirect, session, render_template
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None


app = Flask(__name__)


# --------------------------------------------------
# EINSTELLUNGEN
# --------------------------------------------------

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


# --------------------------------------------------
# DATENBANK
# --------------------------------------------------

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


# --------------------------------------------------
# TABELLEN
# --------------------------------------------------

def datenbank_erstellen():

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS benutzer (
                    id SERIAL PRIMARY KEY,
                    benutzername VARCHAR(100)
                        UNIQUE NOT NULL,
                    passwort TEXT NOT NULL,
                    rolle VARCHAR(50) NOT NULL,
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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    id SERIAL PRIMARY KEY,

                    benutzer_id INTEGER
                        UNIQUE NOT NULL
                        REFERENCES benutzer(id)
                        ON DELETE CASCADE,

                    betrag NUMERIC(12,2)
                        NOT NULL DEFAULT 0
                )
            """)

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
                        DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.close()

        else:

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

            db.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    id INTEGER PRIMARY KEY
                        AUTOINCREMENT,

                    benutzer_id INTEGER
                        UNIQUE NOT NULL,

                    betrag REAL
                        NOT NULL DEFAULT 0,

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

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

                    FOREIGN KEY (benutzer_id)
                    REFERENCES benutzer(id)
                    ON DELETE CASCADE
                )
            """)

        db.commit()

    finally:

        db.close()


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

        ("admin",)
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
                %s
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

            VALUES (?, ?, ?, ?)
            """,

            (
                "joel",

                generate_password_hash(
                    ADMIN_PASSWORD
                ),

                "admin",

                False
            )
        )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

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
                benutzer["passwort"],
                passwort
            )
        ):

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


# --------------------------------------------------
# ERSTES EIGENES PASSWORT
# --------------------------------------------------

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


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

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


# --------------------------------------------------
# FINANZEN
# --------------------------------------------------

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


    budget_datensatz = query_einen(

        """
        SELECT betrag
        FROM budgets
        WHERE benutzer_id = %s
        """,

        """
        SELECT betrag
        FROM budgets
        WHERE benutzer_id = ?
        """,

        (
            benutzer_id,
        )
    )


    if budget_datensatz:

        budget = float(
            budget_datensatz[
                "betrag"
            ]
        )

    else:

        budget = 0.0


    summe = query_einen(

        """
        SELECT
            COALESCE(
                SUM(betrag),
                0
            ) AS summe

        FROM ausgaben

        WHERE benutzer_id = %s
        """,

        """
        SELECT
            COALESCE(
                SUM(betrag),
                0
            ) AS summe

        FROM ausgaben

        WHERE benutzer_id = ?
        """,

        (
            benutzer_id,
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
            prozent_verbraucht,
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

            TO_CHAR(
                datum,
                'DD.MM.YYYY HH24:MI'
            ) AS datum

        FROM ausgaben

        WHERE benutzer_id = %s

        ORDER BY datum DESC
        """,

        """
        SELECT
            id,
            beschreibung,
            kategorie,
            betrag,
            datum

        FROM ausgaben

        WHERE benutzer_id = ?

        ORDER BY id DESC
        """,

        (
            benutzer_id,
        )
    )


    return render_template(

        "finanzen.html",

        benutzer=session[
            "benutzer"
        ],

        budget=budget,

        ausgegeben=ausgegeben,

        verfuegbar=verfuegbar,

        prozent_verbraucht=
            prozent_verbraucht,

        ausgaben=ausgaben
    )


# --------------------------------------------------
# BUDGET SPEICHERN
# --------------------------------------------------

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

    except ValueError:

        return redirect(
            "/finanzen"
        )


    if betrag < 0:

        betrag = 0


    vorhandenes_budget = (
        query_einen(

            """
            SELECT id
            FROM budgets
            WHERE benutzer_id = %s
            """,

            """
            SELECT id
            FROM budgets
            WHERE benutzer_id = ?
            """,

            (
                benutzer_id,
            )
        )
    )


    if vorhandenes_budget:

        execute_query(

            """
            UPDATE budgets

            SET betrag = %s

            WHERE benutzer_id = %s
            """,

            """
            UPDATE budgets

            SET betrag = ?

            WHERE benutzer_id = ?
            """,

            (
                betrag,
                benutzer_id
            )
        )

    else:

        execute_query(

            """
            INSERT INTO budgets
            (
                benutzer_id,
                betrag
            )

            VALUES (
                %s,
                %s
            )
            """,

            """
            INSERT INTO budgets
            (
                benutzer_id,
                betrag
            )

            VALUES (?, ?)
            """,

            (
                benutzer_id,
                betrag
            )
        )


    return redirect(
        "/finanzen"
    )


# --------------------------------------------------
# AUSGABE HINZUFÜGEN
# --------------------------------------------------

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


    beschreibung = request.form[
        "beschreibung"
    ].strip()


    kategorie = request.form[
        "kategorie"
    ].strip()


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
                betrag
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
                benutzer_id,
                beschreibung,
                kategorie,
                betrag
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
                datum
            )

            VALUES (?, ?, ?, ?, ?)
            """,

            (
                benutzer_id,
                beschreibung,
                kategorie,
                betrag,

                datetime.now().strftime(
                    "%d.%m.%Y %H:%M"
                )
            )
        )


    return redirect(
        "/finanzen"
    )


# --------------------------------------------------
# AUSGABE LÖSCHEN
# --------------------------------------------------

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


# --------------------------------------------------
# ADMIN
# --------------------------------------------------

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
        meldung=meldung
    )


# --------------------------------------------------
# BENUTZERNAME ÄNDERN
# --------------------------------------------------

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


# --------------------------------------------------
# PASSWORT / EINMALPASSWORT ÄNDERN
# --------------------------------------------------

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


# --------------------------------------------------
# BENUTZER LÖSCHEN
# --------------------------------------------------

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
        and benutzer["rolle"]
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


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# --------------------------------------------------
# START
# --------------------------------------------------

datenbank_erstellen()


if __name__ == "__main__":

    app.run(
        debug=True
    )