import os
import sqlite3

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

DATABASE_URL = os.environ.get("DATABASE_URL")


# --------------------------------------------------
# DATENBANK
# --------------------------------------------------

def postgres_verwenden():
    return bool(DATABASE_URL)


def datenbank():

    if postgres_verwenden():

        if psycopg2 is None:
            raise RuntimeError(
                "DATABASE_URL ist gesetzt, aber psycopg2 ist nicht installiert."
            )

        return psycopg2.connect(DATABASE_URL)

    # SQLite nur für lokale Entwicklung
    db = sqlite3.connect("users.db")
    db.row_factory = sqlite3.Row

    return db


def query_einen(sql_postgres, sql_sqlite, werte=()):

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
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


def query_alle(sql_postgres, sql_sqlite, werte=()):

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
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


def execute_query(sql_postgres, sql_sqlite, werte=()):

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
# TABELLEN ERSTELLEN / AKTUALISIEREN
# --------------------------------------------------

def datenbank_erstellen():

    db = datenbank()

    try:

        if postgres_verwenden():

            cursor = db.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS benutzer (
                    id SERIAL PRIMARY KEY,
                    benutzername VARCHAR(100) UNIQUE NOT NULL,
                    passwort TEXT NOT NULL,
                    rolle VARCHAR(50) NOT NULL,
                    passwort_muss_geaendert BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)

            # Falls die Tabelle schon von unserer alten Version existiert
            cursor.execute("""
                ALTER TABLE benutzer
                ADD COLUMN IF NOT EXISTS
                passwort_muss_geaendert BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cursor.close()

        else:

            db.execute("""
                CREATE TABLE IF NOT EXISTS benutzer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    benutzername TEXT UNIQUE NOT NULL,
                    passwort TEXT NOT NULL,
                    rolle TEXT NOT NULL,
                    passwort_muss_geaendert INTEGER NOT NULL DEFAULT 0
                )
            """)

            spalten = db.execute(
                "PRAGMA table_info(benutzer)"
            ).fetchall()

            spalten_namen = [
                spalte["name"]
                for spalte in spalten
            ]

            if "passwort_muss_geaendert" not in spalten_namen:

                db.execute("""
                    ALTER TABLE benutzer
                    ADD COLUMN passwort_muss_geaendert
                    INTEGER NOT NULL DEFAULT 0
                """)

        db.commit()

    finally:

        db.close()


    # Prüfen, ob bereits ein Admin existiert

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
            VALUES (%s, %s, %s, %s)
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

@app.route("/", methods=["GET", "POST"])
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


        if benutzer and check_password_hash(
            benutzer["passwort"],
            passwort
        ):

            session["benutzer_id"] = benutzer["id"]

            session["benutzer"] = (
                benutzer["benutzername"]
            )

            session["rolle"] = (
                benutzer["rolle"]
            )

            session[
                "passwort_muss_geaendert"
            ] = bool(
                benutzer[
                    "passwort_muss_geaendert"
                ]
            )


            # Benutzer hat ein Einmalpasswort
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
            "Benutzername oder Passwort falsch."
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
    methods=["GET", "POST"]
)
def erstes_passwort():

    if "benutzer_id" not in session:

        return redirect("/")


    # Wenn kein Passwortwechsel notwendig ist
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
                "Das Passwort muss mindestens "
                "6 Zeichen haben."
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
        benutzer=session.get("benutzer")
    )


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
def dashboard():

    if "benutzer_id" not in session:

        return redirect("/")


    if session.get(
        "passwort_muss_geaendert"
    ):

        return redirect(
            "/erstes-passwort"
        )


    return render_template(
        "dashboard.html",
        benutzer=session["benutzer"],
        rolle=session["rolle"]
    )


# --------------------------------------------------
# ADMIN
# --------------------------------------------------

@app.route(
    "/admin",
    methods=["GET", "POST"]
)
def admin():

    if session.get("rolle") != "admin":

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
                "Bitte einen Benutzernamen eingeben."
            )


        elif len(einmalpasswort) < 4:

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
                    VALUES (%s, %s, %s, TRUE)
                    """,

                    """
                    INSERT INTO benutzer
                    (
                        benutzername,
                        passwort,
                        rolle,
                        passwort_muss_geaendert
                    )
                    VALUES (?, ?, ?, 1)
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
                    "Das Passwort ist ein Einmalpasswort."
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
        benutzer_liste=benutzer_liste,
        meldung=meldung
    )


# --------------------------------------------------
# BENUTZERNAME ÄNDERN
# --------------------------------------------------

@app.route(
    "/benutzername-aendern/<int:benutzer_id>",
    methods=["GET", "POST"]
)
def benutzername_aendern(
    benutzer_id
):

    if session.get("rolle") != "admin":

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


                meldung = (
                    "Benutzername wurde dauerhaft geändert."
                )


                if session.get(
                    "benutzer_id"
                ) == benutzer_id:

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
# NEUES EINMALPASSWORT SETZEN
# --------------------------------------------------

@app.route(
    "/passwort-aendern/<int:benutzer_id>",
    methods=["GET", "POST"]
)
def passwort_aendern(
    benutzer_id
):

    if session.get("rolle") != "admin":

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


        if len(neues_passwort) < 4:

            meldung = (
                "Das Einmalpasswort muss "
                "mindestens 4 Zeichen haben."
            )


        else:

            # Bei normalen Benutzern:
            # Neues Einmalpasswort + Pflichtwechsel
            if benutzer["rolle"] != "admin":

                execute_query(

                    """
                    UPDATE benutzer
                    SET
                        passwort = %s,
                        passwort_muss_geaendert = TRUE
                    WHERE id = %s
                    """,

                    """
                    UPDATE benutzer
                    SET
                        passwort = ?,
                        passwort_muss_geaendert = 1
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
                    "Neues Einmalpasswort wurde gesetzt."
                )


            # Admin-Passwort direkt ändern
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
                    "Admin-Passwort wurde geändert."
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
    methods=["POST"]
)
def benutzer_loeschen(
    benutzer_id
):

    if session.get("rolle") != "admin":

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
        and benutzer["rolle"] != "admin"
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

    app.run(debug=True)