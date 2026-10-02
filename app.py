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
# GEHEIME EINSTELLUNGEN
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
# DATENBANK-HILFSFUNKTIONEN
# --------------------------------------------------

def postgres_verwenden():
    return DATABASE_URL is not None and psycopg2 is not None


def datenbank():
    if postgres_verwenden():
        return psycopg2.connect(DATABASE_URL)

    db = sqlite3.connect("users.db")
    db.row_factory = sqlite3.Row
    return db


def query_einen(sql_postgres, sql_sqlite, werte=()):
    db = datenbank()

    if postgres_verwenden():
        cursor = db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        cursor.execute(sql_postgres, werte)
        ergebnis = cursor.fetchone()
        cursor.close()
    else:
        ergebnis = db.execute(
            sql_sqlite,
            werte
        ).fetchone()

    db.close()
    return ergebnis


def query_alle(sql_postgres, sql_sqlite, werte=()):
    db = datenbank()

    if postgres_verwenden():
        cursor = db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        cursor.execute(sql_postgres, werte)
        ergebnis = cursor.fetchall()
        cursor.close()
    else:
        ergebnis = db.execute(
            sql_sqlite,
            werte
        ).fetchall()

    db.close()
    return ergebnis


def execute_query(sql_postgres, sql_sqlite, werte=()):
    db = datenbank()

    try:
        if postgres_verwenden():
            cursor = db.cursor()
            cursor.execute(sql_postgres, werte)
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
# DATENBANK ERSTELLEN
# --------------------------------------------------

def datenbank_erstellen():
    db = datenbank()

    if postgres_verwenden():
        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS benutzer (
                id SERIAL PRIMARY KEY,
                benutzername VARCHAR(100) UNIQUE NOT NULL,
                passwort TEXT NOT NULL,
                rolle VARCHAR(50) NOT NULL
            )
        """)

        db.commit()
        cursor.close()

    else:
        db.execute("""
            CREATE TABLE IF NOT EXISTS benutzer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benutzername TEXT UNIQUE NOT NULL,
                passwort TEXT NOT NULL,
                rolle TEXT NOT NULL
            )
        """)

        db.commit()

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
            (benutzername, passwort, rolle)
            VALUES (%s, %s, %s)
            """,
            """
            INSERT INTO benutzer
            (benutzername, passwort, rolle)
            VALUES (?, ?, ?)
            """,
            (
                "joel",
                generate_password_hash(ADMIN_PASSWORD),
                "admin"
            )
        )


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    fehler = ""

    if request.method == "POST":
        benutzername = request.form["benutzername"].strip()
        passwort = request.form["passwort"]

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
            (benutzername,)
        )

        if benutzer and check_password_hash(
            benutzer["passwort"],
            passwort
        ):
            session["benutzer_id"] = benutzer["id"]
            session["benutzer"] = benutzer["benutzername"]
            session["rolle"] = benutzer["rolle"]

            return redirect("/dashboard")

        fehler = "Benutzername oder Passwort falsch."

    return render_template(
        "login.html",
        fehler=fehler
    )


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
def dashboard():
    if "benutzer" not in session:
        return redirect("/")

    return render_template(
        "dashboard.html",
        benutzer=session["benutzer"],
        rolle=session["rolle"]
    )


# --------------------------------------------------
# ADMIN
# --------------------------------------------------

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if session.get("rolle") != "admin":
        return redirect("/dashboard")

    meldung = ""

    if request.method == "POST":
        neuer_name = request.form["benutzername"].strip()
        neues_passwort = request.form["passwort"]

        if neuer_name == "":
            meldung = "Bitte einen Benutzernamen eingeben."

        elif neues_passwort == "":
            meldung = "Bitte ein Passwort eingeben."

        else:
            try:
                execute_query(
                    """
                    INSERT INTO benutzer
                    (benutzername, passwort, rolle)
                    VALUES (%s, %s, %s)
                    """,
                    """
                    INSERT INTO benutzer
                    (benutzername, passwort, rolle)
                    VALUES (?, ?, ?)
                    """,
                    (
                        neuer_name,
                        generate_password_hash(neues_passwort),
                        "benutzer"
                    )
                )

                meldung = "Benutzer wurde erstellt."

            except Exception:
                meldung = "Dieser Benutzername existiert bereits."

    benutzer_liste = query_alle(
        """
        SELECT id, benutzername, rolle
        FROM benutzer
        ORDER BY id
        """,
        """
        SELECT id, benutzername, rolle
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
def benutzername_aendern(benutzer_id):
    if session.get("rolle") != "admin":
        return redirect("/dashboard")

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
        (benutzer_id,)
    )

    if benutzer is None:
        return redirect("/admin")

    meldung = ""

    if request.method == "POST":
        neuer_name = request.form["benutzername"].strip()

        if neuer_name == "":
            meldung = "Bitte einen Benutzernamen eingeben."

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

                meldung = "Benutzername wurde geändert."

                if session.get("benutzer_id") == benutzer_id:
                    session["benutzer"] = neuer_name

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
                    (benutzer_id,)
                )

            except Exception:
                meldung = "Dieser Benutzername existiert bereits."

    return render_template(
        "benutzername.html",
        benutzer=benutzer,
        meldung=meldung
    )


# --------------------------------------------------
# PASSWORT ÄNDERN
# --------------------------------------------------

@app.route(
    "/passwort-aendern/<int:benutzer_id>",
    methods=["GET", "POST"]
)
def passwort_aendern(benutzer_id):
    if session.get("rolle") != "admin":
        return redirect("/dashboard")

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
        (benutzer_id,)
    )

    if benutzer is None:
        return redirect("/admin")

    meldung = ""

    if request.method == "POST":
        neues_passwort = request.form["passwort"]

        if neues_passwort == "":
            meldung = "Bitte ein neues Passwort eingeben."

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
                    generate_password_hash(neues_passwort),
                    benutzer_id
                )
            )

            meldung = "Passwort wurde geändert."

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
def benutzer_loeschen(benutzer_id):
    if session.get("rolle") != "admin":
        return redirect("/dashboard")

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
        (benutzer_id,)
    )

    if benutzer and benutzer["rolle"] != "admin":
        execute_query(
            """
            DELETE FROM benutzer
            WHERE id = %s
            """,
            """
            DELETE FROM benutzer
            WHERE id = ?
            """,
            (benutzer_id,)
        )

    return redirect("/admin")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# --------------------------------------------------
# DATENBANK BEIM START PRÜFEN
# --------------------------------------------------

datenbank_erstellen()


# --------------------------------------------------
# LOKALER START
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)